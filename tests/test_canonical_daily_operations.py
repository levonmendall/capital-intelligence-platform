"""Integration and fail-closed tests for canonical daily operations."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations import (
    CANONICAL_DAILY_STAGE_ORDER,
    CallableStageRunner,
    CanonicalDailyOperationRequest,
    CanonicalDailyOperationsOrchestrator,
    CanonicalDailyStage,
    CanonicalDailyStageResult,
    DailyOperationEventType,
    DailyOperationStatus,
    FailureClassification,
    ReconciliationStatus,
    SQLiteCanonicalDailyOperationsStore,
    StageExecutionError,
    StageRetryPolicy,
)

UTC = timezone.utc
BASE = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class AdvancingClock:
    def __init__(self, start: datetime = BASE) -> None:
        self.current = start

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def _request() -> CanonicalDailyOperationRequest:
    return CanonicalDailyOperationRequest(
        identifier="canonical-daily:COMPOUNDING:2026-07-27",
        idempotency_key=(
            "canonical-daily:COMPOUNDING:2026-07-27:"
            "Capital Intelligence Investment Process v1.0"
        ),
        operation_date=date(2026, 7, 27),
        scheduled_for=BASE - timedelta(hours=2),
        decision_timestamp=BASE - timedelta(hours=1),
        knowledge_cutoff=BASE - timedelta(hours=1, minutes=1),
        started_at=BASE - timedelta(minutes=30),
        portfolio_code="COMPOUNDING",
        process_version="Capital Intelligence Investment Process v1.0",
        code_version="commit:test",
        input_identifiers=("provider-plan:certified-production",),
    )


def _successful_runners(clock: AdvancingClock, calls: list[tuple]) -> dict:
    runners = {}
    for stage in CANONICAL_DAILY_STAGE_ORDER:
        def handler(request, *, expected_stage=stage):
            calls.append(
                (
                    expected_stage,
                    request.attempt,
                    request.input_identifiers,
                    request.idempotency_key,
                )
            )
            request.heartbeat(
                f"{expected_stage.value} remains active",
                request.input_identifiers,
            )
            return CanonicalDailyStageResult(
                output_identifiers=(
                    f"authority:{expected_stage.value}:2026-07-27",
                ),
                completed_at=clock(),
                point_in_time_cutoff=request.operation.knowledge_cutoff,
                reconciliation_status=ReconciliationStatus.RECONCILED,
                detail=f"{expected_stage.value} completed",
            )

        runners[stage] = CallableStageRunner(
            f"TEST:{stage.value}",
            handler,
        )
    return runners


def test_complete_daily_operation_is_ordered_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock()
    calls: list[tuple] = []
    store = SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db")
    orchestrator = CanonicalDailyOperationsOrchestrator(
        store=store,
        runners=_successful_runners(clock, calls),
        clock=clock,
        sleeper=lambda _: None,
    )

    result = orchestrator.run(_request())

    assert result.status is DailyOperationStatus.COMPLETED
    assert result.completed_stages == CANONICAL_DAILY_STAGE_ORDER
    assert result.failed_stage is None
    assert result.output_identifiers == (
        "authority:slo_assessment:2026-07-27",
    )
    assert tuple(item[0] for item in calls) == CANONICAL_DAILY_STAGE_ORDER
    assert calls[0][2] == ("provider-plan:certified-production",)
    for previous, current in zip(calls, calls[1:]):
        assert current[2] == (
            f"authority:{previous[0].value}:2026-07-27",
        )
    assert all(
        item[3].endswith(f":{item[0].value}") for item in calls
    )

    events = store.events(result.identifier)
    event_types = tuple(item["event_type"] for item in events)
    assert event_types.count(DailyOperationEventType.STAGE_STARTED.value) == len(
        CANONICAL_DAILY_STAGE_ORDER
    )
    assert event_types.count(DailyOperationEventType.STAGE_COMPLETED.value) == len(
        CANONICAL_DAILY_STAGE_ORDER
    )
    assert event_types.count(DailyOperationEventType.STAGE_HEARTBEAT.value) >= 2 * len(
        CANONICAL_DAILY_STAGE_ORDER
    )
    assert event_types[-1] == DailyOperationEventType.OPERATION_COMPLETED.value
    assert store.verify_integrity()

    replay = orchestrator.run(_request())

    assert replay == result
    assert len(calls) == len(CANONICAL_DAILY_STAGE_ORDER)


def test_failed_screening_blocks_every_downstream_investment_stage(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock()
    calls: list[CanonicalDailyStage] = []
    runners = _successful_runners(clock, [])

    def screening_failure(request):
        calls.append(request.stage)
        raise StageExecutionError(
            "screening publication did not reconcile complete universe coverage",
            classification=FailureClassification.DATA_QUALITY,
            retryable=False,
        )

    runners[CanonicalDailyStage.COMPLETE_UNIVERSE_SCREENING] = CallableStageRunner(
        "FAIL:screening",
        screening_failure,
    )
    for stage in CANONICAL_DAILY_STAGE_ORDER:
        if stage is CanonicalDailyStage.COMPLETE_UNIVERSE_SCREENING:
            continue
        original = runners[stage]

        def wrapped(request, *, original_runner=original, expected_stage=stage):
            calls.append(expected_stage)
            return original_runner.run(request)

        runners[stage] = CallableStageRunner(f"WRAPPED:{stage.value}", wrapped)

    store = SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db")
    result = CanonicalDailyOperationsOrchestrator(
        store=store,
        runners=runners,
        clock=clock,
        sleeper=lambda _: None,
    ).run(_request())

    assert result.status is DailyOperationStatus.FAILED
    assert result.failed_stage is CanonicalDailyStage.COMPLETE_UNIVERSE_SCREENING
    assert calls == [
        CanonicalDailyStage.PROVIDER_CERTIFICATION,
        CanonicalDailyStage.SECURITY_MASTER_ACTIVATION,
        CanonicalDailyStage.ELIGIBLE_UNIVERSE_PUBLICATION,
        CanonicalDailyStage.COMPLETE_UNIVERSE_SCREENING,
    ]
    events = store.events(result.identifier)
    blocked = tuple(
        CanonicalDailyStage(item["stage"])
        for item in events
        if item["event_type"] == DailyOperationEventType.STAGE_BLOCKED.value
    )
    failed_index = CANONICAL_DAILY_STAGE_ORDER.index(
        CanonicalDailyStage.COMPLETE_UNIVERSE_SCREENING
    )
    assert blocked == CANONICAL_DAILY_STAGE_ORDER[failed_index + 1 :]
    assert not any(
        item["event_type"] == DailyOperationEventType.STAGE_STARTED.value
        and item["stage"] == CanonicalDailyStage.CANONICAL_CIO_CYCLE.value
        for item in events
    )
    assert store.verify_integrity()


def test_transient_provider_failure_retries_with_same_stage_key(
    tmp_path: Path,
) -> None:
    clock = AdvancingClock()
    calls: list[tuple] = []
    sleeps: list[float] = []
    runners = _successful_runners(clock, calls)
    provider_attempts = 0

    def provider(request):
        nonlocal provider_attempts
        provider_attempts += 1
        calls.append(
            (
                request.stage,
                request.attempt,
                request.input_identifiers,
                request.idempotency_key,
            )
        )
        if provider_attempts == 1:
            raise StageExecutionError(
                "licensed provider timed out",
                classification=FailureClassification.TRANSIENT_PROVIDER,
                retryable=True,
            )
        return CanonicalDailyStageResult(
            output_identifiers=("provider-certification:approved",),
            completed_at=clock(),
            point_in_time_cutoff=request.operation.knowledge_cutoff,
            reconciliation_status=ReconciliationStatus.RECONCILED,
            detail="provider freshness and certification verified",
        )

    runners[CanonicalDailyStage.PROVIDER_CERTIFICATION] = CallableStageRunner(
        "RETRY:provider",
        provider,
    )
    policies = {
        stage: StageRetryPolicy(
            maximum_attempts=3,
            initial_backoff_seconds=2,
            multiplier=2,
            maximum_backoff_seconds=10,
        )
        for stage in CANONICAL_DAILY_STAGE_ORDER
    }
    store = SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db")
    result = CanonicalDailyOperationsOrchestrator(
        store=store,
        runners=runners,
        retry_policies=policies,
        clock=clock,
        sleeper=sleeps.append,
    ).run(_request())

    assert result.status is DailyOperationStatus.COMPLETED
    assert provider_attempts == 2
    assert sleeps == [2]
    provider_calls = tuple(
        item for item in calls if item[0] is CanonicalDailyStage.PROVIDER_CERTIFICATION
    )
    assert tuple(item[1] for item in provider_calls) == (1, 2)
    assert provider_calls[0][3] == provider_calls[1][3]
    events = store.events(result.identifier)
    provider_failures = tuple(
        item
        for item in events
        if item["event_type"] == DailyOperationEventType.STAGE_FAILED.value
        and item["stage"] == CanonicalDailyStage.PROVIDER_CERTIFICATION.value
    )
    assert len(provider_failures) == 1
    assert provider_failures[0]["payload"]["retryable"] is True


def test_mismatched_point_in_time_cutoff_fails_closed(tmp_path: Path) -> None:
    clock = AdvancingClock()
    calls: list[tuple] = []
    runners = _successful_runners(clock, calls)

    def mismatched_cutoff(request):
        return CanonicalDailyStageResult(
            output_identifiers=("provider-certification:future",),
            completed_at=clock(),
            point_in_time_cutoff=(
                request.operation.knowledge_cutoff + timedelta(seconds=1)
            ),
            reconciliation_status=ReconciliationStatus.RECONCILED,
            detail="invalid future cutoff",
        )

    runners[CanonicalDailyStage.PROVIDER_CERTIFICATION] = CallableStageRunner(
        "INVALID:cutoff",
        mismatched_cutoff,
    )
    result = CanonicalDailyOperationsOrchestrator(
        store=SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db"),
        runners=runners,
        clock=clock,
        sleeper=lambda _: None,
    ).run(_request())

    assert result.status is DailyOperationStatus.FAILED
    assert result.failed_stage is CanonicalDailyStage.PROVIDER_CERTIFICATION
    assert result.completed_stages == ()


def test_operation_history_and_claims_are_append_only(tmp_path: Path) -> None:
    clock = AdvancingClock()
    store = SQLiteCanonicalDailyOperationsStore(tmp_path / "daily.db")
    orchestrator = CanonicalDailyOperationsOrchestrator(
        store=store,
        runners=_successful_runners(clock, []),
        clock=clock,
        sleeper=lambda _: None,
    )
    orchestrator.run(_request())

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE canonical_daily_operation_events SET payload_json = '{}' "
                "WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM canonical_daily_operation_claims"
            )
