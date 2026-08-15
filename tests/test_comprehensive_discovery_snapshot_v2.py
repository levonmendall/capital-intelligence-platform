from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4_serial as qualified
from operations import comprehensive_discovery_snapshot as persisted
from operations import comprehensive_market_discovery_legacy as legacy
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
    view_qualified_comprehensive_discovery_snapshot,
)


def _values(tmp_path: Path) -> dict[str, str]:
    return {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}


def _result(as_of: datetime) -> qualified.ComprehensiveMarketDiscoveryResult:
    catalog = legacy.DiscoveryCatalogRecord(
        symbol="BTCUSD",
        provider_symbol="BTC/USD",
        name="Bitcoin",
        asset_class=CandidateAssetClass.CRYPTO,
        economic_exposure="crypto",
        venue="COINBASE",
        country_code="GLOBAL",
        currency="USD",
        settlement_currency="USD",
        instrument_type="spot",
        provider_kind="fixture",
        source_identifier="catalog:btc",
        instrument_identifier="crypto:btc-usd",
        contract_multiplier=1.0,
        quote_spread_bps=5.0,
    )
    features = legacy.DiscoveryMarketFeatures(
        price=100000.0,
        observed_at=as_of,
        one_month_return=0.02,
        three_month_return=0.05,
        six_month_return=0.10,
        twelve_month_return=0.20,
        annualized_volatility=0.45,
        maximum_drawdown=-0.20,
        average_daily_dollar_volume=1_000_000_000.0,
        history_bars=500,
        evidence_identifiers=("market:btc",),
    )
    selected = legacy.DiscoveredMarketInstrument(
        catalog=catalog,
        features=features,
        retained_for_state=True,
    )
    lane = qualified.DiscoveryLaneResult(
        asset_class=CandidateAssetClass.CRYPTO,
        catalog_count=1,
        deep_analyzed_count=1,
        selected=(selected,),
        exclusions=(),
        source_identifiers=("source:crypto",),
        scheduled=True,
        schedule_reason=None,
        continuity_count=1,
        preselection=None,
        preselection_evidence=(
            ("BTCUSD", ("provider-factor:momentum", "provider-factor:liquidity")),
        ),
        cutoff_observations=(),
        cutoff_outcomes=(),
    )
    return qualified.ComprehensiveMarketDiscoveryResult(
        identifier="discovery:test",
        as_of=as_of,
        policy_version="policy:test",
        lanes=(lane,),
        manifest_fingerprint="fingerprint:test",
    )


def test_snapshot_round_trip_preserves_continuity_and_provider_factor_lineage(
    tmp_path: Path,
) -> None:
    as_of = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)
    result = _result(as_of)
    snapshot_id = persisted.publish_comprehensive_discovery_snapshot(
        result,
        held_symbols=("BTCUSD",),
        tracked_symbols=(),
        values=_values(tmp_path),
    )

    restored = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=as_of,
        values=_values(tmp_path),
    )

    assert restored.snapshot_id == snapshot_id
    assert restored.held_symbols == ("BTCUSD",)
    assert restored.tracked_symbols == ()
    lane = restored.result.lanes[0]
    assert isinstance(lane, qualified.DiscoveryLaneResult)
    assert lane.continuity_count == 1
    assert lane.preselection_evidence == (
        ("BTCUSD", ("provider-factor:momentum", "provider-factor:liquidity")),
    )
    assert lane.selected[0].catalog.instrument_identifier == "crypto:btc-usd"
    assert lane.selected[0].features.evidence_identifiers == ("market:btc",)


def test_consumer_view_requires_exact_portfolio_learning_scope(tmp_path: Path) -> None:
    as_of = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)
    persisted.publish_comprehensive_discovery_snapshot(
        _result(as_of),
        held_symbols=("BTCUSD",),
        tracked_symbols=("ETHUSD",),
        values=_values(tmp_path),
    )
    restored = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=as_of,
        values=_values(tmp_path),
    )

    with pytest.raises(ComprehensiveDiscoverySnapshotError, match="state scope"):
        view_qualified_comprehensive_discovery_snapshot(
            restored,
            held_symbols=(),
            tracked_symbols=("ETHUSD",),
            excluded_symbols=(),
        )


def test_consumer_exclusion_is_local_and_preserves_terminal_accounting(
    tmp_path: Path,
) -> None:
    as_of = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)
    persisted.publish_comprehensive_discovery_snapshot(
        _result(as_of),
        held_symbols=("BTCUSD",),
        tracked_symbols=(),
        values=_values(tmp_path),
    )
    restored = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=as_of,
        values=_values(tmp_path),
    )

    view = view_qualified_comprehensive_discovery_snapshot(
        restored,
        held_symbols=("BTCUSD",),
        tracked_symbols=(),
        excluded_symbols=("BTCUSD",),
    )

    lane = view.lanes[0]
    assert lane.catalog_count == 1
    assert lane.selected == ()
    assert lane.exclusions == (("BTCUSD", "explicit_discovery_exclusion"),)
    assert lane.preselection_evidence == restored.result.lanes[0].preselection_evidence
    assert view.manifest_fingerprint != restored.result.manifest_fingerprint


def test_snapshot_identity_is_release_independent(tmp_path: Path) -> None:
    as_of = datetime(2026, 8, 15, 2, 0, tzinfo=timezone.utc)
    values_a = {**_values(tmp_path), "CAPITAL_INTELLIGENCE_RELEASE": "release-a"}
    values_b = {**_values(tmp_path), "CAPITAL_INTELLIGENCE_RELEASE": "release-b"}

    first = persisted.publish_comprehensive_discovery_snapshot(
        _result(as_of),
        held_symbols=("BTCUSD",),
        tracked_symbols=(),
        values=values_a,
    )
    second = persisted.publish_comprehensive_discovery_snapshot(
        _result(as_of),
        held_symbols=("BTCUSD",),
        tracked_symbols=(),
        values=values_b,
    )

    assert first == second
