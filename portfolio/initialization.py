"""Governed single-writer initialization for the canonical paper portfolio.

Initialization has exactly three semantic states:

* ABSENT: no canonical store or prior initialization artifacts exist; bootstrap once.
* VALID: a canonical store exists and passes integrity/governance validation; recover it.
* INVALID: any prior store/artifact exists but cannot be validated; fail closed.

The SQLite append-only hash chain remains the sole portfolio state authority.  This
module only governs the transition into that authority and deliberately never
archives, deletes, resets, or recreates existing canonical history.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

try:  # Render and GitHub Actions are Linux; retain a safe import fallback.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX developer environments only
    fcntl = None  # type: ignore[assignment]

from portfolio.constants import (
    CANONICAL_BASE_CURRENCY,
    CANONICAL_CONSTRAINT_PROFILE,
    CANONICAL_PORTFOLIO_CODE,
    CANONICAL_PORTFOLIO_NAME,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import (
    CanonicalPortfolioCompatibilityError,
    CanonicalPortfolioIntegrityError,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
    canonical_initial_snapshot,
    snapshot_to_dict,
)

_SUPPORTED_SCHEMA_VERSIONS = frozenset({"canonical-portfolio-state.v2"})
_INITIALIZATION_THREAD_LOCK = threading.Lock()
_LOCK_SUFFIX = ".canonical-init.lock"


class CanonicalPortfolioInitializationError(CanonicalPortfolioIntegrityError):
    """Fail-closed initialization error with machine-readable provenance."""

    def __init__(self, *, failure_type: str, detail: str) -> None:
        self.initialization_state = "invalid"
        self.failure_type = str(failure_type).strip() or "persistence_error"
        self.failure_detail = str(detail).strip() or "canonical portfolio is invalid"
        super().__init__(
            f"canonical portfolio initialization failed closed "
            f"[{self.failure_type}]: {self.failure_detail}"
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "portfolio_initialization_state": self.initialization_state,
            "portfolio_failure_type": self.failure_type,
            "portfolio_failure_detail": self.failure_detail,
        }


@dataclass(frozen=True, slots=True)
class GovernedCanonicalPortfolioInitialization:
    """Observable result of a safe bootstrap or exact recovery."""

    path: Path
    created: bool
    state: str
    reason: str
    state_generation_id: str
    schema_version: str
    state_hash: str
    paper_only: bool = True
    real_money_authorized: bool = False
    reset: bool = False
    archive_path: Path | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "portfolio_initialization_state": self.state,
            "portfolio_failure_type": None,
            "portfolio_failure_detail": None,
            "portfolio_state_generation_id": self.state_generation_id,
            "portfolio_schema_version": self.schema_version,
            "portfolio_state_hash": self.state_hash,
            "paper_only": self.paper_only,
            "real_money_authorized": self.real_money_authorized,
        }


def _enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _require_paper_only_governance() -> None:
    paper_only = _enabled("CAPITAL_INTELLIGENCE_PAPER_ONLY", default=True)
    real_money_authorized = _enabled(
        "CAPITAL_INTELLIGENCE_REAL_MONEY_AUTHORIZED",
        default=False,
    )
    if not paper_only or real_money_authorized:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail=(
                "canonical portfolio requires paper_only=true and "
                "real_money_authorized=false"
            ),
        )


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + _LOCK_SUFFIX)


def _prior_artifacts(path: Path, *, lock_existed_before: bool) -> tuple[Path, ...]:
    artifacts: list[Path] = []
    if lock_existed_before:
        artifacts.append(_lock_path(path))
    for suffix in ("-wal", "-shm", "-journal"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            artifacts.append(candidate)
    return tuple(artifacts)


@contextmanager
def _initialization_lock(path: Path) -> Iterator[bool]:
    """Serialize first-boot classification before SQLite can create the DB file.

    The lock file intentionally persists as a genesis marker.  If the canonical
    database later disappears, that marker prevents its absence from being
    misclassified as a never-initialized deployment.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(path)
    with _INITIALIZATION_THREAD_LOCK:
        lock_existed_before = lock_path.exists()
        with lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield lock_existed_before
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _state_hash(snapshot: CanonicalPortfolioSnapshot) -> str:
    payload = json.dumps(
        snapshot_to_dict(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_snapshot(snapshot: CanonicalPortfolioSnapshot) -> None:
    if snapshot.portfolio_code != CANONICAL_PORTFOLIO_CODE:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail="persisted portfolio identity is not the sole canonical portfolio",
        )
    if snapshot.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise CanonicalPortfolioInitializationError(
            failure_type="schema_mismatch",
            detail=f"unsupported canonical portfolio schema {snapshot.schema_version!r}",
        )
    if abs(snapshot.starting_capital - INITIAL_PAPER_CAPITAL) > 0.00000001:
        raise CanonicalPortfolioInitializationError(
            failure_type="reconciliation_failure",
            detail="canonical starting-capital invariant is not $250,000.00",
        )
    if snapshot.base_currency != CANONICAL_BASE_CURRENCY:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail=f"canonical base currency must be {CANONICAL_BASE_CURRENCY}",
        )
    if snapshot.display_name != CANONICAL_PORTFOLIO_NAME:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail="canonical portfolio display identity does not match governance",
        )
    if snapshot.constraint_profile != CANONICAL_CONSTRAINT_PROFILE:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail="canonical portfolio constraint profile does not match governance",
        )
    if abs(snapshot.accounting_residual) > 0.000001:
        raise CanonicalPortfolioInitializationError(
            failure_type="reconciliation_failure",
            detail=(
                "canonical cash, positions, and implementation accounting do not "
                "reconcile"
            ),
        )


def _recover_valid_store(path: Path) -> CanonicalPortfolioSnapshot:
    try:
        store = SQLiteCanonicalPortfolioStore(path)
        store.verify_integrity()
        latest = store.latest(CANONICAL_PORTFOLIO_CODE)
    except CanonicalPortfolioInitializationError:
        raise
    except CanonicalPortfolioCompatibilityError as error:
        raise CanonicalPortfolioInitializationError(
            failure_type="invalid_governance_state",
            detail=str(error),
        ) from error
    except CanonicalPortfolioIntegrityError as error:
        raise CanonicalPortfolioInitializationError(
            failure_type="digest_mismatch",
            detail=str(error),
        ) from error
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise CanonicalPortfolioInitializationError(
            failure_type="persistence_error",
            detail=f"existing canonical portfolio store is unreadable: {error}",
        ) from error

    if latest is None:
        raise CanonicalPortfolioInitializationError(
            failure_type="missing_snapshot",
            detail=(
                "canonical database already exists but contains no canonical state; "
                "refusing to bootstrap over existing artifacts"
            ),
        )
    _validate_snapshot(latest)
    return latest


def ensure_canonical_portfolio_store(
    path: str | Path,
    *,
    as_of: datetime | None = None,
    archive_directory: str | Path | None = None,
) -> GovernedCanonicalPortfolioInitialization:
    """Bootstrap once, recover exactly, or fail closed.

    ``archive_directory`` remains in the call signature for compatibility with
    older callers but is deliberately unused: initialization is never permitted
    to archive/delete/reset canonical state.
    """

    del archive_directory
    _require_paper_only_governance()
    effective_as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    resolved_path = Path(path)

    with _initialization_lock(resolved_path) as lock_existed_before:
        database_exists = resolved_path.exists()
        prior_artifacts = _prior_artifacts(
            resolved_path,
            lock_existed_before=lock_existed_before,
        )

        if database_exists:
            latest = _recover_valid_store(resolved_path)
            return GovernedCanonicalPortfolioInitialization(
                path=resolved_path,
                created=False,
                state="recovered",
                reason="existing canonical portfolio recovered exactly as persisted",
                state_generation_id=latest.identifier,
                schema_version=latest.schema_version,
                state_hash=_state_hash(latest),
            )

        if prior_artifacts:
            raise CanonicalPortfolioInitializationError(
                failure_type="missing_snapshot",
                detail=(
                    "canonical database is missing but prior initialization or SQLite "
                    "artifacts exist; refusing to treat prior state as first boot"
                ),
            )

        # Genuine ABSENT state.  The cross-process lock is held before the first
        # SQLite open, so only one initializer can perform this genesis transition.
        try:
            store = SQLiteCanonicalPortfolioStore(resolved_path)
            initial = canonical_initial_snapshot(as_of=effective_as_of)
            store.append(initial)
            store.verify_integrity()
            latest = store.latest(CANONICAL_PORTFOLIO_CODE)
        except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as error:
            raise CanonicalPortfolioInitializationError(
                failure_type="persistence_error",
                detail=f"canonical genesis could not be committed atomically: {error}",
            ) from error

        if latest is None:
            raise CanonicalPortfolioInitializationError(
                failure_type="missing_snapshot",
                detail="canonical genesis committed without a recoverable snapshot",
            )
        _validate_snapshot(latest)
        return GovernedCanonicalPortfolioInitialization(
            path=resolved_path,
            created=True,
            state="bootstrapped",
            reason="one-time canonical paper portfolio genesis committed",
            state_generation_id=latest.identifier,
            schema_version=latest.schema_version,
            state_hash=_state_hash(latest),
        )


__all__ = [
    "CanonicalPortfolioInitializationError",
    "GovernedCanonicalPortfolioInitialization",
    "ensure_canonical_portfolio_store",
]
