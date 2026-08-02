from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    discover_comprehensive_markets,
)
from operations.market_discovery_preselection import (
    CandidateSleeve,
    CatalogScreeningSignal,
    CutoffObservation,
    build_preselection_plan,
    evaluate_cutoff_outcomes,
)
from operations.provider_enriched_preselection import REQUIRED_PROVIDER_FACTORS


def record(symbol):
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        venue="TEST",
        country_code="US",
        currency="USD",
        instrument_type="token",
        source_identifier=f"source:{symbol}",
        economic_exposure="crypto",
        quote_spread_bps=5.0,
        expiration_at=None,
    )


def _provider_factor_evidence(symbol):
    return tuple(
        f"provider-factor:{factor}:test:{factor}.v1:{symbol}"
        for factor in REQUIRED_PROVIDER_FACTORS
    )


def test_default_discovery_has_no_candidate_count_limit_and_sleeves_ignore_catalog_order():
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    records = tuple(record(f"A{i:03d}") for i in range(12))
    signals = {
        item.symbol: CatalogScreeningSignal(
            symbol=item.symbol,
            observed_at=now,
            liquidity_score=.9,
            quality_score=(i + 1) / 20,
            value_score=(12 - i) / 20,
            momentum_score=(i + 1) / 20,
            carry_score=.5,
            improving_conditions_score=(i + 1) / 20,
            indicative_price=100 + i,
        )
        for i, item in enumerate(records)
    }
    plan = build_preselection_plan(
        tuple(reversed(records)),
        signals,
        as_of=now,
        capacity=6,
        shadow_limit=3,
        freshness_days=3,
        minimum_liquidity_score=0,
    )
    assert ComprehensiveMarketDiscoveryPolicy().maximum_deep_candidates_per_lane is None
    assert len(plan.selected_symbols) == 6
    catalog_first_six = tuple(item.symbol for item in tuple(reversed(records))[:6])
    assert plan.selected_symbols != catalog_first_six
    assert plan.catalog_count == len(records)
    assert sum(dict(plan.factor_coverage).values()) >= len(records)
    assert {name for name, _ in plan.sleeve_rankings} == {
        item.value for item in CandidateSleeve
    }


def test_every_eligible_asset_is_analyzed_and_forwarded_despite_legacy_count_settings():
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    ordinary = tuple(
        DiscoveryCatalogRecord(
            symbol=f"COIN{i:03d}",
            provider_symbol=f"COIN{i:03d}-USD",
            name=f"Coin {i}",
            asset_class=CandidateAssetClass.CRYPTO,
            economic_exposure="crypto",
            venue="CC",
            country_code="GLOBAL",
            currency="USD",
            settlement_currency="USD",
            instrument_type="token",
            provider_kind="yahoo",
            source_identifier=f"directory:{i:03d}",
            quote_spread_bps=10,
        )
        for i in range(205)
    )
    held = DiscoveryCatalogRecord(
        symbol="HELD",
        provider_symbol="HELD-USD",
        name="Held",
        asset_class=CandidateAssetClass.CRYPTO,
        economic_exposure="crypto",
        venue="CC",
        country_code="GLOBAL",
        currency="USD",
        settlement_currency="USD",
        instrument_type="token",
        provider_kind="yahoo",
        source_identifier="directory:held",
        quote_spread_bps=10,
    )
    signals = {
        item.symbol: CatalogScreeningSignal(
            symbol=item.symbol,
            observed_at=now,
            liquidity_score=.9,
            quality_score=(i + 1) / 300,
            value_score=(205 - i) / 300,
            momentum_score=(i + 1) / 300,
            carry_score=.5,
            improving_conditions_score=(i + 1) / 300,
            indicative_price=100 + i,
            evidence_identifiers=_provider_factor_evidence(item.symbol),
        )
        for i, item in enumerate(ordinary)
    }

    def catalog_probe(_):
        return {CandidateAssetClass.CRYPTO: ordinary + (held,)}

    def preselection_probe(*_):
        return signals

    def market_probe(records, *_):
        return {
            item.symbol: DiscoveryMarketFeatures(
                price=100,
                observed_at=now,
                one_month_return=.01,
                three_month_return=.02,
                six_month_return=.03,
                twelve_month_return=.04,
                annualized_volatility=.2,
                maximum_drawdown=-.1,
                average_daily_dollar_volume=10_000_000,
                history_bars=300,
                evidence_identifiers=(f"evidence:{item.symbol}",),
            )
            for item in records
        }

    result = discover_comprehensive_markets(
        as_of=now,
        held_symbols=("HELD",),
        catalog_probe=catalog_probe,
        market_probe=market_probe,
        preselection_probe=preselection_probe,
        policy=ComprehensiveMarketDiscoveryPolicy(
            maximum_deep_candidates_per_lane=1,
            selected_crypto_assets=1,
        ),
    )
    lane = next(x for x in result.lanes if x.asset_class is CandidateAssetClass.CRYPTO)
    assert lane.continuity_count == 1
    assert len(lane.preselection.selected_symbols) == 205
    assert lane.preselection.shadow_symbols == ()
    assert lane.deep_analyzed_count == 206
    assert len(lane.selected) == 206
    assert len(lane.preselection_evidence) == 205
    lane_payload = next(
        item
        for item in result.to_dict()["lanes"]
        if item["asset_class"] == CandidateAssetClass.CRYPTO.value
    )
    assert lane_payload["candidate_count_limit_applied"] is False


def test_cutoff_measurement_compares_shadow_with_selected():
    baseline = datetime(2026, 7, 1, tzinfo=timezone.utc)
    result = evaluate_cutoff_outcomes(
        (
            CutoffObservation("crypto", "A", "selected", baseline, 100, ("quality",), .8),
            CutoffObservation("crypto", "B", "below_cutoff", baseline, 100, ("value",), .7),
        ),
        asset_class="crypto",
        current_prices={"A": 105, "B": 120},
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert result[0].below_minus_selected == .15
