from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from delivery.canonical_scheduler import ScheduledCanonicalCIOWorker
from delivery.store import SQLiteAlertStore


class _FailingExecutor:
    def run(self, *, as_of: datetime):
        del as_of
        raise RuntimeError("canonical CIO test failure")


def test_failed_cycle_replays_persisted_error_while_retry_is_not_due(
    tmp_path: Path,
) -> None:
    first_pass_at = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    clock_values = iter((first_pass_at, first_pass_at))
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    worker = ScheduledCanonicalCIOWorker(
        _FailingExecutor(),
        store,
        schedule_timezone="UTC",
        schedule_hour=0,
        clock=lambda: next(clock_values),
        cycle_retry_delay=timedelta(minutes=15),
    )

    first = worker.run_due(now=first_pass_at)
    second = worker.run_due(now=first_pass_at + timedelta(minutes=1))

    assert first.status == "failed"
    assert first.detail == "canonical CIO test failure"
    assert second.status == "failed"
    assert second.detail == "canonical CIO test failure"
