from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations.persistent_alpaca_paper_history import PersistentAlpacaPaperHistoryClient


class _FakeAlpaca:
    def __init__(self) -> None:
        self.history_calls = 0

    def historical_bars(self, symbols, *, start, end, timeframe="1Day"):
        self.history_calls += 1
        return {
            symbol: [
                {
                    "t": (end - timedelta(days=2)).isoformat(),
                    "c": 100.0,
                    "v": 1000.0,
                },
                {
                    "t": (end - timedelta(days=1)).isoformat(),
                    "c": 101.0,
                    "v": 1100.0,
                },
            ]
            for symbol in symbols
        }


def test_recent_daily_history_is_reused_without_provider_redownload(tmp_path) -> None:
    as_of = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)
    underlying = _FakeAlpaca()
    client = PersistentAlpacaPaperHistoryClient(
        underlying,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    first = client.historical_bars(
        ("SPY",),
        start=as_of - timedelta(days=30),
        end=as_of,
        timeframe="1Day",
    )
    second = client.historical_bars(
        ("SPY",),
        start=as_of - timedelta(days=30),
        end=as_of,
        timeframe="1Day",
    )

    assert underlying.history_calls == 1
    assert second == first
    assert tuple(second) == ("SPY",)
