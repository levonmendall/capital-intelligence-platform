from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from delivery.canonical_scheduler import ScheduledCanonicalCIOWorker
from delivery.store import SQLiteAlertStore


class _Executor:
    def __init__(self) -> None:
        self.observed = []

    def run(self, *, as_of):
        self.observed.append(as_of)
        return SimpleNamespace(
            briefing=SimpleNamespace(identifier="briefing:certified-publication")
        )


def test_worker_uses_certified_publication_time_inside_scheduled_market_date(
    tmp_path,
) -> None:
    now = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    decision_as_of = datetime(2026, 7, 29, 20, 44, tzinfo=timezone.utc)
    executor = _Executor()
    worker = ScheduledCanonicalCIOWorker(
        executor,
        SQLiteAlertStore(tmp_path / "alerts.db"),
        clock=lambda: now,
    )

    result = worker.run_due(now=now, decision_as_of=decision_as_of)

    assert result.status == "completed"
    assert executor.observed == [decision_as_of]
    assert result.snapshot_identifier == "briefing:certified-publication"


def test_worker_rejects_a_decision_timestamp_outside_the_scheduled_date(
    tmp_path,
) -> None:
    now = datetime(2026, 7, 30, 20, 5, tzinfo=timezone.utc)
    prior_market_date = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    worker = ScheduledCanonicalCIOWorker(
        _Executor(),
        SQLiteAlertStore(tmp_path / "alerts.db"),
        clock=lambda: now,
    )

    with pytest.raises(ValueError, match="scheduled market date"):
        worker.run_due(now=now, decision_as_of=prior_market_date)
