"""Immutable launch-readiness and failure-scenario evidence.

The authority records optional completed operating days and required isolated
failure exercises against one exact code/process/configuration baseline. It can
prove that a baseline has accumulated the required evidence, but it cannot
approve the baseline or authorize real money. Elapsed operating days are not a
prerequisite for controlled paper testing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class PaperTestCampaignError(RuntimeError):
    """Raised when campaign evidence violates the immutable baseline."""


class PaperTestCampaignIntegrityError(PaperTestCampaignError):
    """Raised when the append-only campaign chain is invalid."""


class PaperTestCampaignState(str, Enum):
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    SATISFIED = "satisfied"
    SUSPENDED = "suspended"


class FailureScenarioKind(str, Enum):
    PROVIDER_OUTAGE = "provider_outage"
    STALE_OR_FUTURE_DATA = "stale_or_future_data"
    INCOMPLETE_SCREENING = "incomplete_screening"
    WORKER_TERMINATION_AND_FENCED_TAKEOVER = (
        "worker_termination_and_fenced_takeover"
    )
    DATABASE_UNAVAILABLE_OR_LOCKED = "database_unavailable_or_locked"
    DATABASE_CORRUPTION_DETECTION = "database_corruption_detection"
    ENCRYPTED_BACKUP_RESTORE = "encrypted_backup_restore"
    EXECUTION_HOLD_AND_RETRY = "execution_hold_and_retry"
    DUPLICATE_ALERT_SUPPRESSION = "duplicate_alert_suppression"
    VALID_NO_ACTION_DAY = "valid_no_action_day"
    EVIDENCE_LINEAGE_RECONSTRUCTION = "evidence_lineage_reconstruction"


REQUIRED_FAILURE_SCENARIOS = tuple(FailureScenarioKind)


class FailureScenarioStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class CampaignEventType(str, Enum):
    BASELINE_RECORDED = "baseline_recorded"
    BURN_IN_DAY_RECORDED = "burn_in_day_recorded"
    FAILURE_SCENARIO_RECORDED = "failure_scenario_recorded"
    CAMPAIGN_REPORT_RECORDED = "campaign_report_recorded"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _non_negative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    result = _non_negative_int(value, field_name=field_name)
    if result < 1:
        raise ValueError(f"{field_name} must be positive")
    return result


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("campaign evidence must contain finite JSON") from error


@dataclass(frozen=True, slots=True)
class PaperTestCampaignBaseline:
    identifier: str
    created_at: datetime
    effective_date: date
    process_version: str
    code_version: str
    operation_plan_hash: str
    stage_bindings_hash: str
    configuration_hash: str
    data_manifest_identifier: str
    required_consecutive_days: int = 0
    required_failure_scenarios: tuple[FailureScenarioKind, ...] = (
        REQUIRED_FAILURE_SCENARIOS
    )
    development_open: bool = True
    schema_version: str = "paper-test-campaign-baseline.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "process_version",
            "code_version",
            "operation_plan_hash",
            "stage_bindings_hash",
            "configuration_hash",
            "data_manifest_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.created_at, field_name="created_at")
        if not isinstance(self.effective_date, date):
            raise TypeError("effective_date must be a date")
        if self.effective_date < self.created_at.date():
            raise ValueError("effective_date cannot predate baseline creation")
        object.__setattr__(
            self,
            "required_consecutive_days",
            _non_negative_int(
                self.required_consecutive_days,
                field_name="required_consecutive_days",
            ),
        )
        if not isinstance(self.required_failure_scenarios, tuple) or not all(
            isinstance(item, FailureScenarioKind)
            for item in self.required_failure_scenarios
        ):
            raise TypeError(
                "required_failure_scenarios must contain FailureScenarioKind values"
            )
        if len(self.required_failure_scenarios) != len(
            set(self.required_failure_scenarios)
        ):
            raise ValueError("required_failure_scenarios cannot contain duplicates")
        if set(self.required_failure_scenarios) != set(REQUIRED_FAILURE_SCENARIOS):
            raise ValueError(
                "controlled paper-test campaign must include every required failure scenario"
            )
        if self.development_open is not True:
            raise ValueError("development must remain open during launch-readiness testing")
        if self.schema_version != "paper-test-campaign-baseline.v1":
            raise ValueError("unsupported campaign baseline schema")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            _canonical_json(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "created_at": self.created_at.isoformat(),
            "effective_date": self.effective_date.isoformat(),
            "process_version": self.process_version,
            "code_version": self.code_version,
            "operation_plan_hash": self.operation_plan_hash,
            "stage_bindings_hash": self.stage_bindings_hash,
            "configuration_hash": self.configuration_hash,
            "data_manifest_identifier": self.data_manifest_identifier,
            "required_consecutive_days": self.required_consecutive_days,
            "required_failure_scenarios": [
                item.value for item in self.required_failure_scenarios
            ],
            "development_open": True,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperTestCampaignBaseline":
        if bool(value.get("real_money_authorized", False)):
            raise ValueError("campaign baseline cannot authorize real money")
        if bool(value.get("performance_claims_permitted", False)):
            raise ValueError("campaign baseline cannot permit performance claims")
        return cls(
            identifier=str(value["identifier"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            effective_date=date.fromisoformat(str(value["effective_date"])),
            process_version=str(value["process_version"]),
            code_version=str(value["code_version"]),
            operation_plan_hash=str(value["operation_plan_hash"]),
            stage_bindings_hash=str(value["stage_bindings_hash"]),
            configuration_hash=str(value["configuration_hash"]),
            data_manifest_identifier=str(value["data_manifest_identifier"]),
            required_consecutive_days=int(
                value.get("required_consecutive_days", 0)
            ),
            required_failure_scenarios=tuple(
                FailureScenarioKind(str(item))
                for item in value.get(
                    "required_failure_scenarios",
                    tuple(item.value for item in REQUIRED_FAILURE_SCENARIOS),
                )
            ),
            development_open=bool(value.get("development_open", True)),
            schema_version=str(
                value.get(
                    "schema_version",
                    "paper-test-campaign-baseline.v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class BurnInDayRecord:
    identifier: str
    baseline_identifier: str
    baseline_fingerprint: str
    operation_date: date
    recorded_at: datetime
    operation_identifier: str
    operation_status: str
    completed_stage_count: int
    stage_output_identifiers: tuple[str, ...]
    decision_identifier: str
    portfolio_snapshot_identifier: str
    readiness_snapshot_identifier: str
    backup_identifier: str
    reconciliation_passed: bool
    no_action_day: bool
    implementation_identifiers: tuple[str, ...]
    duplicate_alert_count: int
    unresolved_critical_incidents: int
    data_integrity_failures: int
    source_identifiers: tuple[str, ...]
    schema_version: str = "paper-test-burn-in-day.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "baseline_fingerprint",
            "operation_identifier",
            "operation_status",
            "decision_identifier",
            "portfolio_snapshot_identifier",
            "readiness_snapshot_identifier",
            "backup_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.operation_date, date):
            raise TypeError("operation_date must be a date")
        _aware(self.recorded_at, field_name="recorded_at")
        if self.operation_date > self.recorded_at.date():
            raise ValueError("future or synthetic operating days cannot be recorded")
        object.__setattr__(
            self,
            "completed_stage_count",
            _non_negative_int(
                self.completed_stage_count,
                field_name="completed_stage_count",
            ),
        )
        object.__setattr__(
            self,
            "stage_output_identifiers",
            _texts(
                self.stage_output_identifiers,
                field_name="stage_output_identifiers",
            ),
        )
        object.__setattr__(
            self,
            "implementation_identifiers",
            _texts(
                self.implementation_identifiers,
                field_name="implementation_identifiers",
            ),
        )
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(
                self.source_identifiers,
                field_name="source_identifiers",
                minimum=1,
            ),
        )
        for field_name in (
            "duplicate_alert_count",
            "unresolved_critical_incidents",
            "data_integrity_failures",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("reconciliation_passed", "no_action_day"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        if self.no_action_day and self.implementation_identifiers:
            raise ValueError("no-action day cannot contain implementation identifiers")
        if not self.no_action_day and not self.implementation_identifiers:
            raise ValueError(
                "an action day requires canonical implementation identifiers"
            )
        if self.schema_version != "paper-test-burn-in-day.v1":
            raise ValueError("unsupported burn-in day schema")

    @property
    def creditable(self) -> bool:
        return (
            self.operation_status == "completed"
            and self.completed_stage_count == 12
            and len(self.stage_output_identifiers) >= 12
            and self.reconciliation_passed
            and self.duplicate_alert_count == 0
            and self.unresolved_critical_incidents == 0
            and self.data_integrity_failures == 0
        )

    def require_baseline(self, baseline: PaperTestCampaignBaseline) -> None:
        if self.baseline_identifier != baseline.identifier:
            raise PaperTestCampaignError(
                "burn-in day belongs to another immutable baseline"
            )
        if self.baseline_fingerprint != baseline.fingerprint:
            raise PaperTestCampaignError(
                "burn-in day baseline fingerprint does not match"
            )
        if self.operation_date < baseline.effective_date:
            raise PaperTestCampaignError(
                "burn-in day predates the immutable baseline"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "baseline_identifier": self.baseline_identifier,
            "baseline_fingerprint": self.baseline_fingerprint,
            "operation_date": self.operation_date.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "operation_identifier": self.operation_identifier,
            "operation_status": self.operation_status,
            "completed_stage_count": self.completed_stage_count,
            "stage_output_identifiers": list(self.stage_output_identifiers),
            "decision_identifier": self.decision_identifier,
            "portfolio_snapshot_identifier": self.portfolio_snapshot_identifier,
            "readiness_snapshot_identifier": self.readiness_snapshot_identifier,
            "backup_identifier": self.backup_identifier,
            "reconciliation_passed": self.reconciliation_passed,
            "no_action_day": self.no_action_day,
            "implementation_identifiers": list(self.implementation_identifiers),
            "duplicate_alert_count": self.duplicate_alert_count,
            "unresolved_critical_incidents": self.unresolved_critical_incidents,
            "data_integrity_failures": self.data_integrity_failures,
            "source_identifiers": list(self.source_identifiers),
            "creditable": self.creditable,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BurnInDayRecord":
        return cls(
            identifier=str(value["identifier"]),
            baseline_identifier=str(value["baseline_identifier"]),
            baseline_fingerprint=str(value["baseline_fingerprint"]),
            operation_date=date.fromisoformat(str(value["operation_date"])),
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            operation_identifier=str(value["operation_identifier"]),
            operation_status=str(value["operation_status"]),
            completed_stage_count=int(value["completed_stage_count"]),
            stage_output_identifiers=tuple(
                str(item) for item in value["stage_output_identifiers"]
            ),
            decision_identifier=str(value["decision_identifier"]),
            portfolio_snapshot_identifier=str(
                value["portfolio_snapshot_identifier"]
            ),
            readiness_snapshot_identifier=str(
                value["readiness_snapshot_identifier"]
            ),
            backup_identifier=str(value["backup_identifier"]),
            reconciliation_passed=bool(value["reconciliation_passed"]),
            no_action_day=bool(value["no_action_day"]),
            implementation_identifiers=tuple(
                str(item) for item in value.get("implementation_identifiers", ())
            ),
            duplicate_alert_count=int(value["duplicate_alert_count"]),
            unresolved_critical_incidents=int(
                value["unresolved_critical_incidents"]
            ),
            data_integrity_failures=int(value["data_integrity_failures"]),
            source_identifiers=tuple(
                str(item) for item in value["source_identifiers"]
            ),
            schema_version=str(
                value.get("schema_version", "paper-test-burn-in-day.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class FailureScenarioRecord:
    identifier: str
    baseline_identifier: str
    baseline_fingerprint: str
    kind: FailureScenarioKind
    status: FailureScenarioStatus
    recorded_at: datetime
    isolated_environment: bool
    production_mutation_count: int
    expected_behavior: str
    actual_behavior: str
    detection_seconds: int
    recovery_seconds: int
    data_loss_seconds: int
    evidence_identifiers: tuple[str, ...]
    error: str | None = None
    schema_version: str = "paper-test-failure-scenario.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "baseline_fingerprint",
            "expected_behavior",
            "actual_behavior",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.kind, FailureScenarioKind):
            raise TypeError("kind must be FailureScenarioKind")
        if not isinstance(self.status, FailureScenarioStatus):
            raise TypeError("status must be FailureScenarioStatus")
        _aware(self.recorded_at, field_name="recorded_at")
        if not isinstance(self.isolated_environment, bool):
            raise TypeError("isolated_environment must be a bool")
        for field_name in (
            "production_mutation_count",
            "detection_seconds",
            "recovery_seconds",
            "data_loss_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        if self.error is not None:
            object.__setattr__(self, "error", _text(self.error, field_name="error"))
        if self.status is FailureScenarioStatus.PASSED:
            if not self.isolated_environment:
                raise ValueError("passed scenario must run in isolation")
            if self.production_mutation_count != 0:
                raise ValueError("passed scenario cannot mutate production")
            if self.error is not None:
                raise ValueError("passed scenario cannot contain an error")
        elif self.error is None:
            raise ValueError("failed or blocked scenario requires an error")
        if self.schema_version != "paper-test-failure-scenario.v1":
            raise ValueError("unsupported failure scenario schema")

    @property
    def passed(self) -> bool:
        return self.status is FailureScenarioStatus.PASSED

    def require_baseline(self, baseline: PaperTestCampaignBaseline) -> None:
        if self.baseline_identifier != baseline.identifier:
            raise PaperTestCampaignError(
                "failure scenario belongs to another immutable baseline"
            )
        if self.baseline_fingerprint != baseline.fingerprint:
            raise PaperTestCampaignError(
                "failure scenario baseline fingerprint does not match"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "baseline_identifier": self.baseline_identifier,
            "baseline_fingerprint": self.baseline_fingerprint,
            "kind": self.kind.value,
            "status": self.status.value,
            "recorded_at": self.recorded_at.isoformat(),
            "isolated_environment": self.isolated_environment,
            "production_mutation_count": self.production_mutation_count,
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "detection_seconds": self.detection_seconds,
            "recovery_seconds": self.recovery_seconds,
            "data_loss_seconds": self.data_loss_seconds,
            "evidence_identifiers": list(self.evidence_identifiers),
            "error": self.error,
            "passed": self.passed,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FailureScenarioRecord":
        return cls(
            identifier=str(value["identifier"]),
            baseline_identifier=str(value["baseline_identifier"]),
            baseline_fingerprint=str(value["baseline_fingerprint"]),
            kind=FailureScenarioKind(str(value["kind"])),
            status=FailureScenarioStatus(str(value["status"])),
            recorded_at=datetime.fromisoformat(str(value["recorded_at"])),
            isolated_environment=bool(value["isolated_environment"]),
            production_mutation_count=int(value["production_mutation_count"]),
            expected_behavior=str(value["expected_behavior"]),
            actual_behavior=str(value["actual_behavior"]),
            detection_seconds=int(value["detection_seconds"]),
            recovery_seconds=int(value["recovery_seconds"]),
            data_loss_seconds=int(value["data_loss_seconds"]),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            error=None if value.get("error") is None else str(value["error"]),
            schema_version=str(
                value.get(
                    "schema_version",
                    "paper-test-failure-scenario.v1",
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class PaperTestCampaignReport:
    identifier: str
    baseline_identifier: str
    baseline_fingerprint: str
    evaluated_at: datetime
    state: PaperTestCampaignState
    credited_dates: tuple[date, ...]
    consecutive_day_count: int
    required_consecutive_days: int
    passed_scenarios: tuple[FailureScenarioKind, ...]
    missing_scenarios: tuple[FailureScenarioKind, ...]
    failed_scenarios: tuple[FailureScenarioKind, ...]
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "paper-test-campaign-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "baseline_fingerprint",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.state, PaperTestCampaignState):
            raise TypeError("state must be PaperTestCampaignState")
        if not isinstance(self.credited_dates, tuple) or not all(
            isinstance(item, date) for item in self.credited_dates
        ):
            raise TypeError("credited_dates must contain dates")
        if tuple(sorted(self.credited_dates)) != self.credited_dates:
            raise ValueError("credited_dates must be sorted")
        if len(self.credited_dates) != len(set(self.credited_dates)):
            raise ValueError("credited_dates cannot contain duplicates")
        for field_name in ("consecutive_day_count", "required_consecutive_days"):
            object.__setattr__(
                self,
                field_name,
                _non_negative_int(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "passed_scenarios",
            "missing_scenarios",
            "failed_scenarios",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, tuple) or not all(
                isinstance(item, FailureScenarioKind) for item in value
            ):
                raise TypeError(f"{field_name} must contain FailureScenarioKind")
        object.__setattr__(
            self,
            "blockers",
            _texts(self.blockers, field_name="blockers"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        if self.state is PaperTestCampaignState.SATISFIED:
            if self.blockers or self.missing_scenarios or self.failed_scenarios:
                raise ValueError("satisfied campaign cannot contain blockers")
            if self.consecutive_day_count < self.required_consecutive_days:
                raise ValueError("satisfied campaign lacks required operating-day evidence")
        if self.schema_version != "paper-test-campaign-report.v1":
            raise ValueError("unsupported campaign report schema")

    @property
    def paper_test_authorized(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "baseline_identifier": self.baseline_identifier,
            "baseline_fingerprint": self.baseline_fingerprint,
            "evaluated_at": self.evaluated_at.isoformat(),
            "state": self.state.value,
            "credited_dates": [item.isoformat() for item in self.credited_dates],
            "consecutive_day_count": self.consecutive_day_count,
            "required_consecutive_days": self.required_consecutive_days,
            "passed_scenarios": [item.value for item in self.passed_scenarios],
            "missing_scenarios": [item.value for item in self.missing_scenarios],
            "failed_scenarios": [item.value for item in self.failed_scenarios],
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "campaign_requirements_satisfied": (
                self.state is PaperTestCampaignState.SATISFIED
            ),
            "paper_test_authorized": False,
            "real_money_authorized": False,
            "performance_claims_permitted": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PaperTestCampaignReport":
        for prohibited in (
            "paper_test_authorized",
            "real_money_authorized",
            "performance_claims_permitted",
        ):
            if bool(value.get(prohibited, False)):
                raise ValueError(f"campaign report cannot set {prohibited}")
        return cls(
            identifier=str(value["identifier"]),
            baseline_identifier=str(value["baseline_identifier"]),
            baseline_fingerprint=str(value["baseline_fingerprint"]),
            evaluated_at=datetime.fromisoformat(str(value["evaluated_at"])),
            state=PaperTestCampaignState(str(value["state"])),
            credited_dates=tuple(
                date.fromisoformat(str(item)) for item in value["credited_dates"]
            ),
            consecutive_day_count=int(value["consecutive_day_count"]),
            required_consecutive_days=int(value["required_consecutive_days"]),
            passed_scenarios=tuple(
                FailureScenarioKind(str(item))
                for item in value.get("passed_scenarios", ())
            ),
            missing_scenarios=tuple(
                FailureScenarioKind(str(item))
                for item in value.get("missing_scenarios", ())
            ),
            failed_scenarios=tuple(
                FailureScenarioKind(str(item))
                for item in value.get("failed_scenarios", ())
            ),
            blockers=tuple(str(item) for item in value.get("blockers", ())),
            evidence_identifiers=tuple(
                str(item) for item in value["evidence_identifiers"]
            ),
            schema_version=str(
                value.get("schema_version", "paper-test-campaign-report.v1")
            ),
        )


class SQLitePaperTestCampaignStore:
    """Append-only SHA-256 authority for baselines, days, scenarios, and reports."""

    _TABLE = "paper_test_campaign_events"
    _GENESIS = "0" * 64

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
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    baseline_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS paper_test_campaign_lookup
                ON {self._TABLE} (baseline_identifier, event_type, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper-test campaign is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'paper-test campaign is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        baseline_identifier: str,
        event_type: str,
        event_key: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    event_identifier,
                    baseline_identifier,
                    event_type,
                    event_key,
                    occurred_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def _append(
        self,
        *,
        event_identifier: str,
        baseline_identifier: str,
        event_type: CampaignEventType,
        event_key: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
        unique_key: bool,
    ) -> int:
        identifier = _text(event_identifier, field_name="event_identifier")
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        key = _text(event_key, field_name="event_key")
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = _canonical_json(payload)
        self.verify_integrity()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,event_type,event_key,payload_json FROM {self._TABLE} "
                "WHERE event_identifier=?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["event_type"]) != event_type.value
                    or str(existing["event_key"]) != key
                    or str(existing["payload_json"]) != payload_json
                ):
                    raise PaperTestCampaignError(
                        "campaign event identifier already has different content"
                    )
                return int(existing["sequence"])
            if unique_key:
                duplicate = connection.execute(
                    f"SELECT event_identifier FROM {self._TABLE} "
                    "WHERE baseline_identifier=? AND event_type=? AND event_key=?",
                    (baseline, event_type.value, key),
                ).fetchone()
                if duplicate is not None:
                    raise PaperTestCampaignError(
                        "campaign already contains evidence for this baseline key"
                    )
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                baseline_identifier=baseline,
                event_type=event_type.value,
                event_key=key,
                occurred_at=timestamp,
                payload_json=payload_json,
                previous_hash=previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    sequence,
                    identifier,
                    baseline,
                    event_type.value,
                    key,
                    timestamp,
                    payload_json,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def append_baseline(self, value: PaperTestCampaignBaseline) -> int:
        if not isinstance(value, PaperTestCampaignBaseline):
            raise TypeError("value must be PaperTestCampaignBaseline")
        return self._append(
            event_identifier=value.identifier,
            baseline_identifier=value.identifier,
            event_type=CampaignEventType.BASELINE_RECORDED,
            event_key=value.identifier,
            occurred_at=value.created_at,
            payload=value.to_dict(),
            unique_key=True,
        )

    def append_day(self, value: BurnInDayRecord) -> int:
        if not isinstance(value, BurnInDayRecord):
            raise TypeError("value must be BurnInDayRecord")
        baseline = self.baseline(value.baseline_identifier)
        if baseline is None:
            raise PaperTestCampaignError("campaign baseline is unavailable")
        value.require_baseline(baseline)
        return self._append(
            event_identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=CampaignEventType.BURN_IN_DAY_RECORDED,
            event_key=value.operation_date.isoformat(),
            occurred_at=value.recorded_at,
            payload=value.to_dict(),
            unique_key=True,
        )

    def append_scenario(self, value: FailureScenarioRecord) -> int:
        if not isinstance(value, FailureScenarioRecord):
            raise TypeError("value must be FailureScenarioRecord")
        baseline = self.baseline(value.baseline_identifier)
        if baseline is None:
            raise PaperTestCampaignError("campaign baseline is unavailable")
        value.require_baseline(baseline)
        return self._append(
            event_identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=CampaignEventType.FAILURE_SCENARIO_RECORDED,
            event_key=value.kind.value,
            occurred_at=value.recorded_at,
            payload=value.to_dict(),
            unique_key=False,
        )

    def append_report(self, value: PaperTestCampaignReport) -> int:
        if not isinstance(value, PaperTestCampaignReport):
            raise TypeError("value must be PaperTestCampaignReport")
        return self._append(
            event_identifier=value.identifier,
            baseline_identifier=value.baseline_identifier,
            event_type=CampaignEventType.CAMPAIGN_REPORT_RECORDED,
            event_key=value.evaluated_at.isoformat(),
            occurred_at=value.evaluated_at,
            payload=value.to_dict(),
            unique_key=True,
        )

    def _payloads(
        self,
        *,
        baseline_identifier: str,
        event_type: CampaignEventType,
    ) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE baseline_identifier=? AND event_type=? ORDER BY sequence",
                (baseline_identifier, event_type.value),
            ).fetchall()
        return tuple(json.loads(str(row["payload_json"])) for row in rows)

    def baseline(self, identifier: str) -> PaperTestCampaignBaseline | None:
        resolved = _text(identifier, field_name="identifier")
        payloads = self._payloads(
            baseline_identifier=resolved,
            event_type=CampaignEventType.BASELINE_RECORDED,
        )
        return None if not payloads else PaperTestCampaignBaseline.from_dict(payloads[-1])

    def days(self, baseline_identifier: str) -> tuple[BurnInDayRecord, ...]:
        return tuple(
            BurnInDayRecord.from_dict(item)
            for item in self._payloads(
                baseline_identifier=baseline_identifier,
                event_type=CampaignEventType.BURN_IN_DAY_RECORDED,
            )
        )

    def scenarios(
        self,
        baseline_identifier: str,
    ) -> tuple[FailureScenarioRecord, ...]:
        return tuple(
            FailureScenarioRecord.from_dict(item)
            for item in self._payloads(
                baseline_identifier=baseline_identifier,
                event_type=CampaignEventType.FAILURE_SCENARIO_RECORDED,
            )
        )

    def reports(
        self,
        baseline_identifier: str,
    ) -> tuple[PaperTestCampaignReport, ...]:
        return tuple(
            PaperTestCampaignReport.from_dict(item)
            for item in self._payloads(
                baseline_identifier=baseline_identifier,
                event_type=CampaignEventType.CAMPAIGN_REPORT_RECORDED,
            )
        )

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise PaperTestCampaignIntegrityError(
                    "campaign sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous:
                raise PaperTestCampaignIntegrityError(
                    "campaign previous hash is invalid"
                )
            actual = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                baseline_identifier=str(row["baseline_identifier"]),
                event_type=str(row["event_type"]),
                event_key=str(row["event_key"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous,
            )
            if str(row["content_hash"]) != actual:
                raise PaperTestCampaignIntegrityError(
                    "campaign content hash is invalid"
                )
            previous = actual
        return True


class PaperTestCampaignEvaluator:
    """Assess optional operating-day and required failure evidence."""

    def evaluate(
        self,
        *,
        baseline: PaperTestCampaignBaseline,
        days: tuple[BurnInDayRecord, ...],
        scenarios: tuple[FailureScenarioRecord, ...],
        evaluated_at: datetime,
    ) -> PaperTestCampaignReport:
        if not isinstance(baseline, PaperTestCampaignBaseline):
            raise TypeError("baseline must be PaperTestCampaignBaseline")
        timestamp = _aware(evaluated_at, field_name="evaluated_at")
        for item in days:
            item.require_baseline(baseline)
        for item in scenarios:
            item.require_baseline(baseline)
        eligible_dates = tuple(
            sorted(
                item.operation_date
                for item in days
                if item.creditable and item.operation_date <= timestamp.date()
            )
        )
        consecutive = 0
        if eligible_dates:
            current = eligible_dates[-1]
            consecutive = 1
            for candidate in reversed(eligible_dates[:-1]):
                if (current - candidate).days == 1:
                    consecutive += 1
                    current = candidate
                else:
                    break
        latest_scenarios: dict[FailureScenarioKind, FailureScenarioRecord] = {}
        for item in scenarios:
            if item.recorded_at <= timestamp:
                latest_scenarios[item.kind] = item
        missing = tuple(
            item
            for item in baseline.required_failure_scenarios
            if item not in latest_scenarios
        )
        failed = tuple(
            item
            for item in baseline.required_failure_scenarios
            if item in latest_scenarios and not latest_scenarios[item].passed
        )
        passed = tuple(
            item
            for item in baseline.required_failure_scenarios
            if item in latest_scenarios and latest_scenarios[item].passed
        )
        blockers: list[str] = []
        if (
            baseline.required_consecutive_days > 0
            and consecutive < baseline.required_consecutive_days
        ):
            blockers.append(
                "optional operating-day evidence has not reached the configured requirement"
            )
        if missing:
            blockers.append(
                "required failure scenarios are missing: "
                + ", ".join(item.value for item in missing)
            )
        if failed:
            blockers.append(
                "required failure scenarios are not passing: "
                + ", ".join(item.value for item in failed)
            )
        non_creditable = tuple(item for item in days if not item.creditable)
        if non_creditable:
            blockers.append(
                "one or more recorded operating days failed campaign quality controls"
            )
        state = (
            PaperTestCampaignState.SATISFIED
            if not blockers
            else PaperTestCampaignState.BLOCKED
            if failed or non_creditable
            else PaperTestCampaignState.IN_PROGRESS
        )
        evidence = tuple(
            dict.fromkeys(
                (
                    baseline.identifier,
                    *(item.identifier for item in days),
                    *(item.identifier for item in latest_scenarios.values()),
                )
            )
        )
        return PaperTestCampaignReport(
            identifier=(
                f"paper-test-campaign-report:{baseline.identifier}:"
                f"{timestamp.isoformat()}"
            ),
            baseline_identifier=baseline.identifier,
            baseline_fingerprint=baseline.fingerprint,
            evaluated_at=timestamp,
            state=state,
            credited_dates=eligible_dates,
            consecutive_day_count=consecutive,
            required_consecutive_days=baseline.required_consecutive_days,
            passed_scenarios=passed,
            missing_scenarios=missing,
            failed_scenarios=failed,
            blockers=tuple(blockers),
            evidence_identifiers=evidence,
        )


__all__ = [
    "BurnInDayRecord",
    "CampaignEventType",
    "FailureScenarioKind",
    "FailureScenarioRecord",
    "FailureScenarioStatus",
    "PaperTestCampaignBaseline",
    "PaperTestCampaignError",
    "PaperTestCampaignEvaluator",
    "PaperTestCampaignIntegrityError",
    "PaperTestCampaignReport",
    "PaperTestCampaignState",
    "REQUIRED_FAILURE_SCENARIOS",
    "SQLitePaperTestCampaignStore",
]
