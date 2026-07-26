"""Production service-level objectives for the governed investment process.

The SLO layer is intentionally separate from analytical authority.  It measures
whether required production processes are operating on time and with intact
point-in-time evidence; it never manufactures a recommendation, changes a
threshold automatically, or upgrades incomplete data into authoritative data.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cio.persistence import CIOJournalIntegrityError, SQLiteCIOJournal
from data.security import SecurityMasterError
from data.security_master_ingestion import (
    SQLiteSecurityMasterOperationalStore,
    SecurityMasterActivationPolicy,
    SecurityMasterIngestionService,
)
from data.security_master_store import (
    SQLiteSecurityMasterStore,
    SecurityMasterIntegrityError,
)
from operations.metrics import MetricRegistry


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


def _non_negative_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return normalized


def _non_negative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
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
        raise ValueError("operational SLO payload must be finite JSON") from error


class OperationalSLOName(str, Enum):
    PROVIDER_FRESHNESS = "provider_freshness"
    FULL_UNIVERSE_CYCLE = "full_universe_cycle_completion"
    THESIS_REVIEW = "thesis_review_latency"
    DECISION_EVALUATION = "decision_evaluation_latency"


class OperationalSLOStatus(str, Enum):
    MET = "met"
    PENDING = "pending"
    BREACHED = "breached"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class FullUniverseCycleStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OperationalSLOPolicy:
    """Versioned deadlines and required-state policy for production operations."""

    version: str = "operational-slo.v1"
    provider_maximum_age_hours: float = 36.0
    screening_timezone: str = "America/New_York"
    screening_hour: int = 7
    screening_completion_deadline_minutes: int = 120
    screening_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    thesis_review_grace_hours: float = 24.0
    decision_evaluation_grace_hours: float = 48.0
    provider_required: bool = True
    screening_cycle_required: bool = True
    thesis_review_required: bool = True
    decision_evaluation_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "version",
            _required_text(self.version, field_name="version"),
        )
        for field_name in (
            "provider_maximum_age_hours",
            "thesis_review_grace_hours",
            "decision_evaluation_grace_hours",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_number(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if isinstance(self.screening_hour, bool) or not isinstance(
            self.screening_hour,
            int,
        ):
            raise TypeError("screening_hour must be an integer")
        if not 0 <= self.screening_hour <= 23:
            raise ValueError("screening_hour must be between 0 and 23")
        if (
            isinstance(self.screening_completion_deadline_minutes, bool)
            or not isinstance(self.screening_completion_deadline_minutes, int)
        ):
            raise TypeError(
                "screening_completion_deadline_minutes must be an integer"
            )
        if not 1 <= self.screening_completion_deadline_minutes <= 1440:
            raise ValueError(
                "screening_completion_deadline_minutes must be between 1 and 1440"
            )
        try:
            ZoneInfo(self.screening_timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(
                f"unknown screening timezone: {self.screening_timezone}"
            ) from error
        if not isinstance(self.screening_weekdays, tuple):
            raise TypeError("screening_weekdays must be a tuple")
        weekdays = tuple(dict.fromkeys(self.screening_weekdays))
        if not weekdays or any(
            isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6
            for item in weekdays
        ):
            raise ValueError("screening_weekdays must contain weekday integers 0-6")
        object.__setattr__(self, "screening_weekdays", weekdays)
        for field_name in (
            "provider_required",
            "screening_cycle_required",
            "thesis_review_required",
            "decision_evaluation_required",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    def expected_screening_time(self, evaluated_at: datetime) -> datetime:
        """Return the latest scheduled screening boundary not after evaluation."""

        evaluated = _aware(evaluated_at, field_name="evaluated_at")
        zone = ZoneInfo(self.screening_timezone)
        local = evaluated.astimezone(zone)
        candidate_date = local.date()
        candidate = datetime.combine(
            candidate_date,
            time(hour=self.screening_hour),
            tzinfo=zone,
        )
        if candidate > local:
            candidate_date -= timedelta(days=1)
        while candidate_date.weekday() not in self.screening_weekdays:
            candidate_date -= timedelta(days=1)
        return datetime.combine(
            candidate_date,
            time(hour=self.screening_hour),
            tzinfo=zone,
        ).astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class FullUniverseCycleRecord:
    """Immutable terminal record for one expected full-universe cycle."""

    identifier: str
    scheduled_for: datetime
    started_at: datetime
    completed_at: datetime
    status: FullUniverseCycleStatus
    security_master_catalog_identifier: str | None
    universe_snapshot_identifier: str | None
    eligible_instrument_count: int
    screened_instrument_count: int
    qualified_candidate_count: int
    error: str | None = None
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        for field_name in ("scheduled_for", "started_at", "completed_at"):
            object.__setattr__(
                self,
                field_name,
                _aware(getattr(self, field_name), field_name=field_name),
            )
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot predate started_at")
        if not isinstance(self.status, FullUniverseCycleStatus):
            raise TypeError("status must be FullUniverseCycleStatus")
        for field_name in (
            "eligible_instrument_count",
            "screened_instrument_count",
            "qualified_candidate_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_integer(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if self.screened_instrument_count > self.eligible_instrument_count:
            raise ValueError("screened_instrument_count cannot exceed eligible count")
        if self.qualified_candidate_count > self.screened_instrument_count:
            raise ValueError(
                "qualified_candidate_count cannot exceed screened count"
            )
        for field_name in (
            "security_master_catalog_identifier",
            "universe_snapshot_identifier",
            "error",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _required_text(value, field_name=field_name),
                )
        if self.status is FullUniverseCycleStatus.COMPLETED:
            if self.security_master_catalog_identifier is None:
                raise ValueError("completed cycle requires security-master catalog")
            if self.universe_snapshot_identifier is None:
                raise ValueError("completed cycle requires universe snapshot")
            if self.error is not None:
                raise ValueError("completed cycle cannot contain an error")
        elif self.error is None:
            raise ValueError("failed cycle requires an error")
        recorded = self.recorded_at or self.completed_at
        object.__setattr__(
            self,
            "recorded_at",
            _aware(recorded, field_name="recorded_at"),
        )
        if recorded < self.completed_at:
            raise ValueError("recorded_at cannot predate completed_at")

    @property
    def completion_latency_minutes(self) -> float:
        return round(
            max(
                0.0,
                (self.completed_at - self.scheduled_for).total_seconds() / 60.0,
            ),
            10,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "scheduled_for": self.scheduled_for.isoformat(),
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "status": self.status.value,
            "security_master_catalog_identifier": (
                self.security_master_catalog_identifier
            ),
            "universe_snapshot_identifier": self.universe_snapshot_identifier,
            "eligible_instrument_count": self.eligible_instrument_count,
            "screened_instrument_count": self.screened_instrument_count,
            "qualified_candidate_count": self.qualified_candidate_count,
            "error": self.error,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FullUniverseCycleRecord":
        return cls(
            identifier=str(payload["identifier"]),
            scheduled_for=datetime.fromisoformat(str(payload["scheduled_for"])),
            started_at=datetime.fromisoformat(str(payload["started_at"])),
            completed_at=datetime.fromisoformat(str(payload["completed_at"])),
            status=FullUniverseCycleStatus(str(payload["status"])),
            security_master_catalog_identifier=payload.get(
                "security_master_catalog_identifier"
            ),
            universe_snapshot_identifier=payload.get(
                "universe_snapshot_identifier"
            ),
            eligible_instrument_count=int(payload["eligible_instrument_count"]),
            screened_instrument_count=int(payload["screened_instrument_count"]),
            qualified_candidate_count=int(payload["qualified_candidate_count"]),
            error=payload.get("error"),
            recorded_at=datetime.fromisoformat(str(payload["recorded_at"])),
        )


@dataclass(frozen=True, slots=True)
class SecurityMasterSLOObservation:
    configured: bool
    screening_ready: bool
    catalog_integrity_verified: bool
    operation_integrity_verified: bool
    active_catalog_identifier: str | None
    source_age_hours: float | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "configured",
            "screening_ready",
            "catalog_integrity_verified",
            "operation_integrity_verified",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        if self.active_catalog_identifier is not None:
            object.__setattr__(
                self,
                "active_catalog_identifier",
                _required_text(
                    self.active_catalog_identifier,
                    field_name="active_catalog_identifier",
                ),
            )
        if self.source_age_hours is not None:
            object.__setattr__(
                self,
                "source_age_hours",
                _non_negative_number(
                    self.source_age_hours,
                    field_name="source_age_hours",
                ),
            )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class ThesisSLOObservation:
    identifier: str
    state: str
    next_review_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("identifier", "state"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "next_review_at",
            _aware(self.next_review_at, field_name="next_review_at"),
        )


@dataclass(frozen=True, slots=True)
class DecisionEvaluationSLOObservation:
    snapshot_identifier: str
    decision_at: datetime
    horizon_days: int
    evaluated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_identifier",
            _required_text(
                self.snapshot_identifier,
                field_name="snapshot_identifier",
            ),
        )
        object.__setattr__(
            self,
            "decision_at",
            _aware(self.decision_at, field_name="decision_at"),
        )
        if isinstance(self.horizon_days, bool) or not isinstance(
            self.horizon_days,
            int,
        ):
            raise TypeError("horizon_days must be an integer")
        if self.horizon_days < 1:
            raise ValueError("horizon_days must be positive")
        if self.evaluated_at is not None:
            object.__setattr__(
                self,
                "evaluated_at",
                _aware(self.evaluated_at, field_name="evaluated_at"),
            )

    @property
    def horizon_ended_at(self) -> datetime:
        return self.decision_at + timedelta(days=self.horizon_days)


@dataclass(frozen=True, slots=True)
class OperationalSLOInputs:
    security_master: SecurityMasterSLOObservation
    cycles: tuple[FullUniverseCycleRecord, ...] = ()
    journal_integrity_verified: bool = True
    journal_reasons: tuple[str, ...] = ()
    slo_integrity_verified: bool = True
    slo_reasons: tuple[str, ...] = ()
    theses: tuple[ThesisSLOObservation, ...] = ()
    evaluations: tuple[DecisionEvaluationSLOObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.security_master, SecurityMasterSLOObservation):
            raise TypeError("security_master must be SecurityMasterSLOObservation")
        if not isinstance(self.cycles, tuple) or not all(
            isinstance(item, FullUniverseCycleRecord) for item in self.cycles
        ):
            raise TypeError("cycles must contain FullUniverseCycleRecord values")
        if not isinstance(self.journal_integrity_verified, bool):
            raise TypeError("journal_integrity_verified must be a bool")
        if not isinstance(self.journal_reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.journal_reasons
        ):
            raise TypeError("journal_reasons must contain non-empty strings")
        if not isinstance(self.slo_integrity_verified, bool):
            raise TypeError("slo_integrity_verified must be a bool")
        if not isinstance(self.slo_reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.slo_reasons
        ):
            raise TypeError("slo_reasons must contain non-empty strings")
        if not isinstance(self.theses, tuple) or not all(
            isinstance(item, ThesisSLOObservation) for item in self.theses
        ):
            raise TypeError("theses must contain ThesisSLOObservation values")
        if not isinstance(self.evaluations, tuple) or not all(
            isinstance(item, DecisionEvaluationSLOObservation)
            for item in self.evaluations
        ):
            raise TypeError(
                "evaluations must contain DecisionEvaluationSLOObservation values"
            )


@dataclass(frozen=True, slots=True)
class OperationalSLOComponent:
    name: OperationalSLOName
    status: OperationalSLOStatus
    required: bool
    objective: str
    detail: str
    observed_at: datetime | None = None
    deadline_at: datetime | None = None
    actual_value: float | None = None
    threshold_value: float | None = None
    unit: str | None = None
    affected_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, OperationalSLOName):
            raise TypeError("name must be OperationalSLOName")
        if not isinstance(self.status, OperationalSLOStatus):
            raise TypeError("status must be OperationalSLOStatus")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")
        for field_name in ("objective", "detail"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("observed_at", "deadline_at"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _aware(value, field_name=field_name),
                )
        for field_name in ("actual_value", "threshold_value"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _non_negative_number(value, field_name=field_name),
                )
        if self.unit is not None:
            object.__setattr__(
                self,
                "unit",
                _required_text(self.unit, field_name="unit"),
            )
        if not isinstance(self.affected_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.affected_identifiers
        ):
            raise TypeError("affected_identifiers must contain non-empty strings")

    @property
    def ready(self) -> bool:
        return self.status in {
            OperationalSLOStatus.MET,
            OperationalSLOStatus.PENDING,
            OperationalSLOStatus.NOT_APPLICABLE,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "status": self.status.value,
            "required": self.required,
            "ready": self.ready,
            "objective": self.objective,
            "detail": self.detail,
            "observed_at": (
                None if self.observed_at is None else self.observed_at.isoformat()
            ),
            "deadline_at": (
                None if self.deadline_at is None else self.deadline_at.isoformat()
            ),
            "actual_value": self.actual_value,
            "threshold_value": self.threshold_value,
            "unit": self.unit,
            "affected_identifiers": list(self.affected_identifiers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationalSLOComponent":
        return cls(
            name=OperationalSLOName(str(payload["name"])),
            status=OperationalSLOStatus(str(payload["status"])),
            required=bool(payload["required"]),
            objective=str(payload["objective"]),
            detail=str(payload["detail"]),
            observed_at=(
                None
                if payload.get("observed_at") is None
                else datetime.fromisoformat(str(payload["observed_at"]))
            ),
            deadline_at=(
                None
                if payload.get("deadline_at") is None
                else datetime.fromisoformat(str(payload["deadline_at"]))
            ),
            actual_value=(
                None
                if payload.get("actual_value") is None
                else float(payload["actual_value"])
            ),
            threshold_value=(
                None
                if payload.get("threshold_value") is None
                else float(payload["threshold_value"])
            ),
            unit=payload.get("unit"),
            affected_identifiers=tuple(payload.get("affected_identifiers", ())),
        )


@dataclass(frozen=True, slots=True)
class OperationalSLOSnapshot:
    identifier: str
    evaluated_at: datetime
    policy_version: str
    ready: bool
    components: tuple[OperationalSLOComponent, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evaluated_at",
            _aware(self.evaluated_at, field_name="evaluated_at"),
        )
        if not isinstance(self.ready, bool):
            raise TypeError("ready must be a bool")
        if not isinstance(self.components, tuple) or not self.components or not all(
            isinstance(item, OperationalSLOComponent) for item in self.components
        ):
            raise TypeError(
                "components must be a non-empty tuple of OperationalSLOComponent"
            )
        names = tuple(item.name for item in self.components)
        if len(names) != len(set(names)):
            raise ValueError("components cannot repeat an SLO name")
        expected = all(item.ready for item in self.components if item.required)
        if self.ready != expected:
            raise ValueError("ready does not match required component state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "policy_version": self.policy_version,
            "ready": self.ready,
            "components": [item.to_dict() for item in self.components],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationalSLOSnapshot":
        return cls(
            identifier=str(payload["identifier"]),
            evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
            policy_version=str(payload["policy_version"]),
            ready=bool(payload["ready"]),
            components=tuple(
                OperationalSLOComponent.from_dict(item)
                for item in payload["components"]
            ),
        )

    def publish_metrics(self, registry: MetricRegistry) -> None:
        if not isinstance(registry, MetricRegistry):
            raise TypeError("registry must be MetricRegistry")
        registry.set_gauge(
            "capital_intelligence_operational_slo_ready",
            1.0 if self.ready else 0.0,
        )
        for item in self.components:
            labels = {"objective": item.name.value}
            registry.set_gauge(
                "capital_intelligence_operational_slo_objective_ready",
                1.0 if item.ready else 0.0,
                labels=labels,
            )
            for status in OperationalSLOStatus:
                registry.set_gauge(
                    "capital_intelligence_operational_slo_status",
                    1.0 if item.status is status else 0.0,
                    labels={
                        "objective": item.name.value,
                        "status": status.value,
                    },
                )
            if item.actual_value is not None:
                registry.set_gauge(
                    "capital_intelligence_operational_slo_actual",
                    item.actual_value,
                    labels={
                        "objective": item.name.value,
                        "unit": item.unit or "count",
                    },
                )
            if item.threshold_value is not None:
                registry.set_gauge(
                    "capital_intelligence_operational_slo_threshold",
                    item.threshold_value,
                    labels={
                        "objective": item.name.value,
                        "unit": item.unit or "count",
                    },
                )


class OperationalSLOEvaluator:
    """Pure point-in-time evaluator for the four production SLOs."""

    _MONITORED_THESIS_STATES = {
        "active",
        "strengthening",
        "stable",
        "weakening",
        "reduced",
    }

    def __init__(self, policy: OperationalSLOPolicy | None = None) -> None:
        self.policy = policy or OperationalSLOPolicy()

    def evaluate(
        self,
        inputs: OperationalSLOInputs,
        *,
        evaluated_at: datetime | None = None,
    ) -> OperationalSLOSnapshot:
        if not isinstance(inputs, OperationalSLOInputs):
            raise TypeError("inputs must be OperationalSLOInputs")
        evaluated = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        provider = self._provider_component(inputs.security_master)
        cycle = self._cycle_component(
            inputs,
            provider=provider,
            evaluated_at=evaluated,
        )
        thesis = self._thesis_component(inputs, evaluated_at=evaluated)
        evaluation = self._evaluation_component(inputs, evaluated_at=evaluated)
        components = (provider, cycle, thesis, evaluation)
        ready = all(item.ready for item in components if item.required)
        return OperationalSLOSnapshot(
            identifier=f"operational-slo:{evaluated.isoformat()}",
            evaluated_at=evaluated,
            policy_version=self.policy.version,
            ready=ready,
            components=components,
        )

    def _provider_component(
        self,
        observation: SecurityMasterSLOObservation,
    ) -> OperationalSLOComponent:
        objective = (
            "Maintain an authoritative, intact security master no more than "
            f"{self.policy.provider_maximum_age_hours:g} hours old."
        )
        if not observation.configured:
            return OperationalSLOComponent(
                name=OperationalSLOName.PROVIDER_FRESHNESS,
                status=OperationalSLOStatus.BLOCKED,
                required=self.policy.provider_required,
                objective=objective,
                detail="security-master operations database is not configured",
                threshold_value=self.policy.provider_maximum_age_hours,
                unit="hours",
            )
        if not (
            observation.catalog_integrity_verified
            and observation.operation_integrity_verified
        ):
            return OperationalSLOComponent(
                name=OperationalSLOName.PROVIDER_FRESHNESS,
                status=OperationalSLOStatus.BREACHED,
                required=self.policy.provider_required,
                objective=objective,
                detail="security-master catalog or operation hash chain is invalid",
                actual_value=observation.source_age_hours,
                threshold_value=self.policy.provider_maximum_age_hours,
                unit="hours",
                affected_identifiers=(
                    ()
                    if observation.active_catalog_identifier is None
                    else (observation.active_catalog_identifier,)
                ),
            )
        if not observation.screening_ready:
            detail = "; ".join(observation.reasons) or (
                "no authoritative security-master catalog is screening-ready"
            )
            return OperationalSLOComponent(
                name=OperationalSLOName.PROVIDER_FRESHNESS,
                status=OperationalSLOStatus.BLOCKED,
                required=self.policy.provider_required,
                objective=objective,
                detail=detail,
                actual_value=observation.source_age_hours,
                threshold_value=self.policy.provider_maximum_age_hours,
                unit="hours",
                affected_identifiers=(
                    ()
                    if observation.active_catalog_identifier is None
                    else (observation.active_catalog_identifier,)
                ),
            )
        if observation.source_age_hours is None:
            return OperationalSLOComponent(
                name=OperationalSLOName.PROVIDER_FRESHNESS,
                status=OperationalSLOStatus.BREACHED,
                required=self.policy.provider_required,
                objective=objective,
                detail="active security-master source age is unavailable",
                threshold_value=self.policy.provider_maximum_age_hours,
                unit="hours",
            )
        status = (
            OperationalSLOStatus.MET
            if observation.source_age_hours
            <= self.policy.provider_maximum_age_hours
            else OperationalSLOStatus.BREACHED
        )
        return OperationalSLOComponent(
            name=OperationalSLOName.PROVIDER_FRESHNESS,
            status=status,
            required=self.policy.provider_required,
            objective=objective,
            detail=(
                "authoritative security master is fresh and intact"
                if status is OperationalSLOStatus.MET
                else "authoritative security master exceeds the freshness objective"
            ),
            actual_value=observation.source_age_hours,
            threshold_value=self.policy.provider_maximum_age_hours,
            unit="hours",
            affected_identifiers=(
                ()
                if observation.active_catalog_identifier is None
                else (observation.active_catalog_identifier,)
            ),
        )

    def _cycle_component(
        self,
        inputs: OperationalSLOInputs,
        *,
        provider: OperationalSLOComponent,
        evaluated_at: datetime,
    ) -> OperationalSLOComponent:
        scheduled_for = self.policy.expected_screening_time(evaluated_at)
        deadline = scheduled_for + timedelta(
            minutes=self.policy.screening_completion_deadline_minutes
        )
        objective = (
            "Complete the full eligible-universe screening cycle within "
            f"{self.policy.screening_completion_deadline_minutes} minutes and "
            "screen every eligible instrument."
        )
        if not inputs.slo_integrity_verified:
            return OperationalSLOComponent(
                name=OperationalSLOName.FULL_UNIVERSE_CYCLE,
                status=OperationalSLOStatus.BREACHED,
                required=self.policy.screening_cycle_required,
                objective=objective,
                detail="; ".join(inputs.slo_reasons)
                or "operational SLO history integrity is not verified",
                observed_at=scheduled_for,
                deadline_at=deadline,
                threshold_value=float(
                    self.policy.screening_completion_deadline_minutes
                ),
                unit="minutes",
            )
        if not provider.ready:
            return OperationalSLOComponent(
                name=OperationalSLOName.FULL_UNIVERSE_CYCLE,
                status=OperationalSLOStatus.BLOCKED,
                required=self.policy.screening_cycle_required,
                objective=objective,
                detail=(
                    "full-universe screening is blocked because authoritative "
                    "security-master readiness is not met"
                ),
                observed_at=scheduled_for,
                deadline_at=deadline,
                threshold_value=float(
                    self.policy.screening_completion_deadline_minutes
                ),
                unit="minutes",
            )
        matching = tuple(
            item for item in inputs.cycles if item.scheduled_for == scheduled_for
        )
        record = max(matching, key=lambda item: item.recorded_at) if matching else None
        if record is None:
            pending = evaluated_at <= deadline
            return OperationalSLOComponent(
                name=OperationalSLOName.FULL_UNIVERSE_CYCLE,
                status=(
                    OperationalSLOStatus.PENDING
                    if pending
                    else OperationalSLOStatus.BREACHED
                ),
                required=self.policy.screening_cycle_required,
                objective=objective,
                detail=(
                    "the expected full-universe cycle is still within its deadline"
                    if pending
                    else "no terminal full-universe cycle record exists by the deadline"
                ),
                observed_at=scheduled_for,
                deadline_at=deadline,
                actual_value=max(
                    0.0,
                    (evaluated_at - scheduled_for).total_seconds() / 60.0,
                ),
                threshold_value=float(
                    self.policy.screening_completion_deadline_minutes
                ),
                unit="minutes",
            )
        identifiers = (record.identifier,)
        if record.status is FullUniverseCycleStatus.FAILED:
            return OperationalSLOComponent(
                name=OperationalSLOName.FULL_UNIVERSE_CYCLE,
                status=OperationalSLOStatus.BREACHED,
                required=self.policy.screening_cycle_required,
                objective=objective,
                detail=f"full-universe cycle failed: {record.error}",
                observed_at=record.completed_at,
                deadline_at=deadline,
                actual_value=record.completion_latency_minutes,
                threshold_value=float(
                    self.policy.screening_completion_deadline_minutes
                ),
                unit="minutes",
                affected_identifiers=identifiers,
            )
        problems: list[str] = []
        active_catalog = inputs.security_master.active_catalog_identifier
        if record.security_master_catalog_identifier != active_catalog:
            problems.append("cycle did not use the currently active security master")
        if record.eligible_instrument_count < 1:
            problems.append("cycle reported no eligible instruments")
        if record.screened_instrument_count != record.eligible_instrument_count:
            problems.append(
                "cycle did not screen every eligible instrument "
                f"({record.screened_instrument_count}/"
                f"{record.eligible_instrument_count})"
            )
        if record.completed_at > deadline:
            problems.append("cycle completed after its deadline")
        status = (
            OperationalSLOStatus.MET
            if not problems
            else OperationalSLOStatus.BREACHED
        )
        return OperationalSLOComponent(
            name=OperationalSLOName.FULL_UNIVERSE_CYCLE,
            status=status,
            required=self.policy.screening_cycle_required,
            objective=objective,
            detail=(
                "full eligible universe was screened by the deadline"
                if not problems
                else "; ".join(problems)
            ),
            observed_at=record.completed_at,
            deadline_at=deadline,
            actual_value=record.completion_latency_minutes,
            threshold_value=float(self.policy.screening_completion_deadline_minutes),
            unit="minutes",
            affected_identifiers=identifiers,
        )

    def _thesis_component(
        self,
        inputs: OperationalSLOInputs,
        *,
        evaluated_at: datetime,
    ) -> OperationalSLOComponent:
        objective = (
            "Review every monitored living thesis no later than "
            f"{self.policy.thesis_review_grace_hours:g} hours after its "
            "scheduled review time."
        )
        if not inputs.journal_integrity_verified:
            return OperationalSLOComponent(
                name=OperationalSLOName.THESIS_REVIEW,
                status=OperationalSLOStatus.BLOCKED,
                required=self.policy.thesis_review_required,
                objective=objective,
                detail="; ".join(inputs.journal_reasons)
                or "canonical CIO journal integrity is not verified",
                threshold_value=self.policy.thesis_review_grace_hours,
                unit="hours",
            )
        monitored = tuple(
            item
            for item in inputs.theses
            if item.state.casefold() in self._MONITORED_THESIS_STATES
        )
        if not monitored:
            return OperationalSLOComponent(
                name=OperationalSLOName.THESIS_REVIEW,
                status=OperationalSLOStatus.NOT_APPLICABLE,
                required=self.policy.thesis_review_required,
                objective=objective,
                detail="no active ownership thesis currently requires monitoring",
                threshold_value=self.policy.thesis_review_grace_hours,
                unit="hours",
            )
        grace = timedelta(hours=self.policy.thesis_review_grace_hours)
        overdue = tuple(
            item for item in monitored if evaluated_at > item.next_review_at + grace
        )
        maximum_lateness = max(
            (
                max(
                    0.0,
                    (evaluated_at - item.next_review_at).total_seconds() / 3600.0,
                )
                for item in monitored
            ),
            default=0.0,
        )
        return OperationalSLOComponent(
            name=OperationalSLOName.THESIS_REVIEW,
            status=(
                OperationalSLOStatus.BREACHED
                if overdue
                else OperationalSLOStatus.MET
            ),
            required=self.policy.thesis_review_required,
            objective=objective,
            detail=(
                f"{len(overdue)} of {len(monitored)} monitored theses are overdue"
                if overdue
                else f"all {len(monitored)} monitored theses are within review policy"
            ),
            actual_value=maximum_lateness,
            threshold_value=self.policy.thesis_review_grace_hours,
            unit="hours",
            affected_identifiers=tuple(item.identifier for item in overdue),
        )

    def _evaluation_component(
        self,
        inputs: OperationalSLOInputs,
        *,
        evaluated_at: datetime,
    ) -> OperationalSLOComponent:
        objective = (
            "Evaluate each frozen decision evidence snapshot no later than "
            f"{self.policy.decision_evaluation_grace_hours:g} hours after its "
            "decision horizon ends."
        )
        if not inputs.journal_integrity_verified:
            return OperationalSLOComponent(
                name=OperationalSLOName.DECISION_EVALUATION,
                status=OperationalSLOStatus.BLOCKED,
                required=self.policy.decision_evaluation_required,
                objective=objective,
                detail="; ".join(inputs.journal_reasons)
                or "canonical CIO journal integrity is not verified",
                threshold_value=self.policy.decision_evaluation_grace_hours,
                unit="hours",
            )
        if not inputs.evaluations:
            return OperationalSLOComponent(
                name=OperationalSLOName.DECISION_EVALUATION,
                status=OperationalSLOStatus.NOT_APPLICABLE,
                required=self.policy.decision_evaluation_required,
                objective=objective,
                detail="no frozen decision evidence snapshots exist",
                threshold_value=self.policy.decision_evaluation_grace_hours,
                unit="hours",
            )
        grace = timedelta(hours=self.policy.decision_evaluation_grace_hours)
        outstanding = tuple(
            item
            for item in inputs.evaluations
            if item.evaluated_at is None
            and evaluated_at > item.horizon_ended_at + grace
        )
        pending = tuple(
            item
            for item in inputs.evaluations
            if item.evaluated_at is None and item not in outstanding
        )
        maximum_lateness = max(
            (
                max(
                    0.0,
                    (evaluated_at - item.horizon_ended_at).total_seconds()
                    / 3600.0,
                )
                for item in outstanding
            ),
            default=0.0,
        )
        return OperationalSLOComponent(
            name=OperationalSLOName.DECISION_EVALUATION,
            status=(
                OperationalSLOStatus.BREACHED
                if outstanding
                else OperationalSLOStatus.MET
            ),
            required=self.policy.decision_evaluation_required,
            objective=objective,
            detail=(
                f"{len(outstanding)} decision evaluations are overdue; "
                f"{len(pending)} have not reached their evaluation deadline"
                if outstanding
                else (
                    f"no decision evaluations are overdue; {len(pending)} have "
                    "not reached their evaluation deadline"
                )
            ),
            actual_value=maximum_lateness,
            threshold_value=self.policy.decision_evaluation_grace_hours,
            unit="hours",
            affected_identifiers=tuple(
                item.snapshot_identifier for item in outstanding
            ),
        )


class OperationalSLOIntegrityError(RuntimeError):
    """Raised when append-only SLO history fails integrity verification."""


class SQLiteOperationalSLOStore:
    """Append-only cycle and assessment history with independent hash chains."""

    _GENESIS_HASH = "0" * 64
    _CYCLE_TABLE = "full_universe_cycle_records"
    _SNAPSHOT_TABLE = "operational_slo_snapshots"

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
                f"""
                CREATE TABLE IF NOT EXISTS {self._CYCLE_TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    scheduled_for TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS full_universe_cycle_schedule
                ON {self._CYCLE_TABLE} (scheduled_for, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._CYCLE_TABLE}_no_update
                BEFORE UPDATE ON {self._CYCLE_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'operational SLO cycle history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._CYCLE_TABLE}_no_delete
                BEFORE DELETE ON {self._CYCLE_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'operational SLO cycle history is append-only');
                END;

                CREATE TABLE IF NOT EXISTS {self._SNAPSHOT_TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    evaluated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS operational_slo_evaluated_at
                ON {self._SNAPSHOT_TABLE} (evaluated_at, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._SNAPSHOT_TABLE}_no_update
                BEFORE UPDATE ON {self._SNAPSHOT_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'operational SLO assessment history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._SNAPSHOT_TABLE}_no_delete
                BEFORE DELETE ON {self._SNAPSHOT_TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'operational SLO assessment history is append-only');
                END;
                """
            )

    def append_cycle(self, record: FullUniverseCycleRecord) -> FullUniverseCycleRecord:
        if not isinstance(record, FullUniverseCycleRecord):
            raise TypeError("record must be FullUniverseCycleRecord")
        self._initialize()
        self.verify_integrity()
        payload_json = _canonical_json(record.to_dict())
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {self._CYCLE_TABLE} WHERE identifier = ?",
                (record.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "cycle identifier cannot be reused for different content"
                    )
                return record
            previous = connection.execute(
                f"SELECT content_hash FROM {self._CYCLE_TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = (
                self._GENESIS_HASH
                if previous is None
                else str(previous["content_hash"])
            )
            content_hash = self._hash(
                record.identifier,
                record.recorded_at,
                payload_json,
                previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._CYCLE_TABLE} (
                    identifier, scheduled_for, recorded_at, payload_json,
                    previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.identifier,
                    record.scheduled_for.isoformat(),
                    record.recorded_at.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return record

    def cycles(self, *, limit: int = 1000) -> tuple[FullUniverseCycleRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit < 1:
            raise ValueError("limit must be positive")
        if not self.path.exists():
            return ()
        with self._connect() as connection:
            if not self._has_table(connection, self._CYCLE_TABLE):
                return ()
            rows = connection.execute(
                f"SELECT payload_json FROM {self._CYCLE_TABLE} "
                "ORDER BY scheduled_for DESC, sequence DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            FullUniverseCycleRecord.from_dict(json.loads(str(row["payload_json"])))
            for row in rows
        )

    def append_snapshot(
        self,
        snapshot: OperationalSLOSnapshot,
    ) -> OperationalSLOSnapshot:
        if not isinstance(snapshot, OperationalSLOSnapshot):
            raise TypeError("snapshot must be OperationalSLOSnapshot")
        self._initialize()
        self.verify_integrity()
        payload_json = _canonical_json(snapshot.to_dict())
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {self._SNAPSHOT_TABLE} WHERE identifier = ?",
                (snapshot.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "SLO snapshot identifier cannot be reused for different content"
                    )
                return snapshot
            previous = connection.execute(
                f"SELECT content_hash FROM {self._SNAPSHOT_TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = (
                self._GENESIS_HASH
                if previous is None
                else str(previous["content_hash"])
            )
            content_hash = self._hash(
                snapshot.identifier,
                snapshot.evaluated_at,
                payload_json,
                previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._SNAPSHOT_TABLE} (
                    identifier, evaluated_at, payload_json, previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.identifier,
                    snapshot.evaluated_at.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return snapshot

    def latest_snapshot(self) -> OperationalSLOSnapshot | None:
        if not self.path.exists():
            return None
        with self._connect() as connection:
            if not self._has_table(connection, self._SNAPSHOT_TABLE):
                return None
            row = connection.execute(
                f"SELECT payload_json FROM {self._SNAPSHOT_TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return (
            None
            if row is None
            else OperationalSLOSnapshot.from_dict(
                json.loads(str(row["payload_json"]))
            )
        )

    def verify_integrity(self) -> bool:
        if not self.path.exists():
            return True
        with self._connect() as connection:
            for table in (self._CYCLE_TABLE, self._SNAPSHOT_TABLE):
                if not self._has_table(connection, table):
                    continue
                previous_hash = self._GENESIS_HASH
                expected_sequence = 1
                rows = connection.execute(
                    f"SELECT * FROM {table} ORDER BY sequence ASC"
                ).fetchall()
                for row in rows:
                    sequence = int(row["sequence"])
                    if sequence != expected_sequence:
                        raise OperationalSLOIntegrityError(
                            f"{table} sequence is not contiguous"
                        )
                    if str(row["previous_hash"]) != previous_hash:
                        raise OperationalSLOIntegrityError(
                            f"{table} previous hash does not match"
                        )
                    timestamp_field = (
                        "recorded_at"
                        if table == self._CYCLE_TABLE
                        else "evaluated_at"
                    )
                    expected_hash = self._hash(
                        str(row["identifier"]),
                        datetime.fromisoformat(str(row[timestamp_field])),
                        str(row["payload_json"]),
                        previous_hash,
                    )
                    if str(row["content_hash"]) != expected_hash:
                        raise OperationalSLOIntegrityError(
                            f"{table} content hash is invalid"
                        )
                    previous_hash = expected_hash
                    expected_sequence += 1
        return True

    @staticmethod
    def _has_table(connection: sqlite3.Connection, table: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _hash(
        identifier: str,
        timestamp: datetime,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        material = "\n".join(
            (identifier, timestamp.isoformat(), payload_json, previous_hash)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


class SQLiteOperationalSLOSource:
    """Read SLO observations from authoritative production stores."""

    def __init__(
        self,
        *,
        security_master_database: str | Path,
        journal_database: str | Path,
        slo_store: SQLiteOperationalSLOStore,
    ) -> None:
        self.security_master_database = Path(security_master_database)
        self.journal_database = Path(journal_database)
        if not isinstance(slo_store, SQLiteOperationalSLOStore):
            raise TypeError("slo_store must be SQLiteOperationalSLOStore")
        self.slo_store = slo_store

    def load(
        self,
        *,
        policy: OperationalSLOPolicy,
        evaluated_at: datetime,
    ) -> OperationalSLOInputs:
        if not isinstance(policy, OperationalSLOPolicy):
            raise TypeError("policy must be OperationalSLOPolicy")
        evaluated = _aware(evaluated_at, field_name="evaluated_at")
        security_master = self._security_master(policy, evaluated)
        try:
            self.slo_store.verify_integrity()
            slo_integrity = True
            slo_reasons: tuple[str, ...] = ()
            cycles = self.slo_store.cycles()
        except (OperationalSLOIntegrityError, sqlite3.Error, ValueError) as error:
            slo_integrity = False
            slo_reasons = (str(error),)
            cycles = ()
        journal_integrity, journal_reasons, theses, evaluations = self._journal()
        return OperationalSLOInputs(
            security_master=security_master,
            cycles=cycles,
            journal_integrity_verified=journal_integrity,
            journal_reasons=journal_reasons,
            slo_integrity_verified=slo_integrity,
            slo_reasons=slo_reasons,
            theses=theses,
            evaluations=evaluations,
        )

    def _security_master(
        self,
        policy: OperationalSLOPolicy,
        evaluated_at: datetime,
    ) -> SecurityMasterSLOObservation:
        if not self.security_master_database.exists():
            return SecurityMasterSLOObservation(
                configured=False,
                screening_ready=False,
                catalog_integrity_verified=True,
                operation_integrity_verified=True,
                active_catalog_identifier=None,
                source_age_hours=None,
                reasons=("security-master database does not exist",),
            )
        try:
            service = SecurityMasterIngestionService(
                SQLiteSecurityMasterStore(self.security_master_database),
                SQLiteSecurityMasterOperationalStore(
                    self.security_master_database
                ),
                activation_policy=SecurityMasterActivationPolicy(
                    maximum_catalog_age_hours=(
                        policy.provider_maximum_age_hours
                    ),
                ),
            )
            status = service.status(evaluated_at=evaluated_at)
        except (
            SecurityMasterError,
            SecurityMasterIntegrityError,
            sqlite3.Error,
            ValueError,
        ) as error:
            return SecurityMasterSLOObservation(
                configured=True,
                screening_ready=False,
                catalog_integrity_verified=False,
                operation_integrity_verified=False,
                active_catalog_identifier=None,
                source_age_hours=None,
                reasons=(str(error),),
            )
        return SecurityMasterSLOObservation(
            configured=True,
            screening_ready=status.screening_ready,
            catalog_integrity_verified=status.catalog_integrity_verified,
            operation_integrity_verified=status.operation_integrity_verified,
            active_catalog_identifier=status.active_catalog_identifier,
            source_age_hours=status.active_source_age_hours,
            reasons=status.reasons,
        )

    def _journal(
        self,
    ) -> tuple[
        bool,
        tuple[str, ...],
        tuple[ThesisSLOObservation, ...],
        tuple[DecisionEvaluationSLOObservation, ...],
    ]:
        if not self.journal_database.exists():
            return False, ("canonical CIO journal database does not exist",), (), ()
        try:
            with sqlite3.connect(self.journal_database) as connection:
                connection.row_factory = sqlite3.Row
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'cio_journal_events'"
                ).fetchone()
                if table is None:
                    return False, ("canonical CIO journal table does not exist",), (), ()
            SQLiteCIOJournal(self.journal_database).verify_integrity()
            with sqlite3.connect(self.journal_database) as connection:
                connection.row_factory = sqlite3.Row
                thesis_rows = connection.execute(
                    """
                    SELECT event.payload_json
                    FROM cio_journal_events AS event
                    JOIN (
                        SELECT aggregate_identifier, MAX(sequence) AS sequence
                        FROM cio_journal_events
                        WHERE event_type = 'thesis_snapshot'
                        GROUP BY aggregate_identifier
                    ) AS latest
                    ON event.sequence = latest.sequence
                    ORDER BY event.sequence ASC
                    """
                ).fetchall()
                evidence_rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM cio_journal_events
                    WHERE event_type = 'decision_evidence_snapshot'
                    ORDER BY sequence ASC
                    """
                ).fetchall()
                evaluation_rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM cio_journal_events
                    WHERE event_type = 'decision_evaluation'
                    ORDER BY sequence ASC
                    """
                ).fetchall()
        except (sqlite3.Error, CIOJournalIntegrityError, ValueError) as error:
            return False, (str(error),), (), ()
        try:
            theses = tuple(
                self._thesis(json.loads(str(row["payload_json"])))
                for row in thesis_rows
            )
            evaluated = {
                str(payload["snapshot_identifier"]): datetime.fromisoformat(
                    str(payload["evaluated_at"])
                )
                for payload in (
                    json.loads(str(row["payload_json"]))
                    for row in evaluation_rows
                )
            }
            evaluations = tuple(
                self._evaluation(
                    json.loads(str(row["payload_json"])),
                    evaluated=evaluated,
                )
                for row in evidence_rows
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            return False, (f"canonical CIO journal SLO payload is invalid: {error}",), (), ()
        return True, (), theses, evaluations

    @staticmethod
    def _thesis(payload: Mapping[str, Any]) -> ThesisSLOObservation:
        return ThesisSLOObservation(
            identifier=str(payload["identifier"]),
            state=str(payload["state"]),
            next_review_at=datetime.fromisoformat(str(payload["next_review_at"])),
        )

    @staticmethod
    def _evaluation(
        payload: Mapping[str, Any],
        *,
        evaluated: Mapping[str, datetime],
    ) -> DecisionEvaluationSLOObservation:
        identifier = str(payload["identifier"])
        return DecisionEvaluationSLOObservation(
            snapshot_identifier=identifier,
            decision_at=datetime.fromisoformat(str(payload["decision_as_of"])),
            horizon_days=int(payload["decision_horizon_days"]),
            evaluated_at=evaluated.get(identifier),
        )


class OperationalSLOService:
    """Load authoritative observations, evaluate objectives, and optionally record."""

    def __init__(
        self,
        source: SQLiteOperationalSLOSource,
        evaluator: OperationalSLOEvaluator,
        store: SQLiteOperationalSLOStore,
    ) -> None:
        if not isinstance(source, SQLiteOperationalSLOSource):
            raise TypeError("source must be SQLiteOperationalSLOSource")
        if not isinstance(evaluator, OperationalSLOEvaluator):
            raise TypeError("evaluator must be OperationalSLOEvaluator")
        if not isinstance(store, SQLiteOperationalSLOStore):
            raise TypeError("store must be SQLiteOperationalSLOStore")
        self.source = source
        self.evaluator = evaluator
        self.store = store

    def assess(
        self,
        *,
        evaluated_at: datetime | None = None,
        record: bool = False,
    ) -> OperationalSLOSnapshot:
        evaluated = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        inputs = self.source.load(
            policy=self.evaluator.policy,
            evaluated_at=evaluated,
        )
        snapshot = self.evaluator.evaluate(inputs, evaluated_at=evaluated)
        if record:
            self.store.append_snapshot(snapshot)
        return snapshot


def operational_slo_policy_from_settings(settings: object) -> OperationalSLOPolicy:
    """Build the versioned SLO policy from validated operational settings."""

    required_fields = (
        "slo_provider_maximum_age_hours",
        "slo_screening_timezone",
        "slo_screening_hour",
        "slo_screening_completion_deadline_minutes",
        "slo_thesis_review_grace_hours",
        "slo_decision_evaluation_grace_hours",
    )
    missing = tuple(name for name in required_fields if not hasattr(settings, name))
    if missing:
        raise TypeError(
            "settings is missing operational SLO fields: " + ", ".join(missing)
        )
    return OperationalSLOPolicy(
        provider_maximum_age_hours=float(
            getattr(settings, "slo_provider_maximum_age_hours")
        ),
        screening_timezone=str(getattr(settings, "slo_screening_timezone")),
        screening_hour=int(getattr(settings, "slo_screening_hour")),
        screening_completion_deadline_minutes=int(
            getattr(settings, "slo_screening_completion_deadline_minutes")
        ),
        thesis_review_grace_hours=float(
            getattr(settings, "slo_thesis_review_grace_hours")
        ),
        decision_evaluation_grace_hours=float(
            getattr(settings, "slo_decision_evaluation_grace_hours")
        ),
    )


def build_operational_slo_service(
    *,
    security_master_database: str | Path,
    journal_database: str | Path,
    slo_database: str | Path,
    policy: OperationalSLOPolicy,
    initialize_store: bool = False,
) -> OperationalSLOService:
    store = SQLiteOperationalSLOStore(
        slo_database,
        initialize=initialize_store,
    )
    return OperationalSLOService(
        SQLiteOperationalSLOSource(
            security_master_database=security_master_database,
            journal_database=journal_database,
            slo_store=store,
        ),
        OperationalSLOEvaluator(policy),
        store,
    )


__all__ = [
    "DecisionEvaluationSLOObservation",
    "FullUniverseCycleRecord",
    "FullUniverseCycleStatus",
    "OperationalSLOComponent",
    "OperationalSLOEvaluator",
    "OperationalSLOInputs",
    "OperationalSLOIntegrityError",
    "OperationalSLOName",
    "OperationalSLOPolicy",
    "OperationalSLOService",
    "OperationalSLOSnapshot",
    "OperationalSLOStatus",
    "SQLiteOperationalSLOSource",
    "SQLiteOperationalSLOStore",
    "SecurityMasterSLOObservation",
    "ThesisSLOObservation",
    "build_operational_slo_service",
    "operational_slo_policy_from_settings",
]
