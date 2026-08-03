"""Broad discovery stays complete while deep evidence remains resource-bounded."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from operations.equity_discovery import EquityDiscoveryPolicy, discover_us_equities


AS_OF = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")


class _Client:
    def __init__(self) -> None:
        self.snapshot_calls: list[tuple[str, ...]] = []
        self.history_calls: list[tuple[str, ...]] = []

    def assets(self, **_kwargs):
        return tuple(
            {
                "symbol": symbol,
                "name": f"{symbol} Operating Company",
                "exchange": "NASDAQ",
                "status": "active",
                "tradable": True,
                "fractionable": True,
                "class": "us_equity",
            }
            for symbol in SYMBOLS
        )

    def snapshots(self, symbols):
        batch = tuple(symbols)
        self.snapshot_calls.append(batch)
        rank = {symbol: len(SYMBOLS) - index for index, symbol in enumerate(SYMBOLS)}
        return {
            symbol: {
                "dailyBar": {
                    "c": 100.0 + rank[symbol],
                    "v": 2_000_000,
                    "t": "2026-08-03T17:55:00Z",
                },
                "prevDailyBar": {"c": 100.0},
            }
            for symbol in batch
        }

    def historical_bars(self, symbols, **_kwargs):
        batch = tuple(symbols)
        self.history_calls.append(batch)
        growth = {
            "AAA": 1.0018,
            "BBB": 1.0015,
            "CCC": 1.0012,
            "DDD": 1.0009,
            "EEE": 1.0006,
            "FFF": 1.0003,
            "VTI": 1.0005,
        }
        start = AS_OF - timedelta(days=350)
        return {
            symbol: tuple(
                {
                    "t": (start + timedelta(days=index)).isoformat(),
                    "c": 50.0 * (growth[symbol] ** index),
                    "v": 2_000_000.0,
                }
                for index in range(300)
            )
            for symbol in batch
        }


class _SEC:
    def fetch_security_master(self):
        instruments = tuple(
            SimpleNamespace(
                instrument_id=f"sec:{symbol.lower()}",
                issuer_id=f"SEC:CIK:{index:010d}",
                name=f"{symbol} Operating Company",
            )
            for index, symbol in enumerate(SYMBOLS, start=1)
        )
        listings = tuple(
            SimpleNamespace(
                instrument_id=f"sec:{symbol.lower()}",
                symbol=symbol,
                venue="NASDAQ",
            )
            for symbol in SYMBOLS
        )
        return SimpleNamespace(
            instruments=instruments,
            listings=listings,
            retrieved_at=AS_OF,
        )


def test_broad_screen_advances_only_bounded_decision_evidence_cohort() -> None:
    client = _Client()
    policy = EquityDiscoveryPolicy(
        deep_shortlist_count=3,
        selected_candidate_count=2,
        deep_history_batch_size=2,
        minimum_history_bars=252,
    )

    result = discover_us_equities(
        as_of=AS_OF,
        held_symbols=("FFF",),
        client=client,
        sec_provider=_SEC(),
        policy=policy,
    )

    assert result.screened_asset_count == 6
    assert result.snapshot_covered_count == 6
    assert set().union(*map(set, client.snapshot_calls)) == set(SYMBOLS)

    # Top three receive deep history and the held symbol is always protected.
    assert result.deep_shortlist_count == 4
    deep_symbols = set().union(
        *(set(batch) for batch in client.history_calls if batch != ("VTI",))
    )
    assert deep_symbols == {"AAA", "BBB", "CCC", "FFF"}
    assert all(len(batch) <= 2 for batch in client.history_calls)

    # Two strongest new companies plus the held company enter decision evidence.
    assert [item.symbol for item in result.selected] == ["AAA", "BBB", "FFF"]
    reasons = dict(result.exclusions)
    assert reasons["CCC"] == "outside_decision_evidence_cohort"
    assert reasons["DDD"] == "outside_deep_evidence_cohort"
    assert reasons["EEE"] == "outside_deep_evidence_cohort"


def test_default_policy_keeps_full_snapshot_scope_and_bounded_deep_work() -> None:
    policy = EquityDiscoveryPolicy()

    assert policy.maximum_snapshot_assets is None
    assert policy.deep_shortlist_count == 400
    assert policy.selected_candidate_count == 64
    assert policy.deep_history_batch_size == 25
    assert policy.version == "broad-us-equity-discovery.v3-bounded-decision-evidence"
