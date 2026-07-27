"""Governed incident, recovery, and reconciliation exercise authority.

Exercises run against isolated adapters and produce append-only evidence.  They
never mutate production state, authorize real-money execution, or waive an
operational or investment-governance requirement.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol


def _required_text(value: object, *, field_name: str) -> str:
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
    return value


def _positive_int(value: object, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return value


def _text_tuple(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_required_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("resilience payload must be finite JSON") from error


class ResilienceExerciseKind(str, Enum):
    PROVIDER_OUTAGE = "provider_outage"
    STALE_DATA = "stale_data"
    CONFLICTING_SOURCE = "conflicting_source"
    DATABASE_CORRUPTION = "database_corruption"
    MISSED_UNIVERSE_CYCLE = "missed_universe_cycle"
    FAILED_THESIS_REVIEW = "failed_thesis_review"
    DELAYED_EVALUATION = "delayed_evaluation"
    PARTIAL_PAPER_EXECUTION = "partial_paper_execution"
    BACKUP_RESTORE = "backup_restore"
    MODEL_ROLLBACK = "model_rollback"


class ResilienceExerciseStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ResilienceExerciseScenario:
    identifier: str
    kind: ResilienceExerciseKind
    description: str
    required: bool = True
    detection_deadline_seconds: int = 300
    recovery_deadline_seconds: int = 3600
    reconciliation_deadline_seconds: int = 3600
    expected_invariants: tuple[str, ...] = ()
    schema_version: str = "resilience-exercise-scenario.v1"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "description", "schema_version"):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.kind, ResilienceExerciseKind):
            raise TypeError("kind must be ResilienceExerciseKind")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")
        for field_name in (
            "detection_deadline_seconds",
            "recovery_deadline_seconds",
            "reconciliation_deadline_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _positive_int(getattr(self, field_name), field_name=field_name, minimum=1),
            )
        object.__setattr__(
            self,
            "expected_invariants",
            _text_tuple(self.expected_invariants, field_name="expected_invariants", minimum=1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "kind": self.kind.value,
            "description": self.description,
            "required": self.required,
            "detection_deadline_seconds": self.detection_deadline_seconds,
            "recovery_deadline_seconds": self.recovery_deadline_seconds,
            "reconciliation_deadline_seconds": self.reconciliation_deadline_seconds,
            "expected_invariants": list(self.expected_invariants),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ResilienceExerciseOutcome:
    identifier: str
    scenario_identifier: str
    kind: ResilienceExerciseKind
    status: ResilienceExerciseStatus
    started_at: datetime
    injected_at: datetime
    detected_at: datetime | None
    recovered_at: datetime | None
    reconciled_at: datetime | None
    isolated_environment: bool
    production_mutation_count: int
    before_fingerprint: str
    after_fingerprint: str | None
    verified_invariants: tuple[str, ...]
    detection_evidence_identifiers: tuple[str, ...] = ()
    recovery_evidence_identifiers: tuple[str, ...] = ()
    reconciliation_evidence_identifiers: tuple[str, ...] = ()
    error: str | None = None
    schema_version: str = "resilience-exercise-outcome.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "scenario_identifier",
            "before_fingerprint",
            "schema_version",
        ):
            object.__setattr__(self, field_name, _required_text(getattr(self, field_name), field_name=field_name))
        if not isinstance(self.kind, ResilienceExerciseKind):
            raise TypeError("kind must be ResilienceExerciseKind")
        if not isinstance(self.status, ResilienceExerciseStatus):
            raise TypeError("status must be ResilienceExerciseStatus")
        for field_name in ("started_at", "injected_at"):
            object.__setattr__(self, field_name, _aware(getattr(self, field_name), field_name=field_name))
        if self.injected_at < self.started_at:
            raise ValueError("injected_at cannot predate started_at")
        previous = self.injected_at
        for field_name in ("detected_at", "recovered_at", "reconciled_at"):
            value = getattr(self, field_name)
            if value is not None:
                value = _aware(value, field_name=field_name)
                if value < previous:
                    raise ValueError(f"{field_name} cannot predate the previous phase")
                previous = value
                object.__setattr__(self, field_name, value)
        if not isinstance(self.isolated_environment, bool):
            raise TypeError("isolated_environment must be a bool")
        object.__setattr__(
            self,
            "production_mutation_count",
            _positive_int(self.production_mutation_count, field_name="production_mutation_count"),
        )
        if self.after_fingerprint is not None:
            object.__setattr__(self, "after_fingerprint", _required_text(self.after_fingerprint, field_name="after_fingerprint"))
        for field_name in (
            "verified_invariants",
            "detection_evidence_identifiers",
            "recovery_evidence_identifiers",
            "reconciliation_evidence_identifiers",
        ):
            object.__setattr__(self, field_name, _text_tuple(getattr(self, field_name), field_name=field_name))
        if self.error is not None:
            object.__setattr__(self, "error", _required_text(self.error, field_name="error"))
        if self.status is ResilienceExerciseStatus.PASSED:
            if None in (self.detected_at, self.recovered_at, self.reconciled_at):
                raise ValueError("passed outcomes require every phase timestamp")
            if not self.isolated_environment:
                raise ValueError("passed outcomes must run in an isolated environment")
            if self.production_mutation_count != 0:
                raise ValueError("passed outcomes cannot mutate production")
            if self.after_fingerprint != self.before_fingerprint:
                raise ValueError("passed outcomes must reconcile the original fingerprint")
            if not self.detection_evidence_identifiers:
                raise ValueError("passed outcomes require detection evidence")
            if not self.recovery_evidence_identifiers:
                raise ValueError("passed outcomes require recovery evidence")
            if not self.reconciliation_evidence_identifiers:
                raise ValueError("passed outcomes require reconciliation evidence")
            if self.error is not None:
                raise ValueError("passed outcomes cannot contain an error")
        elif self.error is None:
            raise ValueError("failed or blocked outcomes require an error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "scenario_identifier": self.scenario_identifier,
            "kind": self.kind.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "injected_at": self.injected_at.isoformat(),
            "detected_at": None if self.detected_at is None else self.detected_at.isoformat(),
            "recovered_at": None if self.recovered_at is None else self.recovered_at.isoformat(),
            "reconciled_at": None if self.reconciled_at is None else self.reconciled_at.isoformat(),
            "isolated_environment": self.isolated_environment,
            "production_mutation_count": self.production_mutation_count,
            "before_fingerprint": self.before_fingerprint,
            "after_fingerprint": self.after_fingerprint,
            "verified_invariants": list(self.verified_invariants),
            "detection_evidence_identifiers": list(self.detection_evidence_identifiers),
            "recovery_evidence_identifiers": list(self.recovery_evidence_identifiers),
            "reconciliation_evidence_identifiers": list(self.reconciliation_evidence_identifiers),
            "error": self.error,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ResilienceExercisePolicy:
    version: str = "resilience-exercise-policy.v1"
    required_kinds: tuple[ResilienceExerciseKind, ...] = tuple(ResilienceExerciseKind)
    require_isolation: bool = True
    maximum_production_mutations: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _required_text(self.version, field_name="version"))
        if not isinstance(self.required_kinds, tuple) or not self.required_kinds:
            raise ValueError("required_kinds must be a non-empty tuple")
        if any(not isinstance(item, ResilienceExerciseKind) for item in self.required_kinds):
            raise TypeError("required_kinds must contain ResilienceExerciseKind values")
        if len(self.required_kinds) != len(set(self.required_kinds)):
            raise ValueError("required_kinds cannot contain duplicates")
        if not isinstance(self.require_isolation, bool):
            raise TypeError("require_isolation must be a bool")
        object.__setattr__(
            self,
            "maximum_production_mutations",
            _positive_int(self.maximum_production_mutations, field_name="maximum_production_mutations"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "required_kinds": [item.value for item in self.required_kinds],
            "require_isolation": self.require_isolation,
            "maximum_production_mutations": self.maximum_production_mutations,
        }


@dataclass(frozen=True, slots=True)
class ResilienceExerciseReport:
    identifier: str
    evaluated_at: datetime
    policy: ResilienceExercisePolicy
    scenario_count: int
    passed_count: int
    failed_count: int
    blocked_count: int
    missing_required_kinds: tuple[ResilienceExerciseKind, ...]
    blockers: tuple[str, ...]
    outcome_identifiers: tuple[str, ...]
    release_gate_passed: bool
    real_money_authorized: bool = False
    performance_claims_permitted: bool = False
    schema_version: str = "resilience-exercise-report.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _required_text(self.identifier, field_name="identifier"))
        object.__setattr__(self, "evaluated_at", _aware(self.evaluated_at, field_name="evaluated_at"))
        if not isinstance(self.policy, ResilienceExercisePolicy):
            raise TypeError("policy must be ResilienceExercisePolicy")
        for field_name in ("scenario_count", "passed_count", "failed_count", "blocked_count"):
            object.__setattr__(self, field_name, _positive_int(getattr(self, field_name), field_name=field_name))
        if self.passed_count + self.failed_count + self.blocked_count != self.scenario_count:
            raise ValueError("report counts must reconcile")
        if not isinstance(self.missing_required_kinds, tuple) or any(
            not isinstance(item, ResilienceExerciseKind) for item in self.missing_required_kinds
        ):
            raise TypeError("missing_required_kinds must contain ResilienceExerciseKind values")
        object.__setattr__(self, "blockers", _text_tuple(self.blockers, field_name="blockers"))
        object.__setattr__(self, "outcome_identifiers", _text_tuple(self.outcome_identifiers, field_name="outcome_identifiers"))
        if not isinstance(self.release_gate_passed, bool):
            raise TypeError("release_gate_passed must be a bool")
        if self.real_money_authorized:
            raise ValueError("resilience reports cannot authorize real-money execution")
        if self.performance_claims_permitted:
            raise ValueError("resilience reports cannot permit performance claims")
        object.__setattr__(self, "schema_version", _required_text(self.schema_version, field_name="schema_version"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "policy": self.policy.to_dict(),
            "scenario_count": self.scenario_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "blocked_count": self.blocked_count,
            "missing_required_kinds": [item.value for item in self.missing_required_kinds],
            "blockers": list(self.blockers),
            "outcome_identifiers": list(self.outcome_identifiers),
            "release_gate_passed": self.release_gate_passed,
            "real_money_authorized": self.real_money_authorized,
            "performance_claims_permitted": self.performance_claims_permitted,
            "schema_version": self.schema_version,
        }


class ResilienceExerciseProvider(Protocol):
    def execute(self, scenario: ResilienceExerciseScenario) -> ResilienceExerciseOutcome: ...


class ResilienceExerciseHarness:
    def __init__(self, policy: ResilienceExercisePolicy | None = None) -> None:
        self.policy = policy or ResilienceExercisePolicy()

    def run(
        self,
        scenarios: Iterable[ResilienceExerciseScenario],
        provider: ResilienceExerciseProvider,
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[tuple[ResilienceExerciseOutcome, ...], ResilienceExerciseReport]:
        timestamp = _aware(evaluated_at or datetime.now(timezone.utc), field_name="evaluated_at")
        suite = tuple(scenarios)
        if not suite:
            raise ValueError("at least one resilience scenario is required")
        if len({item.identifier for item in suite}) != len(suite):
            raise ValueError("scenario identifiers must be unique")
        outcomes: list[ResilienceExerciseOutcome] = []
        blockers: list[str] = []
        for scenario in suite:
            try:
                outcome = provider.execute(scenario)
            except Exception as error:
                now = timestamp
                outcome = ResilienceExerciseOutcome(
                    identifier=f"{scenario.identifier}:blocked",
                    scenario_identifier=scenario.identifier,
                    kind=scenario.kind,
                    status=ResilienceExerciseStatus.BLOCKED,
                    started_at=now,
                    injected_at=now,
                    detected_at=None,
                    recovered_at=None,
                    reconciled_at=None,
                    isolated_environment=True,
                    production_mutation_count=0,
                    before_fingerprint="unavailable",
                    after_fingerprint=None,
                    verified_invariants=(),
                    error=f"exercise provider failed: {error}",
                )
            if outcome.scenario_identifier != scenario.identifier or outcome.kind is not scenario.kind:
                raise ValueError("exercise outcome does not match its scenario")
            if outcome.started_at > timestamp:
                raise ValueError("exercise outcome cannot be future-known")
            if outcome.reconciled_at is not None and outcome.reconciled_at > timestamp:
                raise ValueError("exercise reconciliation cannot be future-known")
            if outcome.status is ResilienceExerciseStatus.PASSED:
                assert outcome.detected_at is not None
                assert outcome.recovered_at is not None
                assert outcome.reconciled_at is not None
                detection = (outcome.detected_at - outcome.injected_at).total_seconds()
                recovery = (outcome.recovered_at - outcome.detected_at).total_seconds()
                reconciliation = (outcome.reconciled_at - outcome.recovered_at).total_seconds()
                failures: list[str] = []
                if detection > scenario.detection_deadline_seconds:
                    failures.append("detection deadline exceeded")
                if recovery > scenario.recovery_deadline_seconds:
                    failures.append("recovery deadline exceeded")
                if reconciliation > scenario.reconciliation_deadline_seconds:
                    failures.append("reconciliation deadline exceeded")
                missing = sorted(set(scenario.expected_invariants) - set(outcome.verified_invariants))
                if missing:
                    failures.append(f"invariants not verified: {missing}")
                if self.policy.require_isolation and not outcome.isolated_environment:
                    failures.append("exercise was not isolated")
                if outcome.production_mutation_count > self.policy.maximum_production_mutations:
                    failures.append("production mutation limit exceeded")
                if failures:
                    outcome = ResilienceExerciseOutcome(
                        identifier=outcome.identifier,
                        scenario_identifier=outcome.scenario_identifier,
                        kind=outcome.kind,
                        status=ResilienceExerciseStatus.FAILED,
                        started_at=outcome.started_at,
                        injected_at=outcome.injected_at,
                        detected_at=outcome.detected_at,
                        recovered_at=outcome.recovered_at,
                        reconciled_at=outcome.reconciled_at,
                        isolated_environment=outcome.isolated_environment,
                        production_mutation_count=outcome.production_mutation_count,
                        before_fingerprint=outcome.before_fingerprint,
                        after_fingerprint=outcome.after_fingerprint,
                        verified_invariants=outcome.verified_invariants,
                        detection_evidence_identifiers=outcome.detection_evidence_identifiers,
                        recovery_evidence_identifiers=outcome.recovery_evidence_identifiers,
                        reconciliation_evidence_identifiers=outcome.reconciliation_evidence_identifiers,
                        error="; ".join(failures),
                    )
            if (
                outcome.status is not ResilienceExerciseStatus.PASSED
                and scenario.required
            ):
                blockers.append(f"{scenario.identifier}: {outcome.error}")
            outcomes.append(outcome)
        present_passed = {item.kind for item in outcomes if item.status is ResilienceExerciseStatus.PASSED}
        missing_kinds = tuple(kind for kind in self.policy.required_kinds if kind not in present_passed)
        blockers.extend(f"required scenario kind not passed: {kind.value}" for kind in missing_kinds)
        passed_count = sum(item.status is ResilienceExerciseStatus.PASSED for item in outcomes)
        failed_count = sum(item.status is ResilienceExerciseStatus.FAILED for item in outcomes)
        blocked_count = sum(item.status is ResilienceExerciseStatus.BLOCKED for item in outcomes)
        payload = {
            "evaluated_at": timestamp.isoformat(),
            "policy": self.policy.to_dict(),
            "outcomes": [item.to_dict() for item in outcomes],
        }
        identifier = f"resilience-report:{hashlib.sha256(_canonical_json(payload).encode()).hexdigest()}"
        report = ResilienceExerciseReport(
            identifier=identifier,
            evaluated_at=timestamp,
            policy=self.policy,
            scenario_count=len(outcomes),
            passed_count=passed_count,
            failed_count=failed_count,
            blocked_count=blocked_count,
            missing_required_kinds=missing_kinds,
            blockers=tuple(blockers),
            outcome_identifiers=tuple(item.identifier for item in outcomes),
            release_gate_passed=not blockers,
        )
        return tuple(outcomes), report


class ResilienceExerciseIntegrityError(RuntimeError):
    pass


class SQLiteResilienceExerciseStore:
    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        self.path = Path(path)
        if initialize:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS resilience_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    identifier TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    previous_sha256 TEXT,
                    event_sha256 TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS resilience_events_no_update
                BEFORE UPDATE ON resilience_events BEGIN SELECT RAISE(ABORT, 'resilience events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS resilience_events_no_delete
                BEFORE DELETE ON resilience_events BEGIN SELECT RAISE(ABORT, 'resilience events are append-only'); END;
                """
            )

    def _append(self, event_type: str, identifier: str, payload: Mapping[str, Any], recorded_at: datetime) -> None:
        canonical = _canonical_json(payload)
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload_sha256 FROM resilience_events WHERE identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if existing["payload_sha256"] == payload_hash:
                    return
                raise ResilienceExerciseIntegrityError("identifier already stores different content")
            previous = connection.execute(
                "SELECT event_sha256 FROM resilience_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = None if previous is None else previous["event_sha256"]
            event_hash = hashlib.sha256(
                f"{previous_hash or ''}|{event_type}|{identifier}|{payload_hash}|{recorded_at.isoformat()}".encode()
            ).hexdigest()
            connection.execute(
                "INSERT INTO resilience_events (event_type, identifier, payload, payload_sha256, previous_sha256, event_sha256, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_type, identifier, canonical, payload_hash, previous_hash, event_hash, recorded_at.isoformat()),
            )

    def append_outcome(self, outcome: ResilienceExerciseOutcome, *, recorded_at: datetime | None = None) -> None:
        self._append("outcome", outcome.identifier, outcome.to_dict(), _aware(recorded_at or datetime.now(timezone.utc), field_name="recorded_at"))

    def append_report(self, report: ResilienceExerciseReport, *, recorded_at: datetime | None = None) -> None:
        self._append("report", report.identifier, report.to_dict(), _aware(recorded_at or datetime.now(timezone.utc), field_name="recorded_at"))

    def verify_integrity(self) -> None:
        previous_hash: str | None = None
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM resilience_events ORDER BY sequence").fetchall()
        for row in rows:
            payload_hash = hashlib.sha256(row["payload"].encode()).hexdigest()
            if payload_hash != row["payload_sha256"]:
                raise ResilienceExerciseIntegrityError("resilience payload hash mismatch")
            if row["previous_sha256"] != previous_hash:
                raise ResilienceExerciseIntegrityError("resilience chain is not contiguous")
            expected = hashlib.sha256(
                f"{previous_hash or ''}|{row['event_type']}|{row['identifier']}|{payload_hash}|{row['recorded_at']}".encode()
            ).hexdigest()
            if expected != row["event_sha256"]:
                raise ResilienceExerciseIntegrityError("resilience event hash mismatch")
            previous_hash = row["event_sha256"]

    def event_count(self) -> int:
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM resilience_events").fetchone()[0])


def scenario_from_payload(payload: Mapping[str, Any]) -> ResilienceExerciseScenario:
    return ResilienceExerciseScenario(
        identifier=str(payload["identifier"]),
        kind=ResilienceExerciseKind(str(payload["kind"])),
        description=str(payload["description"]),
        required=bool(payload.get("required", True)),
        detection_deadline_seconds=int(payload.get("detection_deadline_seconds", 300)),
        recovery_deadline_seconds=int(payload.get("recovery_deadline_seconds", 3600)),
        reconciliation_deadline_seconds=int(payload.get("reconciliation_deadline_seconds", 3600)),
        expected_invariants=tuple(str(item) for item in payload.get("expected_invariants", ())),
        schema_version=str(payload.get("schema_version", "resilience-exercise-scenario.v1")),
    )


def policy_from_payload(payload: Mapping[str, Any]) -> ResilienceExercisePolicy:
    return ResilienceExercisePolicy(
        version=str(payload.get("version", "resilience-exercise-policy.v1")),
        required_kinds=tuple(ResilienceExerciseKind(str(item)) for item in payload.get("required_kinds", tuple(item.value for item in ResilienceExerciseKind))),
        require_isolation=bool(payload.get("require_isolation", True)),
        maximum_production_mutations=int(payload.get("maximum_production_mutations", 0)),
    )
