"""Assemble operational test-readiness evidence from canonical authorities.

The assembler reads daily-operation history, SLO assessments, resilience reports,
and the operational incident register.  It does not certify a product gate.  It
records the current operational facts in ``OperationalReadinessSnapshot`` so the
separate human-governed readiness certifications can be evaluated honestly.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from governance.readiness_evidence import (
    OperationalReadinessSnapshot,
    SQLiteReadinessEvidenceStore,
)
from operations.daily_orchestration import (
    DailyOperationEventType,
    FailureClassification,
    SQLiteCanonicalDailyOperationsStore,
)
from operations.incidents import SQLiteOperationalIncidentStore
from operations.resilience import SQLiteResilienceExerciseStore
from operations.slo import SQLiteOperationalSLOStore


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
    return value


@dataclass(frozen=True, slots=True)
class OperationalReadinessAssemblyPolicy:
    """Freshness boundaries for repository-generated operational evidence."""

    maximum_daily_operation_age: timedelta = timedelta(hours=24)
    maximum_slo_age: timedelta = timedelta(hours=24)
    maximum_resilience_report_age: timedelta = timedelta(days=30)
    version: str = "operational-readiness-assembly.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, field_name="version"))
        for field_name in (
            "maximum_daily_operation_age",
            "maximum_slo_age",
            "maximum_resilience_report_age",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, timedelta):
                raise TypeError(f"{field_name} must be timedelta")
            if value <= timedelta(0):
                raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, slots=True)
class OperationalReadinessAssemblyResult:
    snapshot: OperationalReadinessSnapshot
    blockers: tuple[str, ...]
    daily_operation_identifier: str | None
    slo_snapshot_identifier: str | None
    resilience_report_identifier: str | None
    incident_identifiers: tuple[str, ...]
    policy_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, OperationalReadinessSnapshot):
            raise TypeError("snapshot must be OperationalReadinessSnapshot")
        if not isinstance(self.blockers, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.blockers
        ):
            raise TypeError("blockers must contain non-empty strings")
        for field_name in (
            "daily_operation_identifier",
            "slo_snapshot_identifier",
            "resilience_report_identifier",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _text(value, field_name=field_name),
                )
        if not isinstance(self.incident_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.incident_identifiers
        ):
            raise TypeError("incident_identifiers must contain non-empty strings")
        object.__setattr__(
            self,
            "policy_version",
            _text(self.policy_version, field_name="policy_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "blockers": list(self.blockers),
            "daily_operation_identifier": self.daily_operation_identifier,
            "slo_snapshot_identifier": self.slo_snapshot_identifier,
            "resilience_report_identifier": self.resilience_report_identifier,
            "incident_identifiers": list(self.incident_identifiers),
            "policy_version": self.policy_version,
            "real_money_authorized": False,
        }


class OperationalReadinessAssembler:
    """Create and persist one fail-closed operational-readiness snapshot."""

    def __init__(
        self,
        *,
        daily_store: SQLiteCanonicalDailyOperationsStore,
        slo_store: SQLiteOperationalSLOStore,
        resilience_store: SQLiteResilienceExerciseStore,
        incident_store: SQLiteOperationalIncidentStore,
        readiness_store: SQLiteReadinessEvidenceStore,
        policy: OperationalReadinessAssemblyPolicy | None = None,
    ) -> None:
        if not isinstance(daily_store, SQLiteCanonicalDailyOperationsStore):
            raise TypeError("daily_store must be SQLiteCanonicalDailyOperationsStore")
        if not isinstance(slo_store, SQLiteOperationalSLOStore):
            raise TypeError("slo_store must be SQLiteOperationalSLOStore")
        if not isinstance(resilience_store, SQLiteResilienceExerciseStore):
            raise TypeError("resilience_store must be SQLiteResilienceExerciseStore")
        if not isinstance(incident_store, SQLiteOperationalIncidentStore):
            raise TypeError("incident_store must be SQLiteOperationalIncidentStore")
        if not isinstance(readiness_store, SQLiteReadinessEvidenceStore):
            raise TypeError("readiness_store must be SQLiteReadinessEvidenceStore")
        self.daily_store = daily_store
        self.slo_store = slo_store
        self.resilience_store = resilience_store
        self.incident_store = incident_store
        self.readiness_store = readiness_store
        self.policy = policy or OperationalReadinessAssemblyPolicy()

    def assemble(
        self,
        *,
        assessed_at: datetime,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
    ) -> OperationalReadinessAssemblyResult:
        timestamp = _aware(assessed_at, field_name="assessed_at")
        baseline = _text(baseline_identifier, field_name="baseline_identifier")
        process = _text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        blockers: list[str] = []
        sources: list[str] = [
            f"operational-readiness-policy:{self.policy.version}"
        ]
        data_failures = 0
        reconciliation_failures = 0

        daily_id: str | None = None
        try:
            self.daily_store.verify_integrity()
            daily = self._latest_daily_operation(
                assessed_at=timestamp,
                baseline_identifier=baseline,
                process_version=process,
                code_version=code,
            )
        except (sqlite3.Error, RuntimeError, TypeError, ValueError) as error:
            daily = None
            data_failures += 1
            blockers.append(f"daily-operation authority integrity failed: {error}")
        if daily is None:
            blockers.append("matching canonical daily operation is unavailable")
        else:
            daily_id = str(daily["operation_identifier"])
            sources.extend(
                (
                    daily_id,
                    str(daily["claim_event_identifier"]),
                    str(daily["terminal_event_identifier"]),
                    *tuple(str(item) for item in daily["output_identifiers"]),
                )
            )
            terminal_at = datetime.fromisoformat(str(daily["terminal_at"]))
            if timestamp - terminal_at > self.policy.maximum_daily_operation_age:
                blockers.append("canonical daily operation evidence is stale")
            if not bool(daily["completed"]):
                classification = str(daily["classification"])
                blockers.append(
                    "canonical daily operation did not complete: "
                    f"classification={classification}"
                )
                if classification in {
                    FailureClassification.INTEGRITY.value,
                    FailureClassification.DATA_QUALITY.value,
                }:
                    data_failures += 1
                if classification == FailureClassification.RECONCILIATION.value:
                    reconciliation_failures += 1

        slo_id: str | None = None
        try:
            self.slo_store.verify_integrity()
            slo = self.slo_store.latest_snapshot()
        except (sqlite3.Error, RuntimeError, TypeError, ValueError) as error:
            slo = None
            data_failures += 1
            blockers.append(f"SLO authority integrity failed: {error}")
        if slo is None:
            blockers.append("operational SLO snapshot is unavailable")
        else:
            slo_id = slo.identifier
            sources.append(slo.identifier)
            if slo.evaluated_at > timestamp:
                blockers.append("operational SLO snapshot is future-known")
            elif timestamp - slo.evaluated_at > self.policy.maximum_slo_age:
                blockers.append("operational SLO snapshot is stale")
            if not slo.ready:
                blockers.append("operational SLO snapshot is not ready")
                sources.extend(
                    identifier
                    for component in slo.components
                    if not component.ready
                    for identifier in component.affected_identifiers
                )

        resilience_id: str | None = None
        try:
            self.resilience_store.verify_integrity()
            resilience = self._latest_resilience_report(timestamp)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError) as error:
            resilience = None
            data_failures += 1
            blockers.append(f"resilience authority integrity failed: {error}")
        if resilience is None:
            blockers.append("resilience report is unavailable")
        else:
            resilience_id = str(resilience["identifier"])
            sources.extend(
                (
                    resilience_id,
                    *tuple(str(item) for item in resilience["outcome_identifiers"]),
                )
            )
            evaluated_at = datetime.fromisoformat(str(resilience["evaluated_at"]))
            if timestamp - evaluated_at > self.policy.maximum_resilience_report_age:
                blockers.append("resilience report is stale")
            if not bool(resilience["release_gate_passed"]):
                blockers.append("resilience release gate is not passed")

        try:
            self.incident_store.verify_integrity()
            incidents = self.incident_store.unresolved_critical(as_of=timestamp)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError) as error:
            incidents = ()
            data_failures += 1
            blockers.append(f"incident authority integrity failed: {error}")
        incident_ids = tuple(item.incident_identifier for item in incidents)
        sources.extend(
            identifier
            for item in incidents
            for identifier in (
                item.identifier,
                item.incident_identifier,
                *item.source_identifiers,
            )
        )

        blockers = list(dict.fromkeys(blockers))
        source_ids = tuple(
            dict.fromkeys(
                (
                    f"operational-readiness-assembly:{baseline}:{timestamp.isoformat()}",
                    *sources,
                    *(f"operational-blocker:{item}" for item in blockers),
                )
            )
        )
        snapshot = OperationalReadinessSnapshot(
            identifier=f"operational-readiness:{baseline}:{timestamp.isoformat()}",
            observed_at=timestamp,
            knowledge_cutoff=timestamp,
            baseline_identifier=baseline,
            process_version=process,
            code_version=code,
            unresolved_critical_incidents=len(incidents) + len(blockers),
            data_integrity_failures=data_failures,
            reconciliation_failures=reconciliation_failures,
            source_identifiers=source_ids,
        )
        self.readiness_store.append_operational(snapshot)
        self.readiness_store.verify_integrity()
        return OperationalReadinessAssemblyResult(
            snapshot=snapshot,
            blockers=tuple(blockers),
            daily_operation_identifier=daily_id,
            slo_snapshot_identifier=slo_id,
            resilience_report_identifier=resilience_id,
            incident_identifiers=incident_ids,
            policy_version=self.policy.version,
        )

    def _latest_daily_operation(
        self,
        *,
        assessed_at: datetime,
        baseline_identifier: str,
        process_version: str,
        code_version: str,
    ) -> dict[str, Any] | None:
        with sqlite3.connect(self.daily_store.path) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "canonical_daily_operation_events" not in tables:
                return None
            claims = connection.execute(
                "SELECT * FROM canonical_daily_operation_events "
                "WHERE event_type=? AND occurred_at<=? ORDER BY sequence DESC",
                (
                    DailyOperationEventType.OPERATION_CLAIMED.value,
                    assessed_at.isoformat(),
                ),
            ).fetchall()
            selected = None
            claim_payload: Mapping[str, Any] | None = None
            for claim in claims:
                payload = json.loads(str(claim["payload_json"]))
                if (
                    payload.get("process_version") == process_version
                    and payload.get("code_version") == code_version
                    and baseline_identifier in payload.get("input_identifiers", ())
                ):
                    selected = claim
                    claim_payload = payload
                    break
            if selected is None or claim_payload is None:
                return None
            operation_identifier = str(selected["operation_identifier"])
            events = connection.execute(
                "SELECT * FROM canonical_daily_operation_events "
                "WHERE operation_identifier=? AND occurred_at<=? ORDER BY sequence",
                (operation_identifier, assessed_at.isoformat()),
            ).fetchall()
        terminals = tuple(
            row
            for row in events
            if str(row["event_type"])
            in {
                DailyOperationEventType.OPERATION_COMPLETED.value,
                DailyOperationEventType.OPERATION_FAILED.value,
            }
        )
        if not terminals:
            return {
                "operation_identifier": operation_identifier,
                "claim_event_identifier": str(selected["event_identifier"]),
                "terminal_event_identifier": f"running:{operation_identifier}",
                "terminal_at": str(selected["occurred_at"]),
                "completed": False,
                "classification": FailureClassification.INTERRUPTED.value,
                "output_identifiers": tuple(claim_payload["input_identifiers"]),
            }
        terminal = terminals[-1]
        terminal_payload = json.loads(str(terminal["payload_json"]))
        completed = (
            str(terminal["event_type"])
            == DailyOperationEventType.OPERATION_COMPLETED.value
        )
        return {
            "operation_identifier": operation_identifier,
            "claim_event_identifier": str(selected["event_identifier"]),
            "terminal_event_identifier": str(terminal["event_identifier"]),
            "terminal_at": str(terminal["occurred_at"]),
            "completed": completed,
            "classification": terminal_payload.get(
                "classification",
                "none" if completed else FailureClassification.UNKNOWN.value,
            ),
            "output_identifiers": tuple(
                terminal_payload.get(
                    "output_identifiers",
                    claim_payload["input_identifiers"],
                )
            ),
        }

    def _latest_resilience_report(
        self,
        assessed_at: datetime,
    ) -> Mapping[str, Any] | None:
        if not self.resilience_store.path.exists():
            return None
        with sqlite3.connect(self.resilience_store.path) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='resilience_events'"
            ).fetchone()
            if table is None:
                return None
            rows = connection.execute(
                "SELECT payload FROM resilience_events "
                "WHERE event_type='report' AND recorded_at<=? "
                "ORDER BY sequence DESC",
                (assessed_at.isoformat(),),
            ).fetchall()
        return None if not rows else json.loads(str(rows[0]["payload"]))


__all__ = [
    "OperationalReadinessAssembler",
    "OperationalReadinessAssemblyPolicy",
    "OperationalReadinessAssemblyResult",
]
