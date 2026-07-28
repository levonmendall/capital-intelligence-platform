"""Append-only user consent for one exact paper implementation.

This authority is intentionally narrower than the controlled paper-test release,
launch, and runtime authorities. It records whether an authenticated portfolio
manager supports one exact CIO decision and construction payload. It never
creates live-money, broker, custody, or launch authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from portfolio.constants import CANONICAL_PORTFOLIO_CODE


class PaperDecisionApprovalError(RuntimeError):
    """Raised when exact user consent is unavailable or invalid."""


class PaperDecisionApprovalIntegrityError(PaperDecisionApprovalError):
    """Raised when the append-only approval chain is invalid."""


class PaperDecisionApprovalState(str, Enum):
    APPROVED = "approved"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXECUTED = "executed"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_construction_sha256(value: Mapping[str, Any]) -> str:
    """Return the exact canonical hash bound to the user's decision."""

    if not isinstance(value, Mapping):
        raise TypeError("construction payload must be a mapping")
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PaperDecisionApprovalEvent:
    identifier: str
    decision_identifier: str
    construction_identifier: str
    construction_sha256: str
    state: PaperDecisionApprovalState
    actor_user_id: str
    actor_session_id: str
    occurred_at: datetime
    expires_at: datetime | None
    rationale: str
    execution_identifier: str | None = None
    portfolio_code: str = CANONICAL_PORTFOLIO_CODE
    schema_version: str = "paper-decision-approval.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "decision_identifier",
            "construction_identifier",
            "actor_user_id",
            "actor_session_id",
            "rationale",
            "portfolio_code",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        normalized_hash = _text(
            self.construction_sha256,
            field_name="construction_sha256",
        ).lower()
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_hash
        ):
            raise ValueError("construction_sha256 must be a SHA-256 hex digest")
        object.__setattr__(self, "construction_sha256", normalized_hash)
        if not isinstance(self.state, PaperDecisionApprovalState):
            raise TypeError("state must be PaperDecisionApprovalState")
        _aware(self.occurred_at, field_name="occurred_at")
        if self.expires_at is not None:
            _aware(self.expires_at, field_name="expires_at")
            if self.expires_at <= self.occurred_at:
                raise ValueError("expires_at must follow occurred_at")
        if self.portfolio_code != CANONICAL_PORTFOLIO_CODE:
            raise ValueError("paper approval is limited to the canonical portfolio")
        if self.schema_version != "paper-decision-approval.v1":
            raise ValueError("unsupported paper decision approval schema")
        if self.state is PaperDecisionApprovalState.APPROVED and self.expires_at is None:
            raise ValueError("approved paper decisions require an expiry")
        if self.state is PaperDecisionApprovalState.EXECUTED:
            object.__setattr__(
                self,
                "execution_identifier",
                _text(self.execution_identifier, field_name="execution_identifier"),
            )
        elif self.execution_identifier is not None:
            raise ValueError("only an executed event may include execution_identifier")

    def active_at(self, value: datetime) -> bool:
        timestamp = _aware(value, field_name="value")
        return (
            self.state is PaperDecisionApprovalState.APPROVED
            and self.occurred_at <= timestamp
            and self.expires_at is not None
            and timestamp < self.expires_at
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "decision_identifier": self.decision_identifier,
            "construction_identifier": self.construction_identifier,
            "construction_sha256": self.construction_sha256,
            "state": self.state.value,
            "actor_user_id": self.actor_user_id,
            "actor_session_id": self.actor_session_id,
            "occurred_at": self.occurred_at.isoformat(),
            "expires_at": None if self.expires_at is None else self.expires_at.isoformat(),
            "rationale": self.rationale,
            "execution_identifier": self.execution_identifier,
            "portfolio_code": self.portfolio_code,
            "schema_version": self.schema_version,
            "real_money_authorized": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperDecisionApprovalEvent":
        return cls(
            identifier=str(value["identifier"]),
            decision_identifier=str(value["decision_identifier"]),
            construction_identifier=str(value["construction_identifier"]),
            construction_sha256=str(value["construction_sha256"]),
            state=PaperDecisionApprovalState(str(value["state"])),
            actor_user_id=str(value["actor_user_id"]),
            actor_session_id=str(value["actor_session_id"]),
            occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
            expires_at=(
                None
                if value.get("expires_at") is None
                else datetime.fromisoformat(str(value["expires_at"]))
            ),
            rationale=str(value["rationale"]),
            execution_identifier=(
                None
                if value.get("execution_identifier") is None
                else str(value["execution_identifier"])
            ),
            portfolio_code=str(value.get("portfolio_code", CANONICAL_PORTFOLIO_CODE)),
            schema_version=str(value.get("schema_version", "paper-decision-approval.v1")),
        )


class SQLitePaperDecisionApprovalStore:
    """Tamper-evident user approval history for exact paper constructions."""

    _TABLE = "paper_decision_approval_events"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("paper decision approval path must be a file")
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    decision_identifier TEXT NOT NULL,
                    construction_identifier TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                )
                """
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE}_decision "
                f"ON {self._TABLE}(decision_identifier, construction_identifier, sequence)"
            )

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        decision_identifier: str,
        construction_identifier: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                decision_identifier,
                construction_identifier,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, event: PaperDecisionApprovalEvent) -> int:
        if not isinstance(event, PaperDecisionApprovalEvent):
            raise TypeError("event must be PaperDecisionApprovalEvent")
        payload_json = _canonical_json(event.to_dict())
        occurred_at = event.occurred_at.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (event.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise PaperDecisionApprovalError(
                        "approval event identifier already exists with different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH if tail is None else str(tail["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=event.identifier,
                decision_identifier=event.decision_identifier,
                construction_identifier=event.construction_identifier,
                occurred_at=occurred_at,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, decision_identifier,
                    construction_identifier, occurred_at, payload_json,
                    previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event.identifier,
                    event.decision_identifier,
                    event.construction_identifier,
                    occurred_at,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def events(
        self,
        decision_identifier: str,
        construction_identifier: str,
    ) -> tuple[PaperDecisionApprovalEvent, ...]:
        decision = _text(decision_identifier, field_name="decision_identifier")
        construction = _text(
            construction_identifier,
            field_name="construction_identifier",
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE decision_identifier = ? AND construction_identifier = ? "
                "ORDER BY sequence",
                (decision, construction),
            ).fetchall()
        return tuple(
            PaperDecisionApprovalEvent.from_dict(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def latest(
        self,
        decision_identifier: str,
        construction_identifier: str,
    ) -> PaperDecisionApprovalEvent | None:
        values = self.events(decision_identifier, construction_identifier)
        return None if not values else values[-1]

    def approve(
        self,
        *,
        decision_identifier: str,
        construction_identifier: str,
        construction_sha256: str,
        actor_user_id: str,
        actor_session_id: str,
        occurred_at: datetime,
        rationale: str,
        ttl: timedelta = timedelta(hours=24),
    ) -> PaperDecisionApprovalEvent:
        timestamp = _aware(occurred_at, field_name="occurred_at")
        if ttl <= timedelta(0):
            raise ValueError("approval ttl must be positive")
        event = PaperDecisionApprovalEvent(
            identifier=(
                f"paper-approval:{decision_identifier}:{construction_identifier}:"
                f"{timestamp.isoformat()}:{actor_user_id}"
            ),
            decision_identifier=decision_identifier,
            construction_identifier=construction_identifier,
            construction_sha256=construction_sha256,
            state=PaperDecisionApprovalState.APPROVED,
            actor_user_id=actor_user_id,
            actor_session_id=actor_session_id,
            occurred_at=timestamp,
            expires_at=timestamp + ttl,
            rationale=rationale,
        )
        self.append(event)
        return event

    def conclude(
        self,
        *,
        state: PaperDecisionApprovalState,
        decision_identifier: str,
        construction_identifier: str,
        construction_sha256: str,
        actor_user_id: str,
        actor_session_id: str,
        occurred_at: datetime,
        rationale: str,
        execution_identifier: str | None = None,
    ) -> PaperDecisionApprovalEvent:
        if state is PaperDecisionApprovalState.APPROVED:
            raise ValueError("use approve() for an approval event")
        timestamp = _aware(occurred_at, field_name="occurred_at")
        event = PaperDecisionApprovalEvent(
            identifier=(
                f"paper-approval:{state.value}:{decision_identifier}:"
                f"{construction_identifier}:{timestamp.isoformat()}:{actor_user_id}"
            ),
            decision_identifier=decision_identifier,
            construction_identifier=construction_identifier,
            construction_sha256=construction_sha256,
            state=state,
            actor_user_id=actor_user_id,
            actor_session_id=actor_session_id,
            occurred_at=timestamp,
            expires_at=None,
            rationale=rationale,
            execution_identifier=execution_identifier,
        )
        self.append(event)
        return event

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise PaperDecisionApprovalIntegrityError(
                    "paper decision approval sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise PaperDecisionApprovalIntegrityError(
                    "paper decision approval previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                decision_identifier=str(row["decision_identifier"]),
                construction_identifier=str(row["construction_identifier"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise PaperDecisionApprovalIntegrityError(
                    "paper decision approval content hash is invalid"
                )
            previous_hash = expected_hash
        return True


def require_user_approved_paper_decision(
    *,
    store: SQLitePaperDecisionApprovalStore,
    decision_identifier: str,
    construction_identifier: str,
    construction_sha256: str,
    as_of: datetime,
) -> PaperDecisionApprovalEvent:
    """Require current exact user approval before paper execution."""

    store.verify_integrity()
    latest = store.latest(decision_identifier, construction_identifier)
    if latest is None:
        raise PaperDecisionApprovalError(
            "user approval for the exact paper implementation is unavailable"
        )
    if latest.construction_sha256 != construction_sha256.lower():
        raise PaperDecisionApprovalError(
            "user approval construction hash does not match execution"
        )
    if not latest.active_at(as_of):
        raise PaperDecisionApprovalError(
            f"latest user paper-decision state is {latest.state.value} or expired"
        )
    return latest


__all__ = [
    "PaperDecisionApprovalError",
    "PaperDecisionApprovalEvent",
    "PaperDecisionApprovalIntegrityError",
    "PaperDecisionApprovalState",
    "SQLitePaperDecisionApprovalStore",
    "canonical_construction_sha256",
    "require_user_approved_paper_decision",
]
