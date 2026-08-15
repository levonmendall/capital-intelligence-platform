from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from operations.equity_discovery import DiscoveredEquity, EquityDiscoveryResult
from operations.equity_discovery_snapshot import (
    EquityDiscoverySnapshotError,
    load_equity_discovery_snapshot,
    publish_equity_discovery_snapshot,
    view_equity_discovery_snapshot,
)


def _values(tmp_path: Path) -> dict[str, str]:
    return {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}


def _result(as_of: datetime) -> EquityDiscoveryResult:
    candidate = DiscoveredEquity(
        symbol="AAPL",
        name="Apple Inc.",
        cik="0000320193",
        venue="NASDAQ",
        instrument_identifier="instrument:us-equity:aapl",
        score=0.42,
        daily_return=0.01,
        one_month_return=0.03,
        three_month_return=0.08,
        six_month_return=0.12,
        twelve_month_return=0.18,
        relative_strength=0.04,
        annualized_volatility=0.25,
        maximum_drawdown=-0.15,
        average_daily_dollar_volume=2_000_000_000.0,
        current_price=225.0,
        bar_count=500,
        evidence_identifiers=("alpaca:AAPL:bars", "sec:AAPL:identity"),
    )
    return EquityDiscoveryResult(
        identifier="equity-discovery:test",
        as_of=as_of,
        policy_version="broad-us-equity-discovery:test",
        screened_asset_count=5000,
        snapshot_covered_count=4900,
        deep_shortlist_count=100,
        selected=(candidate,),
        observed_prices=(("AAPL", 225.0, "alpaca:AAPL:bars"),),
        exclusions=(("ZZZZ", "insufficient_deep_history"),),
        security_master_snapshot_identifier="sec-company-master:test",
    )


def test_round_trip_preserves_full_equity_discovery_and_scope(tmp_path: Path) -> None:
    as_of = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    original = _result(as_of)
    snapshot_id = publish_equity_discovery_snapshot(
        original,
        held_symbols=("AAPL",),
        tracked_symbols=("MSFT",),
        excluded_symbols=("SPY", "VTI"),
        values=_values(tmp_path),
    )

    restored = load_equity_discovery_snapshot(
        evidence_as_of=as_of,
        values=_values(tmp_path),
    )

    assert restored.snapshot_id == snapshot_id
    assert restored.evidence_as_of == as_of
    assert restored.held_symbols == ("AAPL",)
    assert restored.tracked_symbols == ("MSFT",)
    assert restored.excluded_symbols == ("SPY", "VTI")
    assert restored.result == original


def test_consumer_requires_exact_held_tracked_and_exclusion_scope(tmp_path: Path) -> None:
    as_of = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    publish_equity_discovery_snapshot(
        _result(as_of),
        held_symbols=("AAPL",),
        tracked_symbols=("MSFT",),
        excluded_symbols=("SPY",),
        values=_values(tmp_path),
    )
    restored = load_equity_discovery_snapshot(
        evidence_as_of=as_of,
        values=_values(tmp_path),
    )

    with pytest.raises(EquityDiscoverySnapshotError, match="held-symbol"):
        view_equity_discovery_snapshot(
            restored,
            held_symbols=(),
            tracked_symbols=("MSFT",),
            excluded_symbols=("SPY",),
        )
    with pytest.raises(EquityDiscoverySnapshotError, match="learning scope"):
        view_equity_discovery_snapshot(
            restored,
            held_symbols=("AAPL",),
            tracked_symbols=(),
            excluded_symbols=("SPY",),
        )
    with pytest.raises(EquityDiscoverySnapshotError, match="base-universe exclusion"):
        view_equity_discovery_snapshot(
            restored,
            held_symbols=("AAPL",),
            tracked_symbols=("MSFT",),
            excluded_symbols=(),
        )


def test_snapshot_identity_is_release_independent(tmp_path: Path) -> None:
    as_of = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)
    first = publish_equity_discovery_snapshot(
        _result(as_of),
        held_symbols=(),
        tracked_symbols=(),
        excluded_symbols=("SPY",),
        values={**_values(tmp_path), "CAPITAL_INTELLIGENCE_RELEASE": "release-a"},
    )
    second = publish_equity_discovery_snapshot(
        _result(as_of),
        held_symbols=(),
        tracked_symbols=(),
        excluded_symbols=("SPY",),
        values={**_values(tmp_path), "CAPITAL_INTELLIGENCE_RELEASE": "release-b"},
    )

    assert first == second
