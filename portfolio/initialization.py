"""Governed single-writer initialization for the canonical paper portfolio.

Initialization deliberately distinguishes a database that has never existed from an
existing database that cannot be recovered. Only the former may receive the one-time
genesis snapshot. Existing state is recovered exactly or startup fails closed.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator
from contextlib import contextmanager

from portfolio.constants import (
    CANONICAL_BASE_CURRENCY,
    CANONICAL_CONSTRAINT_PROFILE,
    CANONICAL_PORTFOLIO_CODE,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import (
    CanonicalPortfolioCompatibilityError,
    CanonicalPortfolioIntegrityError,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
    canonical_initial_snapshot,
)

_SUPPORTED_SCHEMA_VERSION = "canonical-portfolio-state.v2"
_EVENT_TABLE = SQLiteCanonicalPortfolioStore._TABLE
_ACCOUNTING_TOLERANCE = 0.000001


class PortfolioInitializationState(str, Enum):
    """Terminal governed states exposed by portfolio initialization."""

    BOOTSTRAPPED = "bootstrapped"
    RECOVERED = "recovered"
    INVALID = "invalid"


class PortfolioInitializationFailure(str, Enum):
    """Credential-safe failure classifications for diagnostics."""

    OUTSIDE_PERSISTENCE_ROOT = "outside_persistence_root"
    MISSING_STATE_TABLE = "missing_state_table"
    MISSING_SNAPSHOT = "missing_snapshot"
    SCHEMA_MISMATCH = "schema_mismatch"
    DIGEST_MISMATCH = "digest_mismatch"
    RECONCILIATION_FAILURE = "reconciliation_failure"
    INVALID_GOVERNANCE_STATE = "invalid_governance_state"
    PERSISTENCE_ERROR = "persistence_error"


class PortfolioInitializationError(RuntimeError):
    """Fail-closed initialization error with bounded diagnostic metadata."""

    def __init__(
        self,
        failure_type: PortfolioInitializationFailure,
        detail: str,
    ) -> None:
        self.failure_type = failure_type
        self.detail = str(detail).strip()
        super().__init__(f"{failure_type.value}: {self.detail}")


@dataclass(frozen=True, slots=True)
class PortfolioInitializationResult:
    """Successful canonical portfolio initialization result."""

    store: SQLiteCanonicalPortfolioStore
    state: CanonicalPortfolioSnapshot
    initialization_state: PortfolioInitializationState
    state_generation_id: str
    schema_version: str
    state_hash: str


@dataclass(frozen=True, slots=True)
class _ExistingStateProbe:
    row_count: int
    latest_payload: dict[str, object]
    latest_content_hash: str


def _resolve_governed_path(path: str | Path, persistence_root: str | Path) -> Path:
    resolved_path = Path(path).expanduser().resolve(strict=False)
    resolved_root = Path(persistence_root).expanduser().resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.OUTSIDE_PERSISTENCE_ROOT,
            "canonical portfolio database is outside the governed persistence root",
        ) from error
    return resolved_path


@contextmanager
def _exclusive_initialization_lock(path: Path) -> Iterator[None]:
    """Serialize classification and genesis/recovery across local processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".initialize.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_existing_state(path: Path) -> _ExistingStateProbe:
    """Inspect an existing database without allowing SQLite to create or repair it."""

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        with connection:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_EVENT_TABLE,),
            ).fetchone()
            if table is None:
                raise PortfolioInitializationError(
                    PortfolioInitializationFailure.MISSING_STATE_TABLE,
                    "existing canonical portfolio database has no canonical event table",
                )
            row = connection.execute(
                f"SELECT sequence, payload_json, content_hash FROM {_EVENT_TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            count_row = connection.execute(
                f"SELECT COUNT(*) AS count FROM {_EVENT_TABLE}"
            ).fetchone()
    except PortfolioInitializationError:
        raise
    except sqlite3.DatabaseError as error:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.PERSISTENCE_ERROR,
            "existing canonical portfolio database cannot be read as valid SQLite state",
        ) from error
    finally:
        if "connection" in locals():
            connection.close()

    row_count = 0 if count_row is None else int(count_row["count"])
    if row is None or row_count < 1:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.MISSING_SNAPSHOT,
            "canonical database exists but contains no portfolio snapshot; bootstrap is forbidden",
        )
    try:
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.DIGEST_MISMATCH,
            "latest canonical portfolio payload is not valid JSON",
        ) from error
    if not isinstance(payload, dict):
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.DIGEST_MISMATCH,
            "latest canonical portfolio payload is not an object",
        )
    schema_version = str(payload.get("schema_version", ""))
    if schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.SCHEMA_MISMATCH,
            f"unsupported canonical portfolio schema {schema_version or '<missing>'}",
        )
    return _ExistingStateProbe(
        row_count=row_count,
        latest_payload=payload,
        latest_content_hash=str(row["content_hash"]),
    )


def _validate_snapshot(snapshot: CanonicalPortfolioSnapshot) -> None:
    if snapshot.portfolio_code != CANONICAL_PORTFOLIO_CODE:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.INVALID_GOVERNANCE_STATE,
            "canonical portfolio identity does not match the sole governed portfolio",
        )
    if abs(snapshot.starting_capital - INITIAL_PAPER_CAPITAL) > 0.00000001:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.INVALID_GOVERNANCE_STATE,
            "canonical starting-capital invariant is not $250,000.00",
        )
    if snapshot.base_currency != CANONICAL_BASE_CURRENCY:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.INVALID_GOVERNANCE_STATE,
            "canonical base currency is not USD",
        )
    if snapshot.constraint_profile != CANONICAL_CONSTRAINT_PROFILE:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.INVALID_GOVERNANCE_STATE,
            "canonical constraint profile does not preserve paper-only governance",
        )
    if snapshot.schema_version != _SUPPORTED_SCHEMA_VERSION:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.SCHEMA_MISMATCH,
            f"unsupported canonical portfolio schema {snapshot.schema_version}",
        )
    if abs(snapshot.accounting_residual) > _ACCOUNTING_TOLERANCE:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.RECONCILIATION_FAILURE,
            "canonical cash, positions, flows, and PnL do not reconcile",
        )


def _recover_existing(path: Path, probe: _ExistingStateProbe) -> PortfolioInitializationResult:
    store = SQLiteCanonicalPortfolioStore(path)
    try:
        store.verify_integrity()
    except CanonicalPortfolioIntegrityError as error:
        failure = (
            PortfolioInitializationFailure.INVALID_GOVERNANCE_STATE
            if isinstance(error, CanonicalPortfolioCompatibilityError)
            else PortfolioInitializationFailure.DIGEST_MISMATCH
        )
        raise PortfolioInitializationError(
            failure,
            "canonical portfolio append-only lineage or content digest is invalid",
        ) from error
    try:
        state = store.latest(CANONICAL_PORTFOLIO_CODE)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.DIGEST_MISMATCH,
            "canonical portfolio snapshot cannot be reconstructed from persisted content",
        ) from error
    if state is None:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.MISSING_SNAPSHOT,
            "canonical portfolio disappeared during initialization",
        )
    _validate_snapshot(state)
    return PortfolioInitializationResult(
        store=store,
        state=state,
        initialization_state=PortfolioInitializationState.RECOVERED,
        state_generation_id=state.identifier,
        schema_version=state.schema_version,
        state_hash=probe.latest_content_hash,
    )


def _bootstrap_absent(path: Path) -> PortfolioInitializationResult:
    """Create the one permitted genesis state while holding the writer lock."""

    store = SQLiteCanonicalPortfolioStore(path)
    state = canonical_initial_snapshot()
    store.append(state)
    try:
        store.verify_integrity()
    except CanonicalPortfolioIntegrityError as error:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.DIGEST_MISMATCH,
            "new canonical portfolio genesis failed integrity verification",
        ) from error
    persisted = store.latest(CANONICAL_PORTFOLIO_CODE)
    if persisted is None:
        raise PortfolioInitializationError(
            PortfolioInitializationFailure.PERSISTENCE_ERROR,
            "canonical genesis was not durably recoverable after publication",
        )
    _validate_snapshot(persisted)
    probe = _read_existing_state(path)
    return PortfolioInitializationResult(
        store=store,
        state=persisted,
        initialization_state=PortfolioInitializationState.BOOTSTRAPPED,
        state_generation_id=persisted.identifier,
        schema_version=persisted.schema_version,
        state_hash=probe.latest_content_hash,
    )


def initialize_canonical_portfolio(
    path: str | Path,
    *,
    persistence_root: str | Path | None = None,
) -> PortfolioInitializationResult:
    """Recover the canonical portfolio exactly or create genesis only if truly absent.

    The database's existence is the durable bootstrap boundary. An existing empty,
    malformed, incompatible, unsupported, or tampered database is INVALID; it is
    never archived, deleted, re-created, or interpreted as first boot.
    """

    supplied_path = Path(path).expanduser()
    root = supplied_path.parent if persistence_root is None else Path(persistence_root)
    resolved_path = _resolve_governed_path(supplied_path, root)
    with _exclusive_initialization_lock(resolved_path):
        if not resolved_path.exists():
            return _bootstrap_absent(resolved_path)
        probe = _read_existing_state(resolved_path)
        return _recover_existing(resolved_path, probe)


__all__ = [
    "PortfolioInitializationError",
    "PortfolioInitializationFailure",
    "PortfolioInitializationResult",
    "PortfolioInitializationState",
    "initialize_canonical_portfolio",
]
