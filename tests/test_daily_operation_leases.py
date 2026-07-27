"""Concurrency and stale-worker tests for canonical daily operations."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from operations import (
    CANONICAL_DAILY_STAGE_ORDER,
    CallableStageRunner,
    CanonicalDailyOperationRequest,
    CanonicalDailyStage,
    CanonicalDailyStageResult,
    DailyOperationEventType,
    DailyOperationLeaseError,
    DailyOperationLeaseLost,
    DailyOperationStatus,
    LeasedCanonicalDailyOperationsOrchestrator,
    LeasedSQLiteCanonicalDailyOperationsStore,
    ReconciliationStatus,
    current_stage_fencing_context,
)

UTC = timezone.utc
BASE = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime = BASE) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class AdvancingClock:
    def __init__(self, value: datetime = BASE) -> None:
        self.value = value

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=10)
        return current


def _request() -> CanonicalDailyOperationRequest:
    return CanonicalDailyOperationRequest(
        identifier="canonical-daily:COMPOUNDING:2026-07-27",
        idempotency_key="canonical-daily:COMPOUNDING:2026-07-27:process-v1",
        operation_date=date(2026, 7, 27),
        scheduled_for=BASE - timedelta(hours=2),
        decision_timestamp=BASE - timedelta(hours=1),
        knowledge_cutoff=BASE - timedelta(hours=1, minutes=1),
        started_at=BASE - timedelta(minutes=30),
        portfolio_code="COMPOUNDING",
        process_version="process-v1",
        code_version="commit:test",
        input_identifiers=("plan:production-v2",),
    )


def _store(
    path: Path,
    *,
    worker: str,
    clock: MutableClock,
    lease_seconds: float = 10,
) -> LeasedSQLiteCanonicalDailyOperationsStore:
    return LeasedSQLiteCanonicalDailyOperationsStore(
        path,
        worker_identifier=worker,
        lease_duration=timedelta(seconds=lease_seconds),
        clock=clock,
    )


def test_active_operation_lease_excludes_second_worker(tmp_path: Path) -> None:
    clock = MutableClock()
    database = tmp_path / "daily.db"
    first = _store(database, worker="worker-a", clock=clock)
    second = _store(database, worker="worker-b", clock=clock)

    grant = first.acquire_operation(_request())

    assert grant.worker_identifier == "worker-a"
    assert grant.fencing_token == 1
    with pytest.raises(DailyOperationLeaseError, match="another active worker"):
        second.acquire_operation(_request())


def test_heartbeat_renews_operation_and_stage_leases(tmp_path: Path) -> None:
    clock = MutableClock()
    database = tmp_path / "daily.db"
    first = _store(database, worker="worker-a", clock=clock, lease_seconds=10)
    second = _store(database, worker="worker-b", clock=clock, lease_seconds=10)
    request = _request()
    first.claim(request)
    first.append(
        request=request,
        event_identifier="event:stage:started",
        event_type=DailyOperationEventType.STAGE_STARTED,
        occurred_at=clock(),
        stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
        attempt=1,
        payload={"status": "running"},
    )
    original = first.current_fencing_context(
        request.identifier,
        CanonicalDailyStage.PROVIDER_CERTIFICATION,
    )

    clock.advance(6)
    first.append(
        request=request,
        event_identifier="event:stage:heartbeat:1",
        event_type=DailyOperationEventType.STAGE_HEARTBEAT,
        occurred_at=clock(),
        stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
        attempt=1,
        payload={"detail": "still active", "output_identifiers": []},
    )
    renewed = first.current_fencing_context(
        request.identifier,
        CanonicalDailyStage.PROVIDER_CERTIFICATION,
    )

    assert renewed.operation_fencing_token == original.operation_fencing_token
    assert renewed.stage_fencing_token == original.stage_fencing_token
    assert renewed.lease_expires_at > original.lease_expires_at
    clock.advance(5)
    with pytest.raises(DailyOperationLeaseError, match="another active worker"):
        second.acquire_operation(request)


def test_expired_worker_is_fenced_after_takeover(tmp_path: Path) -> None:
    clock = MutableClock()
    database = tmp_path / "daily.db"
    stale = _store(database, worker="worker-a", clock=clock, lease_seconds=5)
    replacement = _store(database, worker="worker-b", clock=clock, lease_seconds=5)
    request = _request()
    stale.claim(request)
    stale.append(
        request=request,
        event_identifier="event:stage:started:1",
        event_type=DailyOperationEventType.STAGE_STARTED,
        occurred_at=clock(),
        stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
        attempt=1,
        payload={"status": "running"},
    )
    stale_context = stale.current_fencing_context(
        request.identifier,
        CanonicalDailyStage.PROVIDER_CERTIFICATION,
    )

    clock.advance(6)
    replacement.claim(request)
    replacement.append(
        request=request,
        event_identifier="event:stage:started:2",
        event_type=DailyOperationEventType.STAGE_STARTED,
        occurred_at=clock(),
        stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
        attempt=2,
        payload={"status": "running"},
    )
    replacement_context = replacement.current_fencing_context(
        request.identifier,
        CanonicalDailyStage.PROVIDER_CERTIFICATION,
    )

    assert replacement_context.operation_fencing_token > (
        stale_context.operation_fencing_token
    )
    assert replacement_context.stage_fencing_token > stale_context.stage_fencing_token
    with pytest.raises(DailyOperationLeaseLost, match="stale"):
        stale.append(
            request=request,
            event_identifier="event:stage:stale-completion",
            event_type=DailyOperationEventType.STAGE_COMPLETED,
            occurred_at=clock(),
            stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
            attempt=1,
            payload={"output_identifiers": ["stale:output"]},
        )

    replacement.append(
        request=request,
        event_identifier="event:stage:completed:2",
        event_type=DailyOperationEventType.STAGE_COMPLETED,
        occurred_at=clock(),
        stage=CanonicalDailyStage.PROVIDER_CERTIFICATION,
        attempt=2,
        payload={"output_identifiers": ["current:output"]},
    )
    completions = tuple(
        event
        for event in replacement.events(request.identifier)
        if event["event_type"] == DailyOperationEventType.STAGE_COMPLETED.value
    )
    assert len(completions) == 1
    assert completions[0]["payload"]["output_identifiers"] == ["current:output"]
    assert completions[0]["payload"]["lease"]["stage_fencing_token"] == (
        replacement_context.stage_fencing_token
    )


def test_fenced_orchestrator_exposes_current_context_to_every_stage(
    tmp_path: Path,
) -> None:
    lease_clock = MutableClock()
    event_clock = AdvancingClock()
    observed: list[tuple[CanonicalDailyStage, int, str]] = []
    runners = {}
    for stage in CANONICAL_DAILY_STAGE_ORDER:
        def handler(request, *, expected=stage):
            context = current_stage_fencing_context()
            observed.append(
                (
                    context.stage,
                    context.stage_fencing_token,
                    context.worker_identifier,
                )
            )
            assert context.operation_identifier == request.operation.identifier
            assert context.stage is expected
            return CanonicalDailyStageResult(
                output_identifiers=(f"authority:{expected.value}",),
                completed_at=event_clock(),
                point_in_time_cutoff=request.operation.knowledge_cutoff,
                reconciliation_status=ReconciliationStatus.RECONCILED,
                detail=f"{expected.value} completed under a fence",
            )

        runners[stage] = CallableStageRunner(f"TEST:{stage.value}", handler)
    store = _store(
        tmp_path / "daily.db",
        worker="worker-a",
        clock=lease_clock,
        lease_seconds=30,
    )
    result = LeasedCanonicalDailyOperationsOrchestrator(
        store=store,
        runners=runners,
        heartbeat_interval_seconds=1,
        clock=event_clock,
        sleeper=lambda _: None,
    ).run(_request())

    assert result.status is DailyOperationStatus.COMPLETED
    assert tuple(item[0] for item in observed) == CANONICAL_DAILY_STAGE_ORDER
    assert all(item[1] == 1 for item in observed)
    assert {item[2] for item in observed} == {"worker-a"}
    events = store.events(result.identifier)
    completions = tuple(
        item
        for item in events
        if item["event_type"] == DailyOperationEventType.STAGE_COMPLETED.value
    )
    assert len(completions) == len(CANONICAL_DAILY_STAGE_ORDER)
    assert all(
        item["payload"]["lease"]["worker_identifier"] == "worker-a"
        for item in completions
    )
    assert store.verify_integrity()
