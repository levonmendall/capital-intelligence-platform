"""Multi-worker ownership and fencing for canonical daily operations.

The append-only daily-operation event chain remains the audit authority.  This
module adds a separate mutable coordination plane with expiring operation leases,
stage locks, heartbeats, and monotonically increasing fencing tokens.  A worker
may publish an authoritative stage event only while it owns both the operation
and stage leases with the latest tokens.
"""

from __future__ import annotations

import contextvars
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from operations.daily_orchestration import (
    CanonicalDailyOperationRequest,
    CanonicalDailyOperationResult,
    CanonicalDailyOperationsOrchestrator,
    CanonicalDailyStage,
    CanonicalDailyStageRequest,
    CanonicalDailyStageResult,
    CanonicalDailyStageRunner,
    DailyOperationEventType,
    FailureClassification,
    SQLiteCanonicalDailyOperationsStore,
    StageExecutionError,
    StageRetryPolicy,
)


class DailyOperationLeaseError(RuntimeError):
    """Raised when a worker cannot acquire or retain canonical ownership."""


class DailyOperationLeaseLost(DailyOperationLeaseError):
    """Raised when a stale worker attempts to publish with an obsolete token."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _aware(value, field_name="timestamp").isoformat()


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("lease-governed payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class DailyOperationLeaseGrant:
    operation_identifier: str
    worker_identifier: str
    fencing_token: int
    acquired_at: datetime
    expires_at: datetime
    stage: CanonicalDailyStage | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_identifier",
            _text(
                self.operation_identifier,
                field_name="operation_identifier",
            ),
        )
        object.__setattr__(
            self,
            "worker_identifier",
            _text(self.worker_identifier, field_name="worker_identifier"),
        )
        if isinstance(self.fencing_token, bool) or not isinstance(
            self.fencing_token,
            int,
        ):
            raise TypeError("fencing_token must be an integer")
        if self.fencing_token < 1:
            raise ValueError("fencing_token must be positive")
        _aware(self.acquired_at, field_name="acquired_at")
        _aware(self.expires_at, field_name="expires_at")
        if self.expires_at <= self.acquired_at:
            raise ValueError("lease expiration must follow acquisition")
        if self.stage is not None and not isinstance(
            self.stage,
            CanonicalDailyStage,
        ):
            raise TypeError("stage must be CanonicalDailyStage")


@dataclass(frozen=True, slots=True)
class StageFencingContext:
    operation_identifier: str
    stage: CanonicalDailyStage
    worker_identifier: str
    operation_fencing_token: int
    stage_fencing_token: int
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_identifier",
            _text(
                self.operation_identifier,
                field_name="operation_identifier",
            ),
        )
        if not isinstance(self.stage, CanonicalDailyStage):
            raise TypeError("stage must be CanonicalDailyStage")
        object.__setattr__(
            self,
            "worker_identifier",
            _text(self.worker_identifier, field_name="worker_identifier"),
        )
        for field_name in (
            "operation_fencing_token",
            "stage_fencing_token",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        _aware(self.lease_expires_at, field_name="lease_expires_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_identifier": self.operation_identifier,
            "stage": self.stage.value,
            "worker_identifier": self.worker_identifier,
            "operation_fencing_token": self.operation_fencing_token,
            "stage_fencing_token": self.stage_fencing_token,
            "lease_expires_at": self.lease_expires_at.isoformat(),
        }


_CURRENT_FENCING_CONTEXT: contextvars.ContextVar[
    StageFencingContext | None
] = contextvars.ContextVar("capital_intelligence_stage_fencing", default=None)
_CURRENT_FENCING_STORE: contextvars.ContextVar[
    "LeasedSQLiteCanonicalDailyOperationsStore | None"
] = contextvars.ContextVar("capital_intelligence_stage_fencing_store", default=None)


def current_stage_fencing_context() -> StageFencingContext:
    context = _CURRENT_FENCING_CONTEXT.get()
    if context is None:
        raise DailyOperationLeaseLost(
            "stage command is not running inside a fenced daily-operation lease"
        )
    return context


def assert_current_stage_fence() -> StageFencingContext:
    context = current_stage_fencing_context()
    store = _CURRENT_FENCING_STORE.get()
    if store is None:
        raise DailyOperationLeaseLost("fencing store is unavailable")
    store.assert_fencing_context(context)
    return context


class LeasedSQLiteCanonicalDailyOperationsStore(
    SQLiteCanonicalDailyOperationsStore
):
    """Daily-operation store with atomic lease and event fencing."""

    _OPERATION_LEASES = "canonical_daily_operation_leases"
    _STAGE_LEASES = "canonical_daily_stage_leases"

    def __init__(
        self,
        path: str | Path,
        *,
        worker_identifier: str,
        lease_duration: timedelta = timedelta(minutes=2),
        clock=None,
    ) -> None:
        self.worker_identifier = _text(
            worker_identifier,
            field_name="worker_identifier",
        )
        if not isinstance(lease_duration, timedelta):
            raise TypeError("lease_duration must be a timedelta")
        if lease_duration.total_seconds() < 5:
            raise ValueError("lease_duration must be at least five seconds")
        self.lease_duration = lease_duration
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease_lock = threading.RLock()
        self._operation_grants: dict[str, DailyOperationLeaseGrant] = {}
        self._stage_grants: dict[
            tuple[str, CanonicalDailyStage],
            DailyOperationLeaseGrant,
        ] = {}
        super().__init__(path)
        self._initialize_leases()

    def _initialize_leases(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._OPERATION_LEASES} (
                    operation_identifier TEXT PRIMARY KEY,
                    worker_identifier TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {self._STAGE_LEASES} (
                    operation_identifier TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    worker_identifier TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    acquired_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    PRIMARY KEY (operation_identifier, stage)
                );
                CREATE INDEX IF NOT EXISTS canonical_daily_operation_lease_expiry
                ON {self._OPERATION_LEASES} (lease_expires_at);
                CREATE INDEX IF NOT EXISTS canonical_daily_stage_lease_expiry
                ON {self._STAGE_LEASES} (lease_expires_at);
                """
            )

    def _now(self) -> datetime:
        return _aware(self.clock(), field_name="clock result")

    def _expires(self, now: datetime) -> datetime:
        return now + self.lease_duration

    @staticmethod
    def _row_expiration(row: sqlite3.Row) -> datetime:
        return _aware(
            datetime.fromisoformat(str(row["lease_expires_at"])),
            field_name="lease_expires_at",
        )

    def _acquire_operation_tx(
        self,
        connection: sqlite3.Connection,
        *,
        operation_identifier: str,
        now: datetime,
    ) -> DailyOperationLeaseGrant:
        row = connection.execute(
            f"SELECT * FROM {self._OPERATION_LEASES} "
            "WHERE operation_identifier = ?",
            (operation_identifier,),
        ).fetchone()
        expires_at = self._expires(now)
        if row is None:
            token = 1
            acquired_at = now
            connection.execute(
                f"INSERT INTO {self._OPERATION_LEASES} ("
                "operation_identifier, worker_identifier, fencing_token, "
                "acquired_at, heartbeat_at, lease_expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_identifier,
                    self.worker_identifier,
                    token,
                    _utc_text(acquired_at),
                    _utc_text(now),
                    _utc_text(expires_at),
                ),
            )
        else:
            active = self._row_expiration(row) > now
            owner = str(row["worker_identifier"])
            if active and owner != self.worker_identifier:
                raise DailyOperationLeaseError(
                    "daily operation is owned by another active worker: "
                    f"owner={owner} expires_at={row['lease_expires_at']}"
                )
            token = int(row["fencing_token"])
            acquired_at = _aware(
                datetime.fromisoformat(str(row["acquired_at"])),
                field_name="acquired_at",
            )
            if not active or owner != self.worker_identifier:
                token += 1
                acquired_at = now
            connection.execute(
                f"UPDATE {self._OPERATION_LEASES} SET "
                "worker_identifier = ?, fencing_token = ?, acquired_at = ?, "
                "heartbeat_at = ?, lease_expires_at = ? "
                "WHERE operation_identifier = ?",
                (
                    self.worker_identifier,
                    token,
                    _utc_text(acquired_at),
                    _utc_text(now),
                    _utc_text(expires_at),
                    operation_identifier,
                ),
            )
        return DailyOperationLeaseGrant(
            operation_identifier=operation_identifier,
            worker_identifier=self.worker_identifier,
            fencing_token=token,
            acquired_at=acquired_at,
            expires_at=expires_at,
        )

    def acquire_operation(
        self,
        request: CanonicalDailyOperationRequest,
    ) -> DailyOperationLeaseGrant:
        if not isinstance(request, CanonicalDailyOperationRequest):
            raise TypeError("request must be CanonicalDailyOperationRequest")
        with self._lease_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            grant = self._acquire_operation_tx(
                connection,
                operation_identifier=request.identifier,
                now=self._now(),
            )
            self._operation_grants[request.identifier] = grant
            return grant

    def _assert_operation_tx(
        self,
        connection: sqlite3.Connection,
        *,
        operation_identifier: str,
        now: datetime,
        renew: bool,
    ) -> DailyOperationLeaseGrant:
        grant = self._operation_grants.get(operation_identifier)
        if grant is None:
            raise DailyOperationLeaseLost("worker has no operation lease grant")
        row = connection.execute(
            f"SELECT * FROM {self._OPERATION_LEASES} "
            "WHERE operation_identifier = ?",
            (operation_identifier,),
        ).fetchone()
        if row is None:
            raise DailyOperationLeaseLost("operation lease record is missing")
        if (
            str(row["worker_identifier"]) != grant.worker_identifier
            or int(row["fencing_token"]) != grant.fencing_token
        ):
            raise DailyOperationLeaseLost(
                "operation fencing token is stale; authoritative publication denied"
            )
        if self._row_expiration(row) <= now:
            raise DailyOperationLeaseLost(
                "operation lease expired; authoritative publication denied"
            )
        expires_at = self._row_expiration(row)
        if renew:
            expires_at = self._expires(now)
            connection.execute(
                f"UPDATE {self._OPERATION_LEASES} SET "
                "heartbeat_at = ?, lease_expires_at = ? "
                "WHERE operation_identifier = ? AND worker_identifier = ? "
                "AND fencing_token = ?",
                (
                    _utc_text(now),
                    _utc_text(expires_at),
                    operation_identifier,
                    grant.worker_identifier,
                    grant.fencing_token,
                ),
            )
            grant = DailyOperationLeaseGrant(
                operation_identifier=grant.operation_identifier,
                worker_identifier=grant.worker_identifier,
                fencing_token=grant.fencing_token,
                acquired_at=grant.acquired_at,
                expires_at=expires_at,
            )
            self._operation_grants[operation_identifier] = grant
        return grant

    def _acquire_stage_tx(
        self,
        connection: sqlite3.Connection,
        *,
        operation_identifier: str,
        stage: CanonicalDailyStage,
        now: datetime,
    ) -> DailyOperationLeaseGrant:
        row = connection.execute(
            f"SELECT * FROM {self._STAGE_LEASES} "
            "WHERE operation_identifier = ? AND stage = ?",
            (operation_identifier, stage.value),
        ).fetchone()
        expires_at = self._expires(now)
        if row is None:
            token = 1
            acquired_at = now
            connection.execute(
                f"INSERT INTO {self._STAGE_LEASES} ("
                "operation_identifier, stage, worker_identifier, fencing_token, "
                "acquired_at, heartbeat_at, lease_expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    operation_identifier,
                    stage.value,
                    self.worker_identifier,
                    token,
                    _utc_text(acquired_at),
                    _utc_text(now),
                    _utc_text(expires_at),
                ),
            )
        else:
            active = self._row_expiration(row) > now
            owner = str(row["worker_identifier"])
            if active and owner != self.worker_identifier:
                raise DailyOperationLeaseError(
                    f"stage {stage.value} is owned by another active worker: "
                    f"owner={owner} expires_at={row['lease_expires_at']}"
                )
            token = int(row["fencing_token"])
            acquired_at = _aware(
                datetime.fromisoformat(str(row["acquired_at"])),
                field_name="acquired_at",
            )
            if not active or owner != self.worker_identifier:
                token += 1
                acquired_at = now
            connection.execute(
                f"UPDATE {self._STAGE_LEASES} SET "
                "worker_identifier = ?, fencing_token = ?, acquired_at = ?, "
                "heartbeat_at = ?, lease_expires_at = ? "
                "WHERE operation_identifier = ? AND stage = ?",
                (
                    self.worker_identifier,
                    token,
                    _utc_text(acquired_at),
                    _utc_text(now),
                    _utc_text(expires_at),
                    operation_identifier,
                    stage.value,
                ),
            )
        grant = DailyOperationLeaseGrant(
            operation_identifier=operation_identifier,
            worker_identifier=self.worker_identifier,
            fencing_token=token,
            acquired_at=acquired_at,
            expires_at=expires_at,
            stage=stage,
        )
        self._stage_grants[(operation_identifier, stage)] = grant
        return grant

    def _assert_stage_tx(
        self,
        connection: sqlite3.Connection,
        *,
        operation_identifier: str,
        stage: CanonicalDailyStage,
        now: datetime,
        renew: bool,
    ) -> DailyOperationLeaseGrant:
        grant = self._stage_grants.get((operation_identifier, stage))
        if grant is None:
            raise DailyOperationLeaseLost(
                f"worker has no lease grant for stage {stage.value}"
            )
        row = connection.execute(
            f"SELECT * FROM {self._STAGE_LEASES} "
            "WHERE operation_identifier = ? AND stage = ?",
            (operation_identifier, stage.value),
        ).fetchone()
        if row is None:
            raise DailyOperationLeaseLost("stage lease record is missing")
        if (
            str(row["worker_identifier"]) != grant.worker_identifier
            or int(row["fencing_token"]) != grant.fencing_token
        ):
            raise DailyOperationLeaseLost(
                f"stage {stage.value} fencing token is stale"
            )
        if self._row_expiration(row) <= now:
            raise DailyOperationLeaseLost(f"stage {stage.value} lease expired")
        expires_at = self._row_expiration(row)
        if renew:
            expires_at = self._expires(now)
            connection.execute(
                f"UPDATE {self._STAGE_LEASES} SET "
                "heartbeat_at = ?, lease_expires_at = ? "
                "WHERE operation_identifier = ? AND stage = ? "
                "AND worker_identifier = ? AND fencing_token = ?",
                (
                    _utc_text(now),
                    _utc_text(expires_at),
                    operation_identifier,
                    stage.value,
                    grant.worker_identifier,
                    grant.fencing_token,
                ),
            )
            grant = DailyOperationLeaseGrant(
                operation_identifier=grant.operation_identifier,
                worker_identifier=grant.worker_identifier,
                fencing_token=grant.fencing_token,
                acquired_at=grant.acquired_at,
                expires_at=expires_at,
                stage=grant.stage,
            )
            self._stage_grants[(operation_identifier, stage)] = grant
        return grant

    def claim(self, request: CanonicalDailyOperationRequest) -> None:
        if not isinstance(request, CanonicalDailyOperationRequest):
            raise TypeError("request must be CanonicalDailyOperationRequest")
        with self._lease_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            grant = self._acquire_operation_tx(
                connection,
                operation_identifier=request.identifier,
                now=self._now(),
            )
            self._operation_grants[request.identifier] = grant
            existing = connection.execute(
                f"SELECT operation_identifier FROM {self._CLAIMS} "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["operation_identifier"]) != request.identifier:
                    raise DailyOperationLeaseError(
                        "daily operation idempotency key belongs to another operation"
                    )
            else:
                connection.execute(
                    f"INSERT INTO {self._CLAIMS} "
                    "(operation_identifier, idempotency_key, claimed_at) "
                    "VALUES (?, ?, ?)",
                    (
                        request.identifier,
                        request.idempotency_key,
                        request.started_at.isoformat(),
                    ),
                )
        if not any(
            item["event_type"] == DailyOperationEventType.OPERATION_CLAIMED.value
            for item in self.events(request.identifier)
        ):
            self.append(
                request=request,
                event_identifier=f"event:{request.identifier}:claimed",
                event_type=DailyOperationEventType.OPERATION_CLAIMED,
                occurred_at=request.started_at,
                payload={
                    "operation_date": request.operation_date.isoformat(),
                    "scheduled_for": request.scheduled_for.isoformat(),
                    "decision_timestamp": request.decision_timestamp.isoformat(),
                    "knowledge_cutoff": request.knowledge_cutoff.isoformat(),
                    "portfolio_code": request.portfolio_code,
                    "process_version": request.process_version,
                    "code_version": request.code_version,
                    "input_identifiers": list(request.input_identifiers),
                },
            )

    def append(
        self,
        *,
        request: CanonicalDailyOperationRequest,
        event_identifier: str,
        event_type: DailyOperationEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        stage: CanonicalDailyStage | None = None,
        attempt: int | None = None,
    ) -> int:
        identifier = _text(event_identifier, field_name="event_identifier")
        timestamp = _aware(occurred_at, field_name="occurred_at")
        if not isinstance(event_type, DailyOperationEventType):
            raise TypeError("event_type must be DailyOperationEventType")
        if stage is not None and not isinstance(stage, CanonicalDailyStage):
            raise TypeError("stage must be CanonicalDailyStage")
        with self._lease_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._now()
            operation_grant = self._assert_operation_tx(
                connection,
                operation_identifier=request.identifier,
                now=now,
                renew=True,
            )
            stage_grant: DailyOperationLeaseGrant | None = None
            if event_type is DailyOperationEventType.STAGE_STARTED:
                if stage is None:
                    raise DailyOperationLeaseError(
                        "stage-started event requires a stage"
                    )
                stage_grant = self._acquire_stage_tx(
                    connection,
                    operation_identifier=request.identifier,
                    stage=stage,
                    now=now,
                )
            elif stage is not None and event_type in {
                DailyOperationEventType.STAGE_HEARTBEAT,
                DailyOperationEventType.STAGE_COMPLETED,
                DailyOperationEventType.STAGE_FAILED,
            }:
                stage_grant = self._assert_stage_tx(
                    connection,
                    operation_identifier=request.identifier,
                    stage=stage,
                    now=now,
                    renew=(event_type is DailyOperationEventType.STAGE_HEARTBEAT),
                )

            governed_payload = dict(payload)
            lease_payload: dict[str, object] = {
                "worker_identifier": self.worker_identifier,
                "operation_fencing_token": operation_grant.fencing_token,
                "operation_lease_expires_at": operation_grant.expires_at.isoformat(),
            }
            if stage_grant is not None:
                lease_payload.update(
                    {
                        "stage_fencing_token": stage_grant.fencing_token,
                        "stage_lease_expires_at": stage_grant.expires_at.isoformat(),
                    }
                )
            existing_lease_payload = governed_payload.get("lease")
            if existing_lease_payload is not None and existing_lease_payload != lease_payload:
                raise DailyOperationLeaseError(
                    "event payload contains conflicting lease metadata"
                )
            governed_payload["lease"] = lease_payload
            payload_json = _canonical_json(governed_payload)
            stage_value = "" if stage is None else stage.value
            attempt_value = "" if attempt is None else str(attempt)

            existing = connection.execute(
                f"SELECT sequence, payload_json, event_type FROM {self._EVENTS} "
                "WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["payload_json"]) != payload_json
                    or str(existing["event_type"]) != event_type.value
                ):
                    raise DailyOperationLeaseError(
                        "daily operation event identifier has conflicting fenced content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._EVENTS} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH
                if tail is None
                else str(tail["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                operation_identifier=request.identifier,
                idempotency_key=request.idempotency_key,
                stage=stage_value,
                attempt=attempt_value,
                event_type=event_type.value,
                occurred_at=timestamp.isoformat(),
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._EVENTS} (
                    sequence, event_identifier, operation_identifier,
                    idempotency_key, stage, attempt, event_type, occurred_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    request.identifier,
                    request.idempotency_key,
                    None if stage is None else stage.value,
                    attempt,
                    event_type.value,
                    timestamp.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            if stage is not None and event_type in {
                DailyOperationEventType.STAGE_COMPLETED,
                DailyOperationEventType.STAGE_FAILED,
            }:
                connection.execute(
                    f"UPDATE {self._STAGE_LEASES} SET lease_expires_at = ?, "
                    "heartbeat_at = ? WHERE operation_identifier = ? AND stage = ? "
                    "AND worker_identifier = ? AND fencing_token = ?",
                    (
                        _utc_text(now),
                        _utc_text(now),
                        request.identifier,
                        stage.value,
                        self.worker_identifier,
                        stage_grant.fencing_token if stage_grant else -1,
                    ),
                )
                self._stage_grants.pop((request.identifier, stage), None)
            if event_type in {
                DailyOperationEventType.OPERATION_COMPLETED,
                DailyOperationEventType.OPERATION_FAILED,
            }:
                connection.execute(
                    f"UPDATE {self._OPERATION_LEASES} SET lease_expires_at = ?, "
                    "heartbeat_at = ? WHERE operation_identifier = ? "
                    "AND worker_identifier = ? AND fencing_token = ?",
                    (
                        _utc_text(now),
                        _utc_text(now),
                        request.identifier,
                        self.worker_identifier,
                        operation_grant.fencing_token,
                    ),
                )
                self._operation_grants.pop(request.identifier, None)
            return sequence

    def current_fencing_context(
        self,
        operation_identifier: str,
        stage: CanonicalDailyStage,
    ) -> StageFencingContext:
        operation = self._operation_grants.get(operation_identifier)
        stage_grant = self._stage_grants.get((operation_identifier, stage))
        if operation is None or stage_grant is None:
            raise DailyOperationLeaseLost("active operation and stage grants are required")
        return StageFencingContext(
            operation_identifier=operation_identifier,
            stage=stage,
            worker_identifier=self.worker_identifier,
            operation_fencing_token=operation.fencing_token,
            stage_fencing_token=stage_grant.fencing_token,
            lease_expires_at=min(operation.expires_at, stage_grant.expires_at),
        )

    def assert_fencing_context(self, context: StageFencingContext) -> None:
        if not isinstance(context, StageFencingContext):
            raise TypeError("context must be StageFencingContext")
        with self._lease_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = self._now()
            operation = self._assert_operation_tx(
                connection,
                operation_identifier=context.operation_identifier,
                now=now,
                renew=False,
            )
            stage = self._assert_stage_tx(
                connection,
                operation_identifier=context.operation_identifier,
                stage=context.stage,
                now=now,
                renew=False,
            )
            if (
                operation.fencing_token != context.operation_fencing_token
                or stage.fencing_token != context.stage_fencing_token
                or self.worker_identifier != context.worker_identifier
            ):
                raise DailyOperationLeaseLost("fencing context is obsolete")

    def release_all(self, operation_identifier: str) -> None:
        normalized = _text(
            operation_identifier,
            field_name="operation_identifier",
        )
        now = self._now()
        with self._lease_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            operation = self._operation_grants.get(normalized)
            if operation is not None:
                connection.execute(
                    f"UPDATE {self._OPERATION_LEASES} SET lease_expires_at = ?, "
                    "heartbeat_at = ? WHERE operation_identifier = ? "
                    "AND worker_identifier = ? AND fencing_token = ?",
                    (
                        _utc_text(now),
                        _utc_text(now),
                        normalized,
                        operation.worker_identifier,
                        operation.fencing_token,
                    ),
                )
            for (operation_id, stage), grant in tuple(self._stage_grants.items()):
                if operation_id != normalized:
                    continue
                connection.execute(
                    f"UPDATE {self._STAGE_LEASES} SET lease_expires_at = ?, "
                    "heartbeat_at = ? WHERE operation_identifier = ? AND stage = ? "
                    "AND worker_identifier = ? AND fencing_token = ?",
                    (
                        _utc_text(now),
                        _utc_text(now),
                        normalized,
                        stage.value,
                        grant.worker_identifier,
                        grant.fencing_token,
                    ),
                )
                self._stage_grants.pop((operation_id, stage), None)
            self._operation_grants.pop(normalized, None)

    def lease_status(self, operation_identifier: str) -> dict[str, object]:
        normalized = _text(
            operation_identifier,
            field_name="operation_identifier",
        )
        with self._connect() as connection:
            operation = connection.execute(
                f"SELECT * FROM {self._OPERATION_LEASES} "
                "WHERE operation_identifier = ?",
                (normalized,),
            ).fetchone()
            stages = connection.execute(
                f"SELECT * FROM {self._STAGE_LEASES} "
                "WHERE operation_identifier = ? ORDER BY stage",
                (normalized,),
            ).fetchall()
        return {
            "operation": None if operation is None else dict(operation),
            "stages": [dict(row) for row in stages],
        }


class FencedStageRunner:
    """Renew leases while a stage runs and deny stale completion publication."""

    def __init__(
        self,
        *,
        delegate: CanonicalDailyStageRunner,
        store: LeasedSQLiteCanonicalDailyOperationsStore,
        heartbeat_interval_seconds: float,
    ) -> None:
        if not isinstance(delegate, CanonicalDailyStageRunner):
            raise TypeError("delegate must implement CanonicalDailyStageRunner")
        if not isinstance(store, LeasedSQLiteCanonicalDailyOperationsStore):
            raise TypeError(
                "store must be LeasedSQLiteCanonicalDailyOperationsStore"
            )
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if heartbeat_interval_seconds >= store.lease_duration.total_seconds() / 2:
            raise ValueError(
                "heartbeat interval must be less than half the lease duration"
            )
        self.delegate = delegate
        self.store = store
        self.heartbeat_interval_seconds = float(heartbeat_interval_seconds)

    @property
    def name(self) -> str:
        return f"FENCED:{self.delegate.name}"

    def run(
        self,
        request: CanonicalDailyStageRequest,
    ) -> CanonicalDailyStageResult:
        context = self.store.current_fencing_context(
            request.operation.identifier,
            request.stage,
        )
        context_token = _CURRENT_FENCING_CONTEXT.set(context)
        store_token = _CURRENT_FENCING_STORE.set(self.store)
        stop = threading.Event()
        lease_failure: list[BaseException] = []

        def renew() -> None:
            while not stop.wait(self.heartbeat_interval_seconds):
                try:
                    request.heartbeat(
                        "worker and stage leases renewed",
                        request.input_identifiers,
                    )
                    self.store.assert_fencing_context(context)
                except BaseException as error:  # pragma: no cover - defensive thread boundary
                    lease_failure.append(error)
                    stop.set()
                    return

        thread = threading.Thread(
            target=renew,
            name=(
                f"daily-lease-heartbeat:{request.operation.identifier}:"
                f"{request.stage.value}"
            ),
            daemon=True,
        )
        thread.start()
        try:
            result = self.delegate.run(request)
            if lease_failure:
                raise StageExecutionError(
                    f"stage lease was lost: {lease_failure[-1]}",
                    classification=FailureClassification.INTERRUPTED,
                    retryable=True,
                )
            self.store.assert_fencing_context(context)
            return result
        finally:
            stop.set()
            thread.join(timeout=max(1.0, self.heartbeat_interval_seconds * 2))
            _CURRENT_FENCING_STORE.reset(store_token)
            _CURRENT_FENCING_CONTEXT.reset(context_token)


class LeasedCanonicalDailyOperationsOrchestrator:
    """Canonical orchestrator with operation ownership and fenced stage runners."""

    def __init__(
        self,
        *,
        store: LeasedSQLiteCanonicalDailyOperationsStore,
        runners: Mapping[CanonicalDailyStage, CanonicalDailyStageRunner],
        retry_policies: Mapping[CanonicalDailyStage, StageRetryPolicy] | None = None,
        heartbeat_interval_seconds: float = 15.0,
        clock=None,
        sleeper=None,
    ) -> None:
        if not isinstance(store, LeasedSQLiteCanonicalDailyOperationsStore):
            raise TypeError(
                "store must be LeasedSQLiteCanonicalDailyOperationsStore"
            )
        wrapped = {
            stage: FencedStageRunner(
                delegate=runner,
                store=store,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
            )
            for stage, runner in runners.items()
        }
        self.store = store
        self._delegate = CanonicalDailyOperationsOrchestrator(
            store=store,
            runners=wrapped,
            retry_policies=retry_policies,
            clock=clock,
            sleeper=sleeper,
        )

    def run(
        self,
        request: CanonicalDailyOperationRequest,
    ) -> CanonicalDailyOperationResult:
        try:
            return self._delegate.run(request)
        finally:
            self.store.release_all(request.identifier)


__all__ = [
    "DailyOperationLeaseError",
    "DailyOperationLeaseGrant",
    "DailyOperationLeaseLost",
    "FencedStageRunner",
    "LeasedCanonicalDailyOperationsOrchestrator",
    "LeasedSQLiteCanonicalDailyOperationsStore",
    "StageFencingContext",
    "assert_current_stage_fence",
    "current_stage_fencing_context",
]
