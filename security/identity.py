"""Authentication, users, sessions, and authorization for Capital Intelligence."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from portfolio.constants import CANONICAL_PORTFOLIO_CODE


class AuthenticationError(RuntimeError):
    """Base authentication failure."""


class InvalidCredentialsError(AuthenticationError):
    """Credentials are absent, invalid, expired, or revoked."""


class AuthorizationError(AuthenticationError):
    """An authenticated principal lacks the requested permission."""


class IdentityConflictError(AuthenticationError):
    """A unique identity or immutable grant conflicts with existing data."""


class UserRole(str, Enum):
    INVESTOR = "investor"
    ADVISOR = "advisor"
    ADMINISTRATOR = "administrator"
    AUDITOR = "auditor"


class MandatePermission(str, Enum):
    VIEW = "view"
    MANAGE = "manage"


class InvestorPermission(str, Enum):
    VIEW = "view"
    REFLECT = "reflect"


@dataclass(frozen=True, slots=True)
class MandateGrant:
    mandate_code: str
    permission: MandatePermission


@dataclass(frozen=True, slots=True)
class InvestorGrant:
    investor_identifier: str
    permission: InvestorPermission


@dataclass(frozen=True, slots=True)
class UserAccount:
    user_id: str
    email: str
    display_name: str
    investor_identifier: str | None
    is_active: bool
    roles: tuple[UserRole, ...]
    mandate_grants: tuple[MandateGrant, ...]
    investor_grants: tuple[InvestorGrant, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    user_id: str
    session_id: str
    email: str
    display_name: str
    investor_identifier: str | None
    roles: frozenset[UserRole]
    mandate_grants: tuple[MandateGrant, ...]
    investor_grants: tuple[InvestorGrant, ...]

    @property
    def is_administrator(self) -> bool:
        return UserRole.ADMINISTRATOR in self.roles

    @property
    def is_auditor(self) -> bool:
        return UserRole.AUDITOR in self.roles

    def can_access_mandate(self, mandate_code: str, *, write: bool = False) -> bool:
        normalized = _mandate_code(mandate_code)
        if normalized != CANONICAL_PORTFOLIO_CODE:
            return False
        if self.is_administrator:
            return True
        if self.is_auditor:
            return not write
        for grant in self.mandate_grants:
            if grant.mandate_code != normalized:
                continue
            return not write or grant.permission is MandatePermission.MANAGE
        return False

    def can_access_investor(
        self,
        investor_identifier: str,
        *, write: bool = False,
    ) -> bool:
        normalized = _required_text(investor_identifier, "investor_identifier")
        if self.is_administrator:
            return True
        if self.is_auditor:
            return not write
        if self.investor_identifier == normalized:
            return True
        for grant in self.investor_grants:
            if grant.investor_identifier != normalized:
                continue
            return not write or grant.permission is InvestorPermission.REFLECT
        return False

    @classmethod
    def testing_system(cls) -> "AuthenticatedPrincipal":
        return cls(
            user_id="system:test",
            session_id="session:test",
            email="system@test.invalid",
            display_name="Test System",
            investor_identifier="primary",
            roles=frozenset({UserRole.ADMINISTRATOR}),
            mandate_grants=(),
            investor_grants=(),
        )


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    token_type: str = "bearer"


@dataclass(frozen=True, slots=True)
class AuthenticationReadiness:
    name: str
    required: bool
    ready: bool
    detail: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _email(value: str) -> str:
    normalized = _required_text(value, "email").casefold()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("email must be valid")
    return normalized


def _mandate_code(value: str) -> str:
    return _required_text(value, "mandate_code").upper()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_password(password: str, *, minimum_length: int = 12) -> None:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if len(password) < minimum_length:
        raise ValueError(f"password must contain at least {minimum_length} characters")
    categories = sum(
        (
            any(character.islower() for character in password),
            any(character.isupper() for character in password),
            any(character.isdigit() for character in password),
            any(not character.isalnum() for character in password),
        )
    )
    if categories < 3:
        raise ValueError("password must use at least three character categories")


def hash_password(
    password: str,
    *,
    minimum_length: int = 12,
    salt: bytes | None = None,
) -> str:
    validate_password(password, minimum_length=minimum_length)
    resolved_salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=resolved_salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )
    return "scrypt-v1$16384$8$1$" + _b64encode(resolved_salt) + "$" + _b64encode(derived)


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_value, digest_value = encoded.split("$")
        if algorithm != "scrypt-v1":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt_value),
            n=int(n_value),
            r=int(r_value),
            p=int(p_value),
            dklen=len(_b64decode(digest_value)),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(derived, _b64decode(digest_value))
    except (TypeError, ValueError):
        return False


_DUMMY_PASSWORD_HASH = hash_password(
    "Not-A-Real-Password-42!",
    salt=b"capital-intel-v1",
)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SQLiteIdentityStore:
    """SQLite identity store with hashed passwords, hashed tokens, and audit history."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
        access_ttl: timedelta = timedelta(minutes=15),
        refresh_ttl: timedelta = timedelta(days=30),
        password_minimum_length: int = 12,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or _utc_now
        self.access_ttl = access_ttl
        self.refresh_ttl = refresh_ttl
        self.password_minimum_length = password_minimum_length
        if access_ttl <= timedelta(0) or refresh_ttl <= access_ttl:
            raise ValueError("refresh_ttl must be longer than a positive access_ttl")
        if password_minimum_length < 10:
            raise ValueError("password_minimum_length must be at least 10")
        if self.path.exists() and self.path.is_dir():
            raise ValueError("identity path must be a file")
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    investor_identifier TEXT UNIQUE,
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_roles (
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    PRIMARY KEY (user_id, role),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS user_mandates (
                    user_id TEXT NOT NULL,
                    mandate_code TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, mandate_code),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS user_investor_access (
                    user_id TEXT NOT NULL,
                    investor_identifier TEXT NOT NULL,
                    permission TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, investor_identifier),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    access_token_hash TEXT NOT NULL UNIQUE,
                    refresh_token_hash TEXT NOT NULL UNIQUE,
                    access_expires_at TEXT NOT NULL,
                    refresh_expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS auth_sessions_user
                ON auth_sessions (user_id, refresh_expires_at DESC);
                CREATE TABLE IF NOT EXISTS auth_audit_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    email TEXT,
                    success INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT
                );
                CREATE TRIGGER IF NOT EXISTS auth_audit_prevent_update
                BEFORE UPDATE ON auth_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'authentication audit history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS auth_audit_prevent_delete
                BEFORE DELETE ON auth_audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'authentication audit history is append-only');
                END;
                """
            )

    def count_users(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        investor_identifier: str | None = None,
        roles: Iterable[UserRole | str] = (UserRole.INVESTOR,),
        user_id: str | None = None,
    ) -> UserAccount:
        normalized_email = _email(email)
        normalized_name = _required_text(display_name, "display_name")
        normalized_investor = (
            None
            if investor_identifier is None
            else _required_text(investor_identifier, "investor_identifier")
        )
        resolved_roles = tuple(sorted({UserRole(role) for role in roles}, key=lambda role: role.value))
        if not resolved_roles:
            raise ValueError("at least one role is required")
        resolved_user_id = user_id or f"user:{uuid4()}"
        now = self._now()
        encoded_password = hash_password(
            password,
            minimum_length=self.password_minimum_length,
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, email, display_name, investor_identifier,
                        password_hash, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        resolved_user_id,
                        normalized_email,
                        normalized_name,
                        normalized_investor,
                        encoded_password,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.executemany(
                    "INSERT INTO user_roles (user_id, role) VALUES (?, ?)",
                    [(resolved_user_id, role.value) for role in resolved_roles],
                )
        except sqlite3.IntegrityError as error:
            raise IdentityConflictError("email or investor identity already exists") from error
        self._audit(
            "user_created",
            user_id=resolved_user_id,
            email=normalized_email,
            success=True,
            detail="User account created.",
        )
        return self.get_user(resolved_user_id)

    def bootstrap_administrator(
        self,
        *,
        email: str | None,
        password: str | None,
        display_name: str = "Platform Administrator",
    ) -> UserAccount | None:
        if not email and not password:
            return None
        if not email or not password:
            raise ValueError("bootstrap administrator email and password must be supplied together")
        existing = self.get_user_by_email(email)
        if existing is not None:
            return existing
        return self.create_user(
            email=email,
            display_name=display_name,
            password=password,
            roles=(UserRole.ADMINISTRATOR,),
        )

    def list_users(self) -> tuple[UserAccount, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT user_id FROM users ORDER BY created_at, user_id"
            ).fetchall()
        return tuple(self.get_user(row["user_id"]) for row in rows)

    def get_user(self, user_id: str) -> UserAccount:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE user_id = ?",
                (_required_text(user_id, "user_id"),),
            ).fetchone()
        if row is None:
            raise KeyError("user was not found")
        return self._account_from_row(row)

    def get_user_by_email(self, email: str) -> UserAccount | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (_email(email),),
            ).fetchone()
        return None if row is None else self._account_from_row(row)

    def assign_role(self, user_id: str, role: UserRole | str) -> UserAccount:
        resolved_user_id = self.get_user(user_id).user_id
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, ?)",
                (resolved_user_id, UserRole(role).value),
            )
        self._audit(
            "role_granted",
            user_id=resolved_user_id,
            success=True,
            detail=f"Role granted: {UserRole(role).value}.",
        )
        return self.get_user(resolved_user_id)

    def assign_mandate(
        self,
        user_id: str,
        mandate_code: str,
        permission: MandatePermission | str = MandatePermission.VIEW,
    ) -> UserAccount:
        resolved_user_id = self.get_user(user_id).user_id
        normalized_code = _mandate_code(mandate_code)
        if normalized_code != CANONICAL_PORTFOLIO_CODE:
            raise ValueError(
                f"only {CANONICAL_PORTFOLIO_CODE} portfolio access may be granted"
            )
        resolved_permission = MandatePermission(permission)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_mandates (
                    user_id, mandate_code, permission, granted_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, mandate_code) DO UPDATE SET
                    permission = excluded.permission,
                    granted_at = excluded.granted_at
                """,
                (
                    resolved_user_id,
                    normalized_code,
                    resolved_permission.value,
                    self._now().isoformat(),
                ),
            )
        self._audit(
            "mandate_granted",
            user_id=resolved_user_id,
            success=True,
            detail=f"{normalized_code}:{resolved_permission.value}",
        )
        return self.get_user(resolved_user_id)

    def grant_investor_access(
        self,
        user_id: str,
        investor_identifier: str,
        permission: InvestorPermission | str = InvestorPermission.VIEW,
    ) -> UserAccount:
        resolved_user_id = self.get_user(user_id).user_id
        normalized_investor = _required_text(investor_identifier, "investor_identifier")
        resolved_permission = InvestorPermission(permission)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_investor_access (
                    user_id, investor_identifier, permission, granted_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, investor_identifier) DO UPDATE SET
                    permission = excluded.permission,
                    granted_at = excluded.granted_at
                """,
                (
                    resolved_user_id,
                    normalized_investor,
                    resolved_permission.value,
                    self._now().isoformat(),
                ),
            )
        self._audit(
            "investor_access_granted",
            user_id=resolved_user_id,
            success=True,
            detail=f"{normalized_investor}:{resolved_permission.value}",
        )
        return self.get_user(resolved_user_id)

    def disable_user(self, user_id: str) -> UserAccount:
        account = self.get_user(user_id)
        now = self._now().isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET is_active = 0, updated_at = ? WHERE user_id = ?",
                (now, account.user_id),
            )
            connection.execute(
                """
                UPDATE auth_sessions SET revoked_at = ?
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (now, account.user_id),
            )
        self._audit(
            "user_disabled",
            user_id=account.user_id,
            email=account.email,
            success=True,
            detail="User disabled and active sessions revoked.",
        )
        return self.get_user(account.user_id)

    def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        normalized_email = _email(email)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        encoded = _DUMMY_PASSWORD_HASH if row is None else row["password_hash"]
        password_ok = verify_password(password, encoded)
        if row is None or not password_ok or not bool(row["is_active"]):
            self._audit(
                "login",
                user_id=None if row is None else row["user_id"],
                email=normalized_email,
                success=False,
                detail="Invalid credentials or inactive account.",
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise InvalidCredentialsError("invalid email or password")
        tokens = self._create_session(row["user_id"])
        self._audit(
            "login",
            user_id=row["user_id"],
            email=normalized_email,
            success=True,
            detail="Login succeeded.",
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return tokens

    def refresh(self, refresh_token: str) -> TokenPair:
        token_hash = _token_hash(_required_text(refresh_token, "refresh_token"))
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sessions.*, users.email, users.is_active
                FROM auth_sessions AS sessions
                JOIN users ON users.user_id = sessions.user_id
                WHERE sessions.refresh_token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or datetime.fromisoformat(row["refresh_expires_at"]) <= now
                or not bool(row["is_active"])
            ):
                raise InvalidCredentialsError("refresh token is invalid or expired")
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?",
                (now.isoformat(), row["session_id"]),
            )
        tokens = self._create_session(row["user_id"])
        self._audit(
            "refresh",
            user_id=row["user_id"],
            email=row["email"],
            success=True,
            detail="Refresh token rotated.",
        )
        return tokens

    def principal_for_access_token(self, access_token: str) -> AuthenticatedPrincipal:
        token_hash = _token_hash(_required_text(access_token, "access_token"))
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sessions.*, users.email, users.display_name,
                       users.investor_identifier, users.is_active
                FROM auth_sessions AS sessions
                JOIN users ON users.user_id = sessions.user_id
                WHERE sessions.access_token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if (
                row is None
                or row["revoked_at"] is not None
                or datetime.fromisoformat(row["access_expires_at"]) <= now
                or not bool(row["is_active"])
            ):
                raise InvalidCredentialsError("access token is invalid or expired")
            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE session_id = ?",
                (now.isoformat(), row["session_id"]),
            )
        account = self.get_user(row["user_id"])
        return AuthenticatedPrincipal(
            user_id=account.user_id,
            session_id=row["session_id"],
            email=account.email,
            display_name=account.display_name,
            investor_identifier=account.investor_identifier,
            roles=frozenset(account.roles),
            mandate_grants=account.mandate_grants,
            investor_grants=account.investor_grants,
        )

    def logout(self, access_token: str) -> None:
        token_hash = _token_hash(_required_text(access_token, "access_token"))
        now = self._now().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT sessions.session_id, sessions.user_id, users.email
                FROM auth_sessions AS sessions
                JOIN users ON users.user_id = sessions.user_id
                WHERE sessions.access_token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """
                UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?)
                WHERE session_id = ?
                """,
                (now, row["session_id"]),
            )
        self._audit(
            "logout",
            user_id=row["user_id"],
            email=row["email"],
            success=True,
            detail="Session revoked.",
        )

    def audit_events(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive int")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM auth_audit_events
                ORDER BY occurred_at DESC, event_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def readiness(self, *, required: bool = True) -> AuthenticationReadiness:
        try:
            count = self.count_users()
        except (OSError, sqlite3.Error) as error:
            return AuthenticationReadiness(
                name="identity",
                required=required,
                ready=False,
                detail=f"identity store is unavailable: {error}",
            )
        if required and count == 0:
            return AuthenticationReadiness(
                name="identity",
                required=True,
                ready=False,
                detail="identity store contains no users; configure a bootstrap administrator",
            )
        return AuthenticationReadiness(
            name="identity",
            required=required,
            ready=True,
            detail=f"identity store ready with {count} user account(s)",
        )

    def _create_session(self, user_id: str) -> TokenPair:
        now = self._now()
        access_expires_at = now + self.access_ttl
        refresh_expires_at = now + self.refresh_ttl
        access_token = "ci_access_" + secrets.token_urlsafe(32)
        refresh_token = "ci_refresh_" + secrets.token_urlsafe(48)
        session_id = f"session:{uuid4()}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (
                    session_id, user_id, access_token_hash, refresh_token_hash,
                    access_expires_at, refresh_expires_at, revoked_at,
                    created_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    session_id,
                    user_id,
                    _token_hash(access_token),
                    _token_hash(refresh_token),
                    access_expires_at.isoformat(),
                    refresh_expires_at.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )

    def _account_from_row(self, row: sqlite3.Row) -> UserAccount:
        with self._connect() as connection:
            role_rows = connection.execute(
                "SELECT role FROM user_roles WHERE user_id = ? ORDER BY role",
                (row["user_id"],),
            ).fetchall()
            mandate_rows = connection.execute(
                """
                SELECT mandate_code, permission FROM user_mandates
                WHERE user_id = ? ORDER BY mandate_code
                """,
                (row["user_id"],),
            ).fetchall()
            investor_rows = connection.execute(
                """
                SELECT investor_identifier, permission FROM user_investor_access
                WHERE user_id = ? ORDER BY investor_identifier
                """,
                (row["user_id"],),
            ).fetchall()
        return UserAccount(
            user_id=row["user_id"],
            email=row["email"],
            display_name=row["display_name"],
            investor_identifier=row["investor_identifier"],
            is_active=bool(row["is_active"]),
            roles=tuple(UserRole(item["role"]) for item in role_rows),
            mandate_grants=tuple(
                MandateGrant(
                    mandate_code=item["mandate_code"],
                    permission=MandatePermission(item["permission"]),
                )
                for item in mandate_rows
            ),
            investor_grants=tuple(
                InvestorGrant(
                    investor_identifier=item["investor_identifier"],
                    permission=InvestorPermission(item["permission"]),
                )
                for item in investor_rows
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _audit(
        self,
        event_type: str,
        *,
        user_id: str | None = None,
        email: str | None = None,
        success: bool,
        detail: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO auth_audit_events (
                    event_id, occurred_at, event_type, user_id, email,
                    success, detail, ip_address, user_agent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"auth-audit:{uuid4()}",
                    self._now().isoformat(),
                    _required_text(event_type, "event_type"),
                    user_id,
                    email,
                    int(success),
                    _required_text(detail, "detail"),
                    ip_address,
                    user_agent,
                ),
            )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("identity clock must return a timezone-aware datetime")
        return value

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


class AuthenticationService:
    """Application-facing identity service with an explicit test compatibility mode."""

    def __init__(self, store: SQLiteIdentityStore, *, required: bool = True) -> None:
        if not isinstance(store, SQLiteIdentityStore):
            raise TypeError("store must be a SQLiteIdentityStore")
        self.store = store
        self.required = bool(required)

    def principal_for_access_token(self, token: str | None) -> AuthenticatedPrincipal:
        if not self.required:
            return AuthenticatedPrincipal.testing_system()
        if token is None:
            raise InvalidCredentialsError("authentication is required")
        return self.store.principal_for_access_token(token)

    def readiness(self) -> AuthenticationReadiness:
        return self.store.readiness(required=self.required)


__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationError",
    "AuthenticationReadiness",
    "AuthenticationService",
    "AuthorizationError",
    "IdentityConflictError",
    "InvalidCredentialsError",
    "InvestorGrant",
    "InvestorPermission",
    "MandateGrant",
    "MandatePermission",
    "SQLiteIdentityStore",
    "TokenPair",
    "UserAccount",
    "UserRole",
    "hash_password",
    "validate_password",
    "verify_password",
]
