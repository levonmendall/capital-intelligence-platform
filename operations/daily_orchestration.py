"""Durable fail-closed orchestration for the canonical daily investment process.

The orchestrator coordinates existing canonical services. It does not discover
securities, create evidence, issue recommendations, change portfolio state, or
silently repair missing authorities. Each stage must return identifiers for
already-persisted canonical outputs and a reconciliation result.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable


class CanonicalDailyStage(str, Enum):
    PROVIDER_CERTIFICATION = "provider_certification"
    SECURITY_MASTER_ACTIVATION = "security_master_activation"
    ELIGIBLE_UNIVERSE_PUBLICATION = "eligible_universe_publication"
    COMPLETE_UNIVERSE_SCREENING = "complete_universe_screening"
    PRODUCTION_CONTEXT_ASSEMBLY = "production_context_assembly"
    CANONICAL_CIO_CYCLE = "canonical_cio_cycle"
    PAPER_CONSTRUCTION_EXECUTION = "paper_construction_execution"
    THESIS_MONITORING = "thesis_monitoring"
    OUTCOME_EVALUATION = "outcome_evaluation"
    OPERATIONAL_EVIDENCE_REVIEW = "operational_evidence_review"
    CANONICAL_ALERT_DELIVERY = "canonical_alert_delivery"
    SLO_ASSESSMENT = "slo_assessment"


CANONICAL_DAILY_STAGE_ORDER = tuple(CanonicalDailyStage)


class DailyOperationStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StageStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class FailureClassification(str, Enum):
    TRANSIENT_PROVIDER = "transient_provider"
    DATA_QUALITY = "data_quality"
    DEPENDENCY = "dependency"
    INTEGRITY = "integrity"
    CONFIGURATION = "configuration"
    RECONCILIATION = "reconciliation"
    EXECUTION = "execution"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class DailyOperationEventType(str, Enum):
    OPERATION_CLAIMED = "operation_claimed"
    STAGE_STARTED = "stage_started"
    STAGE_HEARTBEAT = "stage_heartbeat"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_BLOCKED = "stage_blocked"
    OPERATION_COMPLETED = "operation_completed"
    OPERATION_FAILED = "operation_failed"


class DailyOperationError(RuntimeError):
    """Base error for the daily operating authority."""


class DailyOperationIntegrityError(DailyOperationError):
    """Raised when the append-only operating record is invalid."""


class StageExecutionError(DailyOperationError):
    """Typed stage failure used for retry and failure classification."""

    def __init__(
        self,
        detail: str,
        *,
        classification: FailureClassification = FailureClassification.EXECUTION,
        retryable: bool = False,
        output_identifiers: tuple[str, ...] = (),
    ) -> None:
        super().__init__(detail)
        self.classification = classification
        self.retryable = retryable
        self.output_identifiers = _texts(
            output_identifiers,
            field_name="output_identifiers",
        )


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("daily operation payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class StageRetryPolicy:
    maximum_attempts: int = 3
    initial_backoff_seconds: float = 1.0
    multiplier: float = 2.0
    maximum_backoff_seconds: float = 60.0

    def __post_init__(self) -> None:
        if isinstance(self.maximum_attempts, bool) or not isinstance(
            self.maximum_attempts, int
        ):
            raise TypeError("maximum_attempts must be an integer")
        if self.maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        for field_name in (
            "initial_backoff_seconds",
            "multiplier",
            "maximum_backoff_seconds",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            if float(value) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.multiplier < 1.0:
            raise ValueError("multiplier must be at least 1")

    def backoff_seconds(self, completed_attempt: int) -> float:
        value = self.initial_backoff_seconds * (
            self.multiplier ** max(0, completed_attempt - 1)
        )
        return min(value, self.maximum_backoff_seconds)


@dataclass(frozen=True, slots=True)
class CanonicalDailyOperationRequest:
    identifier: str
    idempotency_key: str
    operation_date: date
    scheduled_for: datetime
    decision_timestamp: datetime
    knowledge_cutoff: datetime
    started_at: datetime
    portfolio_code: str
    process_version: str
    code_version: str
    input_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "idempotency_key",
            "portfolio_code",
            "process_version",
            "code_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.operation_date, date):
            raise TypeError("operation_date must be a date")
        for field_name in (
            "scheduled_for",
            "decision_timestamp",
            "knowledge_cutoff",
            "started_at",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff > self.decision_timestamp:
            raise ValueError("knowledge_cutoff cannot follow decision_timestamp")
        if self.started_at < self.scheduled_for:
            raise ValueError("started_at cannot predate scheduled_for")
        object.__setattr__(
            self,
            "portfolio_code",
            self.portfolio_code.upper(),
        )
        object.__setattr__(
            self,
            "input_identifiers",
            _texts(
                self.input_identifiers,
                field_name="input_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class CanonicalDailyStageResult:
    output_identifiers: tuple[str, ...]
    completed_at: datetime
    point_in_time_cutoff: datetime
    reconciliation_status: ReconciliationStatus
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_identifiers",
            _texts(
                self.output_identifiers,
                field_name="output_identifiers",
                minimum=1,
            ),
        )
        _aware(self.completed_at, field_name="completed_at")
        _aware(self.point_in_time_cutoff, field_name="point_in_time_cutoff")
        if not isinstance(self.reconciliation_status, ReconciliationStatus):
            raise TypeError(
                "reconciliation_status must be a ReconciliationStatus"
            )
        object.__setattr__(self, "detail", _text(self.detail, field_name="detail"))


@dataclass(frozen=True, slots=True)
class CanonicalDailyStageRequest:
    operation: CanonicalDailyOperationRequest
    stage: CanonicalDailyStage
    attempt: int
    idempotency_key: str
    input_identifiers: tuple[str, ...]
    heartbeat: Callable[[str, tuple[str, ...]], None]

    def __post_init__(self) -> None:
        if not isinstance(self.operation, CanonicalDailyOperationRequest):
            raise TypeError("operation must be CanonicalDailyOperationRequest")
        if not isinstance(self.stage, CanonicalDailyStage):
            raise TypeError("stage must be CanonicalDailyStage")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int):
            raise TypeError("attempt must be an integer")
        if self.attempt < 1:
            raise ValueError("attempt must be positive")
        object.__setattr__(
            self,
            "idempotency_key",
            _text(self.idempotency_key, field_name="idempotency_key"),
        )
        object.__setattr__(
            self,
            "input_identifiers",
            _texts(
                self.input_identifiers,
                field_name="input_identifiers",
                minimum=1,
            ),
        )
        if not callable(self.heartbeat):
            raise TypeError("heartbeat must be callable")


@dataclass(frozen=True, slots=True)
class CanonicalDailyOperationResult:
    identifier: str
    idempotency_key: str
    status: DailyOperationStatus
    completed_stages: tuple[CanonicalDailyStage, ...]
    failed_stage: CanonicalDailyStage | None
    output_identifiers: tuple[str, ...]


@runtime_checkable
class CanonicalDailyStageRunner(Protocol):
    @property
    def name(self) -> str: ...

    def run(
        self,
        request: CanonicalDailyStageRequest,
    ) -> CanonicalDailyStageResult: ...


class CallableStageRunner:
    """Small adapter for repository services and deterministic tests."""

    def __init__(
        self,
        name: str,
        handler: Callable[[CanonicalDailyStageRequest], CanonicalDailyStageResult],
    ) -> None:
        self._name = _text(name, field_name="name")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handler = handler

    @property
    def name(self) -> str:
        return self._name

    def run(
        self,
        request: CanonicalDailyStageRequest,
    ) -> CanonicalDailyStageResult:
        return self._handler(request)


class CommandStageRunner:
    """Invoke an existing repository command and preserve its output identifiers."""

    def __init__(
        self,
        *,
        name: str,
        module: str,
        argv: tuple[str, ...],
        output_fields: tuple[str, ...],
        retryable_exit_codes: tuple[int, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._name = _text(name, field_name="name")
        self.module = _text(module, field_name="module")
        self.argv = _texts(argv, field_name="argv")
        self.output_fields = _texts(
            output_fields,
            field_name="output_fields",
            minimum=1,
        )
        if not isinstance(retryable_exit_codes, tuple) or not all(
            isinstance(item, int) and not isinstance(item, bool)
            for item in retryable_exit_codes
        ):
            raise TypeError("retryable_exit_codes must be a tuple of integers")
        self.retryable_exit_codes = retryable_exit_codes
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def name(self) -> str:
        return self._name

    @staticmethod
    def _field(payload: Mapping[str, Any], path: str) -> object:
        value: object = payload
        for part in path.split("."):
            if not isinstance(value, Mapping) or part not in value:
                raise StageExecutionError(
                    f"command output is missing configured identifier field {path!r}",
                    classification=FailureClassification.RECONCILIATION,
                )
            value = value[part]
        return value

    def _arguments(self, request: CanonicalDailyStageRequest) -> list[str]:
        replacements = {
            "{operation_identifier}": request.operation.identifier,
            "{operation_idempotency_key}": request.operation.idempotency_key,
            "{stage_idempotency_key}": request.idempotency_key,
            "{attempt}": str(request.attempt),
            "{scheduled_for}": request.operation.scheduled_for.isoformat(),
            "{decision_timestamp}": request.operation.decision_timestamp.isoformat(),
            "{knowledge_cutoff}": request.operation.knowledge_cutoff.isoformat(),
            "{portfolio_code}": request.operation.portfolio_code,
            "{process_version}": request.operation.process_version,
            "{code_version}": request.operation.code_version,
            "{input_identifiers_json}": json.dumps(request.input_identifiers),
        }
        resolved: list[str] = []
        for argument in self.argv:
            value = argument
            for token, replacement in replacements.items():
                value = value.replace(token, replacement)
            resolved.append(value)
        return resolved

    def run(
        self,
        request: CanonicalDailyStageRequest,
    ) -> CanonicalDailyStageResult:
        request.heartbeat("command invocation started", ())
        try:
            main = getattr(importlib.import_module(self.module), "main")
        except (ImportError, AttributeError) as error:
            raise StageExecutionError(
                f"cannot load command module {self.module!r}",
                classification=FailureClassification.CONFIGURATION,
            ) from error
        if not callable(main):
            raise StageExecutionError(
                f"command module {self.module!r} has no callable main",
                classification=FailureClassification.CONFIGURATION,
            )
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                return_code = main(self._arguments(request))
        except SystemExit as error:
            return_code = int(error.code or 0)
        except Exception as error:
            raise StageExecutionError(
                f"command {self.module!r} raised {type(error).__name__}: {error}",
                classification=FailureClassification.EXECUTION,
            ) from error
        code = int(return_code or 0)
        raw = output.getvalue().strip()
        if code != 0:
            raise StageExecutionError(
                f"command {self.module!r} exited {code}: {raw or 'no output'}",
                classification=(
                    FailureClassification.TRANSIENT_PROVIDER
                    if code in self.retryable_exit_codes
                    else FailureClassification.EXECUTION
                ),
                retryable=code in self.retryable_exit_codes,
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise StageExecutionError(
                f"command {self.module!r} did not return one JSON document",
                classification=FailureClassification.RECONCILIATION,
            ) from error
        if not isinstance(payload, Mapping):
            raise StageExecutionError(
                f"command {self.module!r} output must be a JSON object",
                classification=FailureClassification.RECONCILIATION,
            )
        identifiers = tuple(
            _text(self._field(payload, path), field_name=path)
            for path in self.output_fields
        )
        request.heartbeat("command output identifiers reconciled", identifiers)
        return CanonicalDailyStageResult(
            output_identifiers=identifiers,
            completed_at=self.clock(),
            point_in_time_cutoff=request.operation.knowledge_cutoff,
            reconciliation_status=ReconciliationStatus.RECONCILED,
            detail=f"{self.module} completed and returned configured identifiers",
        )


class SQLiteCanonicalDailyOperationsStore:
    """Append-only hash-chained authority for daily operation lifecycle evidence."""

    _EVENTS = "canonical_daily_operation_events"
    _CLAIMS = "canonical_daily_operation_claims"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._CLAIMS} (
                    operation_identifier TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    claimed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS {self._EVENTS} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    operation_identifier TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    stage TEXT,
                    attempt INTEGER,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS canonical_daily_operation_lookup
                ON {self._EVENTS} (operation_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._CLAIMS}_no_update
                BEFORE UPDATE ON {self._CLAIMS}
                BEGIN SELECT RAISE(ABORT, 'daily operation claims are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._CLAIMS}_no_delete
                BEFORE DELETE ON {self._CLAIMS}
                BEGIN SELECT RAISE(ABORT, 'daily operation claims are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._EVENTS}_no_update
                BEFORE UPDATE ON {self._EVENTS}
                BEGIN SELECT RAISE(ABORT, 'daily operation history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._EVENTS}_no_delete
                BEFORE DELETE ON {self._EVENTS}
                BEGIN SELECT RAISE(ABORT, 'daily operation history is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        operation_identifier: str,
        idempotency_key: str,
        stage: str,
        attempt: str,
        event_type: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                operation_identifier,
                idempotency_key,
                stage,
                attempt,
                event_type,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def claim(self, request: CanonicalDailyOperationRequest) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT operation_identifier FROM {self._CLAIMS} "
                "WHERE idempotency_key = ?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                if str(existing["operation_identifier"]) != request.identifier:
                    raise DailyOperationError(
                        "daily operation idempotency key is already claimed by "
                        "another operation identifier"
                    )
                return
            connection.execute(
                f"INSERT INTO {self._CLAIMS} "
                "(operation_identifier, idempotency_key, claimed_at) VALUES (?, ?, ?)",
                (
                    request.identifier,
                    request.idempotency_key,
                    request.started_at.isoformat(),
                ),
            )
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
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = _canonical_json(payload)
        stage_value = "" if stage is None else stage.value
        attempt_value = "" if attempt is None else str(attempt)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
                    raise DailyOperationError(
                        "daily operation event identifier already exists with "
                        "different content"
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
                occurred_at=timestamp,
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
                    timestamp,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def events(self, operation_identifier: str) -> tuple[dict[str, Any], ...]:
        normalized = _text(
            operation_identifier,
            field_name="operation_identifier",
        )
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._EVENTS} "
                "WHERE operation_identifier = ? ORDER BY sequence",
                (normalized,),
            ).fetchall()
        return tuple(
            {
                "sequence": int(row["sequence"]),
                "event_identifier": str(row["event_identifier"]),
                "stage": None if row["stage"] is None else str(row["stage"]),
                "attempt": None if row["attempt"] is None else int(row["attempt"]),
                "event_type": str(row["event_type"]),
                "occurred_at": str(row["occurred_at"]),
                "payload": json.loads(str(row["payload_json"])),
                "content_hash": str(row["content_hash"]),
            }
            for row in rows
        )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._EVENTS} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise DailyOperationIntegrityError(
                    "daily operation event sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise DailyOperationIntegrityError(
                    "daily operation previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                operation_identifier=str(row["operation_identifier"]),
                idempotency_key=str(row["idempotency_key"]),
                stage="" if row["stage"] is None else str(row["stage"]),
                attempt="" if row["attempt"] is None else str(row["attempt"]),
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise DailyOperationIntegrityError(
                    "daily operation content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class CanonicalDailyOperationsOrchestrator:
    """Execute the complete canonical process with durable dependency control."""

    def __init__(
        self,
        *,
        store: SQLiteCanonicalDailyOperationsStore,
        runners: Mapping[CanonicalDailyStage, CanonicalDailyStageRunner],
        retry_policies: Mapping[CanonicalDailyStage, StageRetryPolicy] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if not isinstance(store, SQLiteCanonicalDailyOperationsStore):
            raise TypeError("store must be SQLiteCanonicalDailyOperationsStore")
        expected = set(CANONICAL_DAILY_STAGE_ORDER)
        if set(runners) != expected:
            missing = sorted(stage.value for stage in expected - set(runners))
            extra = sorted(stage.value for stage in set(runners) - expected)
            raise ValueError(
                f"daily stage runners must be complete: missing={missing} extra={extra}"
            )
        for stage, runner in runners.items():
            if not isinstance(stage, CanonicalDailyStage):
                raise TypeError("runner keys must be CanonicalDailyStage")
            if not isinstance(runner, CanonicalDailyStageRunner):
                raise TypeError(f"runner for {stage.value} does not implement protocol")
            _text(runner.name, field_name=f"{stage.value}.runner.name")
        policies = {
            stage: StageRetryPolicy() for stage in CANONICAL_DAILY_STAGE_ORDER
        }
        if retry_policies is not None:
            for stage, policy in retry_policies.items():
                if not isinstance(stage, CanonicalDailyStage):
                    raise TypeError("retry policy keys must be CanonicalDailyStage")
                if not isinstance(policy, StageRetryPolicy):
                    raise TypeError("retry policies must contain StageRetryPolicy")
                policies[stage] = policy
        self.store = store
        self.runners = dict(runners)
        self.retry_policies = policies
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleeper = sleeper or time.sleep

    @staticmethod
    def _event(
        events: Sequence[Mapping[str, Any]],
        *,
        event_type: DailyOperationEventType,
        stage: CanonicalDailyStage | None = None,
    ) -> Mapping[str, Any] | None:
        matches = tuple(
            item
            for item in events
            if item["event_type"] == event_type.value
            and (stage is None or item["stage"] == stage.value)
        )
        return None if not matches else matches[-1]

    @staticmethod
    def _completed_stage(
        events: Sequence[Mapping[str, Any]],
        stage: CanonicalDailyStage,
    ) -> Mapping[str, Any] | None:
        return CanonicalDailyOperationsOrchestrator._event(
            events,
            event_type=DailyOperationEventType.STAGE_COMPLETED,
            stage=stage,
        )

    @staticmethod
    def _attempts(
        events: Sequence[Mapping[str, Any]],
        stage: CanonicalDailyStage,
    ) -> int:
        return sum(
            1
            for item in events
            if item["stage"] == stage.value
            and item["event_type"] == DailyOperationEventType.STAGE_STARTED.value
        )

    def _heartbeat(
        self,
        request: CanonicalDailyOperationRequest,
        stage: CanonicalDailyStage,
        attempt: int,
        detail: str,
        output_identifiers: tuple[str, ...],
    ) -> None:
        now = self.clock()
        identifiers = _texts(
            output_identifiers,
            field_name="heartbeat output_identifiers",
        )
        digest = hashlib.sha256(
            f"{detail}|{'|'.join(identifiers)}".encode("utf-8")
        ).hexdigest()[:16]
        self.store.append(
            request=request,
            event_identifier=(
                f"event:{request.identifier}:{stage.value}:{attempt}:heartbeat:{digest}"
            ),
            event_type=DailyOperationEventType.STAGE_HEARTBEAT,
            occurred_at=now,
            stage=stage,
            attempt=attempt,
            payload={
                "detail": _text(detail, field_name="heartbeat detail"),
                "output_identifiers": list(identifiers),
            },
        )

    def _result_from_events(
        self,
        request: CanonicalDailyOperationRequest,
        events: Sequence[Mapping[str, Any]],
    ) -> CanonicalDailyOperationResult:
        completed = tuple(
            stage
            for stage in CANONICAL_DAILY_STAGE_ORDER
            if self._completed_stage(events, stage) is not None
        )
        terminal_failure = self._event(
            events,
            event_type=DailyOperationEventType.OPERATION_FAILED,
        )
        terminal_success = self._event(
            events,
            event_type=DailyOperationEventType.OPERATION_COMPLETED,
        )
        if terminal_success is not None:
            status = DailyOperationStatus.COMPLETED
            failed_stage = None
            output_identifiers = tuple(
                terminal_success["payload"]["output_identifiers"]
            )
        elif terminal_failure is not None:
            status = DailyOperationStatus.FAILED
            raw_stage = terminal_failure["payload"].get("failed_stage")
            failed_stage = (
                None if raw_stage is None else CanonicalDailyStage(raw_stage)
            )
            output_identifiers = tuple(
                terminal_failure["payload"].get("output_identifiers", ())
            )
        else:
            status = DailyOperationStatus.RUNNING
            failed_stage = None
            output_identifiers = (
                request.input_identifiers
                if not completed
                else tuple(
                    self._completed_stage(events, completed[-1])["payload"][
                        "output_identifiers"
                    ]
                )
            )
        return CanonicalDailyOperationResult(
            identifier=request.identifier,
            idempotency_key=request.idempotency_key,
            status=status,
            completed_stages=completed,
            failed_stage=failed_stage,
            output_identifiers=output_identifiers,
        )

    def _block_downstream(
        self,
        request: CanonicalDailyOperationRequest,
        *,
        failed_stage: CanonicalDailyStage,
        output_identifiers: tuple[str, ...],
    ) -> None:
        failed_index = CANONICAL_DAILY_STAGE_ORDER.index(failed_stage)
        for stage in CANONICAL_DAILY_STAGE_ORDER[failed_index + 1 :]:
            self.store.append(
                request=request,
                event_identifier=f"event:{request.identifier}:{stage.value}:blocked",
                event_type=DailyOperationEventType.STAGE_BLOCKED,
                occurred_at=self.clock(),
                stage=stage,
                payload={
                    "status": StageStatus.BLOCKED.value,
                    "dependency": failed_stage.value,
                    "classification": FailureClassification.DEPENDENCY.value,
                    "input_identifiers": list(output_identifiers),
                    "detail": (
                        "upstream stage failed; downstream investment activity "
                        "is not authorized"
                    ),
                },
            )

    def run(
        self,
        request: CanonicalDailyOperationRequest,
    ) -> CanonicalDailyOperationResult:
        if not isinstance(request, CanonicalDailyOperationRequest):
            raise TypeError("request must be CanonicalDailyOperationRequest")
        self.store.verify_integrity()
        self.store.claim(request)
        events = self.store.events(request.identifier)
        existing_result = self._result_from_events(request, events)
        if existing_result.status is not DailyOperationStatus.RUNNING:
            return existing_result

        current_inputs = request.input_identifiers
        for index, stage in enumerate(CANONICAL_DAILY_STAGE_ORDER):
            events = self.store.events(request.identifier)
            completed = self._completed_stage(events, stage)
            if completed is not None:
                current_inputs = tuple(completed["payload"]["output_identifiers"])
                continue
            if index > 0:
                dependency = CANONICAL_DAILY_STAGE_ORDER[index - 1]
                dependency_event = self._completed_stage(events, dependency)
                if dependency_event is None:
                    raise DailyOperationIntegrityError(
                        f"stage {stage.value} cannot run without completed dependency "
                        f"{dependency.value}"
                    )
                current_inputs = tuple(
                    dependency_event["payload"]["output_identifiers"]
                )

            policy = self.retry_policies[stage]
            attempts = self._attempts(events, stage)
            if attempts >= policy.maximum_attempts:
                classification = FailureClassification.EXECUTION
                detail = "stage retry policy is exhausted"
                self._block_downstream(
                    request,
                    failed_stage=stage,
                    output_identifiers=current_inputs,
                )
                self.store.append(
                    request=request,
                    event_identifier=f"event:{request.identifier}:failed",
                    event_type=DailyOperationEventType.OPERATION_FAILED,
                    occurred_at=self.clock(),
                    payload={
                        "failed_stage": stage.value,
                        "classification": classification.value,
                        "detail": detail,
                        "output_identifiers": list(current_inputs),
                    },
                )
                return self._result_from_events(
                    request,
                    self.store.events(request.identifier),
                )

            stage_completed = False
            while attempts < policy.maximum_attempts:
                attempts += 1
                stage_key = f"{request.idempotency_key}:{stage.value}"
                started_at = self.clock()
                self.store.append(
                    request=request,
                    event_identifier=(
                        f"event:{request.identifier}:{stage.value}:{attempts}:started"
                    ),
                    event_type=DailyOperationEventType.STAGE_STARTED,
                    occurred_at=started_at,
                    stage=stage,
                    attempt=attempts,
                    payload={
                        "status": StageStatus.RUNNING.value,
                        "runner": self.runners[stage].name,
                        "stage_idempotency_key": stage_key,
                        "input_identifiers": list(current_inputs),
                        "point_in_time_cutoff": request.knowledge_cutoff.isoformat(),
                    },
                )
                heartbeat = lambda detail, identifiers=(): self._heartbeat(
                    request,
                    stage,
                    attempts,
                    detail,
                    identifiers,
                )
                heartbeat("stage attempt is active", current_inputs)
                stage_request = CanonicalDailyStageRequest(
                    operation=request,
                    stage=stage,
                    attempt=attempts,
                    idempotency_key=stage_key,
                    input_identifiers=current_inputs,
                    heartbeat=heartbeat,
                )
                try:
                    result = self.runners[stage].run(stage_request)
                    if not isinstance(result, CanonicalDailyStageResult):
                        raise StageExecutionError(
                            "stage runner returned an invalid result",
                            classification=FailureClassification.RECONCILIATION,
                        )
                    if result.point_in_time_cutoff != request.knowledge_cutoff:
                        raise StageExecutionError(
                            "stage cutoff does not match the daily operation cutoff",
                            classification=FailureClassification.DATA_QUALITY,
                        )
                    if result.completed_at < started_at:
                        raise StageExecutionError(
                            "stage completion timestamp predates its start",
                            classification=FailureClassification.INTEGRITY,
                        )
                    if result.reconciliation_status not in {
                        ReconciliationStatus.RECONCILED,
                        ReconciliationStatus.NOT_APPLICABLE,
                    }:
                        raise StageExecutionError(
                            "stage output did not reconcile",
                            classification=FailureClassification.RECONCILIATION,
                        )
                except StageExecutionError as error:
                    self.store.append(
                        request=request,
                        event_identifier=(
                            f"event:{request.identifier}:{stage.value}:"
                            f"{attempts}:failed"
                        ),
                        event_type=DailyOperationEventType.STAGE_FAILED,
                        occurred_at=self.clock(),
                        stage=stage,
                        attempt=attempts,
                        payload={
                            "status": StageStatus.FAILED.value,
                            "classification": error.classification.value,
                            "retryable": error.retryable,
                            "detail": str(error),
                            "input_identifiers": list(current_inputs),
                            "output_identifiers": list(error.output_identifiers),
                            "point_in_time_cutoff": (
                                request.knowledge_cutoff.isoformat()
                            ),
                        },
                    )
                    if error.retryable and attempts < policy.maximum_attempts:
                        self.sleeper(policy.backoff_seconds(attempts))
                        continue
                    self._block_downstream(
                        request,
                        failed_stage=stage,
                        output_identifiers=current_inputs,
                    )
                    self.store.append(
                        request=request,
                        event_identifier=f"event:{request.identifier}:failed",
                        event_type=DailyOperationEventType.OPERATION_FAILED,
                        occurred_at=self.clock(),
                        payload={
                            "failed_stage": stage.value,
                            "classification": error.classification.value,
                            "detail": str(error),
                            "output_identifiers": list(current_inputs),
                        },
                    )
                    return self._result_from_events(
                        request,
                        self.store.events(request.identifier),
                    )
                except Exception as error:
                    wrapped = StageExecutionError(
                        f"unexpected {type(error).__name__}: {error}",
                        classification=FailureClassification.UNKNOWN,
                    )
                    self.store.append(
                        request=request,
                        event_identifier=(
                            f"event:{request.identifier}:{stage.value}:"
                            f"{attempts}:failed"
                        ),
                        event_type=DailyOperationEventType.STAGE_FAILED,
                        occurred_at=self.clock(),
                        stage=stage,
                        attempt=attempts,
                        payload={
                            "status": StageStatus.FAILED.value,
                            "classification": wrapped.classification.value,
                            "retryable": False,
                            "detail": str(wrapped),
                            "input_identifiers": list(current_inputs),
                            "output_identifiers": [],
                            "point_in_time_cutoff": (
                                request.knowledge_cutoff.isoformat()
                            ),
                        },
                    )
                    self._block_downstream(
                        request,
                        failed_stage=stage,
                        output_identifiers=current_inputs,
                    )
                    self.store.append(
                        request=request,
                        event_identifier=f"event:{request.identifier}:failed",
                        event_type=DailyOperationEventType.OPERATION_FAILED,
                        occurred_at=self.clock(),
                        payload={
                            "failed_stage": stage.value,
                            "classification": wrapped.classification.value,
                            "detail": str(wrapped),
                            "output_identifiers": list(current_inputs),
                        },
                    )
                    return self._result_from_events(
                        request,
                        self.store.events(request.identifier),
                    )

                current_inputs = result.output_identifiers
                heartbeat("stage output is reconciled", current_inputs)
                self.store.append(
                    request=request,
                    event_identifier=(
                        f"event:{request.identifier}:{stage.value}:"
                        f"{attempts}:completed"
                    ),
                    event_type=DailyOperationEventType.STAGE_COMPLETED,
                    occurred_at=result.completed_at,
                    stage=stage,
                    attempt=attempts,
                    payload={
                        "status": StageStatus.COMPLETED.value,
                        "runner": self.runners[stage].name,
                        "stage_idempotency_key": stage_key,
                        "input_identifiers": list(stage_request.input_identifiers),
                        "output_identifiers": list(result.output_identifiers),
                        "point_in_time_cutoff": (
                            result.point_in_time_cutoff.isoformat()
                        ),
                        "reconciliation_status": (
                            result.reconciliation_status.value
                        ),
                        "detail": result.detail,
                        "started_at": started_at.isoformat(),
                        "completed_at": result.completed_at.isoformat(),
                    },
                )
                stage_completed = True
                break
            if not stage_completed:
                raise DailyOperationIntegrityError(
                    f"stage {stage.value} left the retry loop without a result"
                )

        self.store.append(
            request=request,
            event_identifier=f"event:{request.identifier}:completed",
            event_type=DailyOperationEventType.OPERATION_COMPLETED,
            occurred_at=self.clock(),
            payload={
                "status": DailyOperationStatus.COMPLETED.value,
                "completed_stages": [
                    stage.value for stage in CANONICAL_DAILY_STAGE_ORDER
                ],
                "output_identifiers": list(current_inputs),
                "knowledge_cutoff": request.knowledge_cutoff.isoformat(),
                "process_version": request.process_version,
                "code_version": request.code_version,
            },
        )
        self.store.verify_integrity()
        return self._result_from_events(
            request,
            self.store.events(request.identifier),
        )


def operation_result_to_dict(
    result: CanonicalDailyOperationResult,
) -> dict[str, object]:
    return {
        "identifier": result.identifier,
        "idempotency_key": result.idempotency_key,
        "status": result.status.value,
        "completed_stages": [stage.value for stage in result.completed_stages],
        "failed_stage": (
            None if result.failed_stage is None else result.failed_stage.value
        ),
        "output_identifiers": list(result.output_identifiers),
    }


__all__ = [
    "CANONICAL_DAILY_STAGE_ORDER",
    "CallableStageRunner",
    "CanonicalDailyOperationRequest",
    "CanonicalDailyOperationResult",
    "CanonicalDailyOperationsOrchestrator",
    "CanonicalDailyStage",
    "CanonicalDailyStageRequest",
    "CanonicalDailyStageResult",
    "CanonicalDailyStageRunner",
    "CommandStageRunner",
    "DailyOperationError",
    "DailyOperationEventType",
    "DailyOperationIntegrityError",
    "DailyOperationStatus",
    "FailureClassification",
    "ReconciliationStatus",
    "SQLiteCanonicalDailyOperationsStore",
    "StageExecutionError",
    "StageRetryPolicy",
    "StageStatus",
    "operation_result_to_dict",
]
