from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass, CandidateInstrument
from operations.active_paper_universe import build_active_opportunity_engine
from operations.certified_investable_catalog import load_certified_investable_catalog
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    _catalog_from_eodhd,
    discover_comprehensive_markets,
)
from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    FreePaperPilotUniverse,
    load_execution_paper_universe,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
from portfolio.construction_models import PortfolioConstructionPolicy


AS_OF = datetime(2026, 8, 3, 15, tzinfo=timezone.utc)


def _record(
    asset_class: CandidateAssetClass,
    symbol: str,
    *,
    instrument_type: str,
    exposure: str,
    currency: str = "USD",
    expiry: datetime | None = None,
) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure=exposure,
        venue="TEST",
        country_code="US",
        currency=currency,
        settlement_currency=currency,
        instrument_type=instrument_type,
        provider_kind="yahoo",
        source_identifier=f"source:{symbol}",
        expiration_at=expiry,
        underlying_symbol="SPY" if instrument_type == "option" else None,
        strike=500.0 if instrument_type == "option" else None,
        option_right="call" if instrument_type == "option" else None,
    )


def _all_legacy_catalogs() -> dict[CandidateAssetClass, list[DiscoveryCatalogRecord]]:
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [
            _record(
                CandidateAssetClass.INTERNATIONAL_EQUITY,
                "GLOBAL",
                instrument_type="common_stock",
                exposure="international_equity",
            )
        ],
        CandidateAssetClass.FX: [
            _record(
                CandidateAssetClass.FX,
                "EURUSD",
                instrument_type="spot",
                exposure="foreign_exchange",
            )
        ],
        CandidateAssetClass.CRYPTO: [
            _record(
                CandidateAssetClass.CRYPTO,
                "BTCUSD",
                instrument_type="token",
                exposure="crypto",
            )
        ],
        CandidateAssetClass.FUTURE: [
            _record(
                CandidateAssetClass.FUTURE,
                "ESZ26",
                instrument_type="future",
                exposure="us_equity",
                expiry=AS_OF + timedelta(days=100),
            )
        ],
        CandidateAssetClass.FIXED_INCOME: [
            _record(
                CandidateAssetClass.FIXED_INCOME,
                "BOND",
                instrument_type="bond",
                exposure="government_bonds",
            )
        ],
        CandidateAssetClass.OPTION: [
            _record(
                CandidateAssetClass.OPTION,
                "SPYCALL",
                instrument_type="option",
                exposure="option_strategies",
                expiry=AS_OF + timedelta(days=100),
            )
        ],
    }


def _market(records, _as_of, _policy):
    return {
        item.symbol: DiscoveryMarketFeatures(
            price=100.0,
            observed_at=AS_OF,
            one_month_return=0.01,
            three_month_return=0.02,
            six_month_return=0.04,
            twelve_month_return=0.08,
            annualized_volatility=0.2,
            maximum_drawdown=-0.1,
            average_daily_dollar_volume=20_000_000.0,
            history_bars=400,
            evidence_identifiers=(f"evidence:{item.symbol}",),
        )
        for item in records
    }


def _universe(*instruments: FreePaperPilotInstrument) -> FreePaperPilotUniverse:
    return FreePaperPilotUniverse(
        identifier="universal-test-universe",
        objective="Maximize compounded paper returns",
        portfolio_code="COMPOUNDING",
        reporting_currency="USD",
        quote_provider="certified",
        execution_mode="internal-simulated-fills-only",
        minimum_cash_weight=0.02,
        maximum_batch_turnover=0.5,
        maximum_single_instrument_weight=0.8,
        maximum_crypto_proxy_weight=0.2,
        maximum_volatility_proxy_weight=0.2,
        maximum_quote_age_minutes=5,
        required_exposure_classes=tuple(
            dict.fromkeys(item.economic_exposure for item in instruments)
        ),
        instruments=tuple(instruments),
        limitations=("paper only",),
    )


def test_dynamic_discovery_adds_classified_lanes_beyond_original_six() -> None:
    catalogs = _all_legacy_catalogs()
    catalogs[CandidateAssetClass.REAL_ESTATE] = [
        _record(
            CandidateAssetClass.REAL_ESTATE,
            "REIT",
            instrument_type="common_stock",
            exposure="real_estate",
        )
    ]

    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=lambda _as_of: catalogs,
        market_probe=_market,
    )

    assert CandidateAssetClass.REAL_ESTATE in {
        lane.asset_class for lane in result.lanes
    }
    assert "REIT" in {item.catalog.symbol for item in result.selected}


def test_complete_certified_catalog_contract_accepts_any_classified_instrument(
    tmp_path,
) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "capital-intelligence-certified-investable-catalog.v1",
                "complete": True,
                "as_of": (AS_OF - timedelta(minutes=2)).isoformat(),
                "available_at": (AS_OF - timedelta(minutes=1)).isoformat(),
                "records": [
                    {
                        "instrument_identifier": "instrument:commodity:silver",
                        "symbol": "SILVER",
                        "asset_class": "commodity",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    records = load_certified_investable_catalog(as_of=AS_OF, path=path)

    assert records[0]["asset_class"] == "commodity"


def test_provider_directory_compatibility_limit_does_not_truncate_catalog() -> None:
    class Provider:
        def fetch_dataset(self, query):
            assert query.limit == 1_000_000
            return SimpleNamespace(
                payload={
                    "active": [
                        {
                            "Code": "EUR-BOND",
                            "Name": "Euro Government Bond",
                            "Type": "Bond",
                            "Currency": "EUR",
                            "CountryISO2": "DE",
                            "Exchange": "BOND",
                        },
                        {
                            "Code": "USD-BOND",
                            "Name": "US Government Bond",
                            "Type": "Bond",
                            "Currency": "USD",
                            "CountryISO2": "US",
                            "Exchange": "BOND",
                        },
                    ]
                },
                provider_record_id="directory:BOND",
            )

    result = _catalog_from_eodhd(
        as_of=AS_OF,
        config=ComprehensiveMarketDiscoveryConfig(
            eodhd_exchange_codes=("BOND",),
            futures_roots=(),
            option_underlyings=(),
            yahoo_exchange_suffixes=(),
        ),
        provider=Provider(),
        policy=ComprehensiveMarketDiscoveryPolicy(
            maximum_directory_records_per_source=1
        ),
        requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
    )

    assert {item.currency for item in result[CandidateAssetClass.FIXED_INCOME]} == {
        "EUR",
        "USD",
    }


@pytest.mark.parametrize(
    ("asset_class", "instrument_type", "exposure"),
    (
        (CandidateAssetClass.COMMODITY, "spot", "silver"),
        (CandidateAssetClass.REAL_ESTATE, "common_stock", "real_estate"),
        (CandidateAssetClass.VOLATILITY, "future", "volatility"),
        (CandidateAssetClass.ALTERNATIVE, "warrant", "special_situations"),
    ),
)
def test_paper_instrument_eligibility_is_capability_based_not_class_whitelisted(
    asset_class: CandidateAssetClass,
    instrument_type: str,
    exposure: str,
) -> None:
    instrument = FreePaperPilotInstrument(
        symbol=f"X{asset_class.value[:3].upper()}",
        instrument_identifier=f"instrument:{asset_class.value}:test",
        name="Certified test instrument",
        execution_asset_class=asset_class,
        economic_exposure=exposure,
        venue="TEST",
        country_code="US",
        currency="USD",
        instrument_type=instrument_type,
        maximum_weight=0.05,
        provider_symbol="TEST",
        provider_kind="yahoo",
        expiration_at=(
            (AS_OF + timedelta(days=90)).isoformat()
            if instrument_type == "future"
            else None
        ),
        approval_identifier="approval:test",
        custody_settlement_identifier="custody:test",
        execution_model_version="execution:test.v1",
    )

    profile = instrument.profile(universe_identifier="test")

    assert profile.asset_class is asset_class
    assert profile.instrument_type == instrument_type
    assert profile.approval_state.value == "paper_eligible"



def test_listed_adapter_accepts_capability_certified_new_instrument_structure() -> None:
    instrument = FreePaperPilotInstrument(
        symbol="NEWW",
        instrument_identifier="instrument:alternative:new-warrant",
        name="Certified listed warrant",
        execution_asset_class=CandidateAssetClass.ALTERNATIVE,
        economic_exposure="special_situations",
        venue="NASDAQ",
        country_code="US",
        currency="USD",
        instrument_type="warrant",
        maximum_weight=0.02,
        provider_kind="alpaca",
        approval_identifier="approval:new-warrant",
        custody_settlement_identifier="custody:broker-listed",
        execution_model_version="execution:listed-symbol.v1",
        contract_model_version="contract:warrant.v1",
        margin_model_version="margin:fully-funded.v1",
        lifecycle_model_version="lifecycle:warrant.v1",
    )

    profile = instrument.profile(universe_identifier="test")

    assert profile.asset_class is CandidateAssetClass.ALTERNATIVE
    assert profile.instrument_type == "warrant"
    assert profile.approval_state.value == "paper_eligible"


def test_compatibility_discovery_does_not_reactivate_old_count_limits() -> None:
    from operations import comprehensive_market_discovery_legacy as legacy

    catalogs = _all_legacy_catalogs()
    catalogs[CandidateAssetClass.INTERNATIONAL_EQUITY].append(
        _record(
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            "GLOBAL2",
            instrument_type="common_stock",
            exposure="international_equity",
        )
    )
    result = legacy.discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=lambda _as_of: catalogs,
        market_probe=_market,
        policy=legacy.ComprehensiveMarketDiscoveryPolicy(
            maximum_deep_candidates_per_lane=1,
            selected_global_equities=1,
        ),
    )

    lane = next(
        item
        for item in result.lanes
        if item.asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY
    )
    assert {item.catalog.symbol for item in lane.selected} == {"GLOBAL", "GLOBAL2"}
    assert lane.deep_analyzed_count == 2

def test_active_opportunity_engine_always_injects_exact_capability_authority() -> None:
    instrument = FreePaperPilotInstrument(
        symbol="BTCUSD",
        instrument_identifier="instrument:crypto:btcusd",
        name="Bitcoin",
        execution_asset_class=CandidateAssetClass.CRYPTO,
        economic_exposure="crypto",
        venue="CC",
        country_code="GLOBAL",
        currency="USD",
        instrument_type="token",
        maximum_weight=0.05,
        provider_symbol="BTC-USD",
        provider_kind="yahoo",
    )
    base = load_free_paper_pilot_universe()
    engine = build_active_opportunity_engine(
        replace(
            base,
            identifier="universal-authority-test",
            instruments=(*base.instruments, instrument),
        )
    )
    candidate_instrument = CandidateInstrument(
        instrument_id=instrument.instrument_identifier,
        symbol=instrument.symbol,
        name=instrument.name,
        asset_class=CandidateAssetClass.CRYPTO,
        venue=instrument.venue,
        country_code=instrument.country_code,
        average_daily_dollar_volume=100_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=1.0,
        instrument_type="token",
        economic_exposure_class=CandidateAssetClass.CRYPTO,
        security_master_snapshot_identifier="security-master:test",
        security_master_record_identifiers=("security-master-record:test",),
    )

    assessment = engine.universe_policy.evaluate(candidate_instrument, as_of=AS_OF)

    assert assessment.direct_recommendation_allowed is True
    assert assessment.asset_class_approval_identifier is not None


def test_execution_universe_never_falls_back_to_static_shortlist(tmp_path) -> None:
    instrument = FreePaperPilotInstrument(
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        name="VTI",
        execution_asset_class=CandidateAssetClass.US_ETF,
        economic_exposure="us_equity",
        venue="NYSEARCA",
        country_code="US",
        currency="USD",
        instrument_type="fund",
        maximum_weight=0.5,
    )
    active = tmp_path / "active.json"
    write_active_paper_universe(
        _universe(instrument),
        eligible_universe_publication_identifier="publication:current",
        destination=active,
    )

    with pytest.raises(ValueError, match="does not match"):
        load_execution_paper_universe(
            {"eligible_universe_publication_identifier": "publication:old"},
            active_path=active,
        )


def test_construction_search_width_expands_with_approved_opportunity_count() -> None:
    policy = PortfolioConstructionPolicy()

    assert policy.resolved_optimizer_beam_width(2) >= 4
    assert policy.resolved_optimizer_beam_width(10) > 4
    assert policy.resolved_optimizer_beam_width(100) >= 100
    assert PortfolioConstructionPolicy(
        optimizer_beam_width=2
    ).resolved_optimizer_beam_width(20) >= 20
