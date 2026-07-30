from datetime import datetime, timezone
from types import SimpleNamespace

from delivery.canonical_scheduler import ScheduledCanonicalCIOWorker
from delivery.store import SQLiteAlertStore


class _Executor:
    def __init__(self) -> None:
        self.calls = []

    def run(self, *, as_of):
        self.calls.append(as_of)
        return SimpleNamespace(
            briefing=SimpleNamespace(identifier=f"briefing:{as_of.isoformat()}")
        )


def test_three_scheduled_reviews_are_independently_idempotent(tmp_path) -> None:
    executor = _Executor()
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    worker = ScheduledCanonicalCIOWorker(
        executor,
        store,
        schedule_timezone="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
    )

    opening = datetime(2026, 7, 30, 14, 5, tzinfo=timezone.utc)
    midday = datetime(2026, 7, 30, 17, 5, tzinfo=timezone.utc)
    preclose = datetime(2026, 7, 30, 19, 50, tzinfo=timezone.utc)

    first = worker.run_due(now=opening)
    second = worker.run_due(now=midday)
    third = worker.run_due(now=preclose)

    assert first.status == "completed"
    assert first.cycle_key == "canonical-cio:America/Los_Angeles:2026-07-30"
    assert second.status == "completed"
    assert second.cycle_key.endswith(":scheduled:1000")
    assert third.status == "completed"
    assert third.cycle_key.endswith(":scheduled:1245")
    assert len(executor.calls) == 3

    repeated = worker.run_due(now=preclose)
    assert repeated.status == "completed"
    assert len(executor.calls) == 3


def test_material_event_review_has_separate_durable_key(tmp_path) -> None:
    executor = _Executor()
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    worker = ScheduledCanonicalCIOWorker(
        executor,
        store,
        schedule_timezone="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
    )
    now = datetime(2026, 7, 30, 18, 20, tzinfo=timezone.utc)

    event = worker.run_triggered("material-20260730-1120-abc123", now=now)
    repeated = worker.run_triggered("material-20260730-1120-abc123", now=now)

    assert event.status == "completed"
    assert ":event:material-20260730-1120-abc123" in event.cycle_key
    assert repeated.status == "completed"
    assert len(executor.calls) == 1


def test_worker_reports_when_slot_needs_new_context(tmp_path) -> None:
    executor = _Executor()
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    worker = ScheduledCanonicalCIOWorker(
        executor,
        store,
        schedule_timezone="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
    )
    now = datetime(2026, 7, 30, 17, 1, tzinfo=timezone.utc)

    assert worker.needs_scheduled_cycle(now)
    worker.run_due(now=now)
    assert not worker.needs_scheduled_cycle(now)
