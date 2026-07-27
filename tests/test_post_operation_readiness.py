"""Tests for readiness publication after terminal canonical daily operations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from governance import SQLiteReadinessEvidenceStore
from operations import (
    CanonicalDailyOperationsOrchestrator,
    DailyOperationStatus,
    SQLiteCanonicalDailyOperationsStore,
    SQLiteOperationalIncidentStore,
    SQLiteOperationalSLOStore,
    SQLiteResilienceExerciseStore,
)
from operations.post_operation import PostOperationReadinessPublisher
from operations.readiness import OperationalReadinessAssembler
from run_daily_operations import _request, build_parser
from tests.test_canonical_daily_operations import (
    AdvancingClock,
    _request as _base_request,
    _successful_runners,
)
from tests.test_operational_readiness_assembly import (
    BASELINE,
    CODE,
    NOW,
    PROCESS,
    _resilience,
    _slo,
)

UTC = timezone.utc


def _terminal_operation(tmp_path: Path):
    request = replace(
        _base_request(),
        process_version=PROCESS,
        code_version=CODE,
        input_identifiers=(BASELINE, "provider-plan:certified-production"),
    )
    clock = AdvancingClock()
    daily_store = SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db")
    result = CanonicalDailyOperationsOrchestrator(
        store=daily_store,
        runners=_successful_runners(clock, []),
        clock=clock,
        sleeper=lambda _: None,
    ).run(request)
    return request, result, daily_store


def _publisher(
    tmp_path: Path,
    daily_store: SQLiteCanonicalDailyOperationsStore,
    *,
    complete_sources: bool,
) -> tuple[PostOperationReadinessPublisher, SQLiteReadinessEvidenceStore]:
    slo_store = SQLiteOperationalSLOStore(tmp_path / "slo.db")
    resilience_store = SQLiteResilienceExerciseStore(tmp_path / "resilience.db")
    if complete_sources:
        _slo(slo_store)
        _resilience(resilience_store)
    readiness_store = SQLiteReadinessEvidenceStore(tmp_path / "readiness.db")
    publisher = PostOperationReadinessPublisher(
        assembler=OperationalReadinessAssembler(
            daily_store=daily_store,
            slo_store=slo_store,
            resilience_store=resilience_store,
            incident_store=SQLiteOperationalIncidentStore(
                tmp_path / "incidents.db"
            ),
            readiness_store=readiness_store,
        ),
        baseline_identifier=BASELINE,
    )
    return publisher, readiness_store


def test_completed_operation_publishes_clean_version_matched_snapshot(
    tmp_path: Path,
) -> None:
    request, result, daily_store = _terminal_operation(tmp_path)
    publisher, readiness_store = _publisher(
        tmp_path,
        daily_store,
        complete_sources=True,
    )

    publication = publisher.publish(
        request,
        result,
        published_at=NOW,
    )

    assert result.status is DailyOperationStatus.COMPLETED
    assert publication.operation_identifier == request.identifier
    assert publication.operation_status is DailyOperationStatus.COMPLETED
    assert publication.baseline_identifier == BASELINE
    assert publication.clean is True
    assert publication.assembly.blockers == ()
    assert publication.assembly.snapshot.process_version == PROCESS
    assert publication.assembly.snapshot.code_version == CODE
    assert readiness_store.latest_operational(assessed_at=NOW) == (
        publication.assembly.snapshot
    )
    assert publication.to_dict()["real_money_authorized"] is False


def test_missing_runtime_sources_publish_blockers_without_rewriting_operation(
    tmp_path: Path,
) -> None:
    request, result, daily_store = _terminal_operation(tmp_path)
    publisher, readiness_store = _publisher(
        tmp_path,
        daily_store,
        complete_sources=False,
    )

    publication = publisher.publish(
        request,
        result,
        published_at=NOW,
    )

    assert result.status is DailyOperationStatus.COMPLETED
    assert publication.operation_status is DailyOperationStatus.COMPLETED
    assert publication.clean is False
    assert set(publication.assembly.blockers) == {
        "operational SLO snapshot is unavailable",
        "resilience report is unavailable",
    }
    assert publication.assembly.snapshot.unresolved_critical_incidents == 2
    assert readiness_store.latest_operational(assessed_at=NOW) == (
        publication.assembly.snapshot
    )


def test_publisher_rejects_baseline_not_bound_into_operation_claim(
    tmp_path: Path,
) -> None:
    request, result, daily_store = _terminal_operation(tmp_path)
    request_without_baseline = replace(
        request,
        input_identifiers=("provider-plan:certified-production",),
    )
    publisher, _ = _publisher(
        tmp_path,
        daily_store,
        complete_sources=True,
    )

    with pytest.raises(ValueError, match="immutable daily-operation input"):
        publisher.publish(
            request_without_baseline,
            result,
            published_at=NOW,
        )


def test_daily_request_binds_plan_and_test_baseline_as_inputs() -> None:
    parser = build_parser()
    args = parser.parse_args(
        (
            "--plan",
            "unused.json",
            "--test-baseline-identifier",
            BASELINE,
            "--process-version",
            PROCESS,
            "--code-version",
            CODE,
            "--operation-timezone",
            "UTC",
            "--operation-hour",
            "7",
        )
    )
    plan = {
        "schema_version": "canonical-daily-operations.v1",
        "identifier": "test-plan-v1",
        "stages": {},
    }

    request = _request(
        args,
        plan=plan,
        now=datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
    )

    assert request.input_identifiers == (
        "plan:test-plan-v1",
        BASELINE,
    )
    assert request.process_version == PROCESS
    assert request.code_version == CODE
