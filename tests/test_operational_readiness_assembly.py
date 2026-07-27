"""Integration tests for repository-assembled operational readiness evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from governance import SQLiteReadinessEvidenceStore
from operations import (
    CanonicalDailyOperationRequest,
    DailyOperationEventType,
    FailureClassification,
    OperationalIncidentEvent,
    OperationalIncidentSeverity,
    OperationalIncidentState,
    OperationalReadinessAssembler,
    OperationalReadinessAssemblyPolicy,
    OperationalSLOComponent,
    OperationalSLOName,
    OperationalSLOSnapshot,
    OperationalSLOStatus,
    ResilienceExercisePolicy,
    ResilienceExerciseReport,
    SQLiteCanonicalDailyOperationsStore,
    SQLiteOperationalIncidentStore,
    SQLiteOperationalSLOStore,
    SQLiteResilienceExerciseStore,
)
from run_operational_readiness import main as readiness_main

UTC = timezone.utc
NOW = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)
BASELINE = "test-baseline:multi-asset-alpha.1"
PROCESS = "capital-intelligence-investment-process.v1-test"
CODE = "commit:operational-test"


def _request(
    *,
    identifier: str = "canonical-daily:COMPOUNDING:2026-07-27",
    baseline: str = BASELINE,
    process: str = PROCESS,
    code: str = CODE,
) -> CanonicalDailyOperationRequest:
    return CanonicalDailyOperationRequest(
        identifier=identifier,
        idempotency_key=f"{identifier}:{process}",
        operation_date=date(2026, 7, 27),
        scheduled_for=NOW - timedelta(hours=2),
        decision_timestamp=NOW - timedelta(hours=2),
        knowledge_cutoff=NOW - timedelta(hours=2, seconds=1),
        started_at=NOW - timedelta(hours=1, minutes=30),
        portfolio_code="COMPOUNDING",
        process_version=process,
        code_version=code,
        input_identifiers=(baseline, "provider-certification:test"),
    )


def _complete_daily(
    store: SQLiteCanonicalDailyOperationsStore,
    *,
    request: CanonicalDailyOperationRequest | None = None,
    occurred_at: datetime = NOW - timedelta(hours=1),
) -> CanonicalDailyOperationRequest:
    operation = request or _request()
    store.claim(operation)
    store.append(
        request=operation,
        event_identifier=f"event:{operation.identifier}:completed",
        event_type=DailyOperationEventType.OPERATION_COMPLETED,
        occurred_at=occurred_at,
        payload={
            "status": "completed",
            "output_identifiers": ("slo-assessment:test",),
        },
    )
    return operation


def _fail_daily(
    store: SQLiteCanonicalDailyOperationsStore,
    classification: FailureClassification,
) -> CanonicalDailyOperationRequest:
    operation = _request()
    store.claim(operation)
    store.append(
        request=operation,
        event_identifier=f"event:{operation.identifier}:failed",
        event_type=DailyOperationEventType.OPERATION_FAILED,
        occurred_at=NOW - timedelta(hours=1),
        payload={
            "failed_stage": "complete_universe_screening",
            "classification": classification.value,
            "detail": "synthetic failure",
            "output_identifiers": (BASELINE,),
        },
    )
    return operation


def _slo(
    store: SQLiteOperationalSLOStore,
    *,
    ready: bool = True,
    evaluated_at: datetime = NOW - timedelta(minutes=30),
) -> OperationalSLOSnapshot:
    status = OperationalSLOStatus.MET if ready else OperationalSLOStatus.BREACHED
    snapshot = OperationalSLOSnapshot(
        identifier=f"operational-slo:{evaluated_at.isoformat()}:{status.value}",
        evaluated_at=evaluated_at,
        policy_version="operational-slo.v1",
        ready=ready,
        components=(
            OperationalSLOComponent(
                name=OperationalSLOName.SECURITY_MASTER_FRESHNESS,
                status=status,
                required=True,
                objective="certified provider and security master are current",
                detail="synthetic acceptance observation",
                observed_at=evaluated_at,
                affected_identifiers=("security-master:test",),
            ),
        ),
    )
    store.append_snapshot(snapshot)
    return snapshot


def _resilience(
    store: SQLiteResilienceExerciseStore,
    *,
    passed: bool = True,
    evaluated_at: datetime = NOW - timedelta(days=1),
) -> ResilienceExerciseReport:
    policy = ResilienceExercisePolicy()
    outcome_ids = tuple(
        f"resilience-outcome:{item.value}" for item in policy.required_kinds
    )
    report = ResilienceExerciseReport(
        identifier=f"resilience-report:{evaluated_at.isoformat()}:{passed}",
        evaluated_at=evaluated_at,
        policy=policy,
        scenario_count=len(outcome_ids),
        passed_count=len(outcome_ids) if passed else len(outcome_ids) - 1,
        failed_count=0 if passed else 1,
        blocked_count=0,
        missing_required_kinds=() if passed else (policy.required_kinds[-1],),
        blockers=() if passed else ("model rollback exercise failed",),
        outcome_identifiers=outcome_ids,
        release_gate_passed=passed,
    )
    store.append_report(report, recorded_at=evaluated_at)
    return report


def _incident(
    *,
    state: OperationalIncidentState = OperationalIncidentState.OPEN,
    occurred_at: datetime = NOW - timedelta(hours=1),
) -> OperationalIncidentEvent:
    return OperationalIncidentEvent(
        identifier=f"incident-event:provider-outage:{state.value}",
        incident_identifier="incident:provider-outage:1",
        severity=OperationalIncidentSeverity.CRITICAL,
        state=state,
        occurred_at=occurred_at,
        detected_at=NOW - timedelta(hours=2),
        classification="provider_outage",
        summary=(
            "Licensed provider outage remains unresolved"
            if state is OperationalIncidentState.OPEN
            else "Licensed provider service restored and reconciled"
        ),
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
        source_identifiers=("provider-health:test",),
        resolution_identifier=(
            None
            if state is OperationalIncidentState.OPEN
            else "resolution:provider-outage:1"
        ),
    )


def _stores(tmp_path: Path):
    return (
        SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db"),
        SQLiteOperationalSLOStore(tmp_path / "slo.db"),
        SQLiteResilienceExerciseStore(tmp_path / "resilience.db"),
        SQLiteOperationalIncidentStore(tmp_path / "incidents.db"),
        SQLiteReadinessEvidenceStore(tmp_path / "readiness.db"),
    )


def _assembler(tmp_path: Path):
    stores = _stores(tmp_path)
    return (
        OperationalReadinessAssembler(
            daily_store=stores[0],
            slo_store=stores[1],
            resilience_store=stores[2],
            incident_store=stores[3],
            readiness_store=stores[4],
        ),
        stores,
    )


def test_clean_runtime_authorities_produce_zero_failure_operational_snapshot(
    tmp_path: Path,
) -> None:
    assembler, stores = _assembler(tmp_path)
    operation = _complete_daily(stores[0])
    slo = _slo(stores[1])
    resilience = _resilience(stores[2])

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert result.blockers == ()
    assert result.daily_operation_identifier == operation.identifier
    assert result.slo_snapshot_identifier == slo.identifier
    assert result.resilience_report_identifier == resilience.identifier
    assert result.incident_identifiers == ()
    assert result.snapshot.unresolved_critical_incidents == 0
    assert result.snapshot.data_integrity_failures == 0
    assert result.snapshot.reconciliation_failures == 0
    persisted = stores[4].latest_operational(assessed_at=NOW)
    assert persisted == result.snapshot


def test_daily_operation_must_match_baseline_process_and_code(tmp_path: Path) -> None:
    assembler, stores = _assembler(tmp_path)
    _complete_daily(
        stores[0],
        request=_request(
            identifier="canonical-daily:wrong-baseline",
            baseline="test-baseline:other",
        ),
    )
    _slo(stores[1])
    _resilience(stores[2])

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert result.daily_operation_identifier is None
    assert "matching canonical daily operation is unavailable" in result.blockers
    assert result.snapshot.unresolved_critical_incidents >= 1


@pytest.mark.parametrize(
    ("classification", "data_failures", "reconciliation_failures"),
    (
        (FailureClassification.INTEGRITY, 1, 0),
        (FailureClassification.DATA_QUALITY, 1, 0),
        (FailureClassification.RECONCILIATION, 0, 1),
    ),
)
def test_failed_daily_operation_preserves_failure_classification(
    tmp_path: Path,
    classification: FailureClassification,
    data_failures: int,
    reconciliation_failures: int,
) -> None:
    assembler, stores = _assembler(tmp_path)
    _fail_daily(stores[0], classification)
    _slo(stores[1])
    _resilience(stores[2])

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert any(classification.value in item for item in result.blockers)
    assert result.snapshot.data_integrity_failures == data_failures
    assert result.snapshot.reconciliation_failures == reconciliation_failures
    assert result.snapshot.unresolved_critical_incidents >= 1


def test_stale_or_breached_slo_remains_a_current_operational_blocker(
    tmp_path: Path,
) -> None:
    assembler, stores = _assembler(tmp_path)
    _complete_daily(stores[0])
    _slo(
        stores[1],
        ready=False,
        evaluated_at=NOW - timedelta(hours=25),
    )
    _resilience(stores[2])

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert "operational SLO snapshot is stale" in result.blockers
    assert "operational SLO snapshot is not ready" in result.blockers
    assert "security-master:test" in result.snapshot.source_identifiers


def test_failed_or_stale_resilience_report_blocks_snapshot(tmp_path: Path) -> None:
    assembler, stores = _assembler(tmp_path)
    _complete_daily(stores[0])
    _slo(stores[1])
    report = _resilience(
        stores[2],
        passed=False,
        evaluated_at=NOW - timedelta(days=31),
    )

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert result.resilience_report_identifier == report.identifier
    assert "resilience report is stale" in result.blockers
    assert "resilience release gate is not passed" in result.blockers


def test_open_critical_incident_blocks_until_explicit_resolution(tmp_path: Path) -> None:
    assembler, stores = _assembler(tmp_path)
    _complete_daily(stores[0])
    _slo(stores[1])
    _resilience(stores[2])
    open_event = _incident()
    stores[3].append(open_event)

    blocked = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )
    assert blocked.incident_identifiers == (open_event.incident_identifier,)
    assert blocked.snapshot.unresolved_critical_incidents == 1

    stores[3].append(
        _incident(
            state=OperationalIncidentState.RESOLVED,
            occurred_at=NOW + timedelta(minutes=1),
        )
    )
    clean = assembler.assemble(
        assessed_at=NOW + timedelta(minutes=2),
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )
    assert clean.incident_identifiers == ()
    assert clean.snapshot.unresolved_critical_incidents == 0


def test_missing_all_runtime_sources_persists_fail_closed_snapshot(
    tmp_path: Path,
) -> None:
    assembler, stores = _assembler(tmp_path)

    result = assembler.assemble(
        assessed_at=NOW,
        baseline_identifier=BASELINE,
        process_version=PROCESS,
        code_version=CODE,
    )

    assert set(result.blockers) == {
        "matching canonical daily operation is unavailable",
        "operational SLO snapshot is unavailable",
        "resilience report is unavailable",
    }
    assert result.snapshot.unresolved_critical_incidents == 3
    assert stores[4].latest_operational(assessed_at=NOW) == result.snapshot


def test_incident_history_is_idempotent_append_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    store = SQLiteOperationalIncidentStore(tmp_path / "incidents.db")
    event = _incident()

    assert store.append(event) == 1
    assert store.append(event) == 1
    assert store.unresolved_critical(as_of=NOW) == (event,)
    assert store.verify_integrity()

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE operational_incident_events "
                "SET payload_json='{}' WHERE sequence=1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM operational_incident_events")


def test_operational_readiness_cli_assembles_from_persisted_runtime_stores(
    tmp_path: Path,
    capsys,
) -> None:
    daily, slo_store, resilience_store, _, _ = _stores(tmp_path)
    _complete_daily(daily)
    _slo(slo_store)
    _resilience(resilience_store)

    exit_code = readiness_main(
        (
            "--baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--assessed-at",
            NOW.isoformat(),
            "--daily-operations-database",
            str(daily.path),
            "--slo-database",
            str(slo_store.path),
            "--resilience-database",
            str(resilience_store.path),
            "--incident-database",
            str(tmp_path / "incidents.db"),
            "--readiness-evidence-database",
            str(tmp_path / "readiness.db"),
            "--require-clean",
        )
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "clean"
    assert output["blockers"] == []
    assert output["snapshot"]["unresolved_critical_incidents"] == 0
    assert output["real_money_authorized"] is False
