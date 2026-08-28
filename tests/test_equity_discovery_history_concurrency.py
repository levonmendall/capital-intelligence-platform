from __future__ import annotations

import threading
from datetime import datetime, timezone

from operations.equity_discovery import (
    EquityDiscoveryPolicy,
    _deep_history_batches,
    _render_deep_history_workers,
)


class _BlockingHistoryClient:
    def __init__(self) -> None:
        self._barrier = threading.Barrier(2)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def historical_bars(self, symbols, **_kwargs):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self._barrier.wait(timeout=2.0)
            return {symbol: () for symbol in symbols}
        finally:
            with self._lock:
                self.active -= 1


def test_render_equity_history_workers_are_bounded(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    assert _render_deep_history_workers() == 2

    monkeypatch.delenv("RENDER", raising=False)
    assert _render_deep_history_workers() == 1


def test_deep_history_batches_overlap_two_fetches_but_yield_original_order() -> None:
    client = _BlockingHistoryClient()
    policy = EquityDiscoveryPolicy(deep_history_batch_size=1)
    timestamp = datetime(2026, 8, 28, 12, 12, 28, tzinfo=timezone.utc)

    results = list(
        _deep_history_batches(
            alpaca=client,
            shortlist=("DDD", "CCC", "BBB", "AAA"),
            timestamp=timestamp,
            policy=policy,
            workers=2,
        )
    )

    assert [batch for batch, _bars in results] == [
        ("DDD",),
        ("CCC",),
        ("BBB",),
        ("AAA",),
    ]
    assert client.max_active == 2
