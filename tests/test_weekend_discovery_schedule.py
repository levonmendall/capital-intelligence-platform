from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio import CandidateAssetClass
from operations import comprehensive_market_discovery as comprehensive
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryConfig,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    default_catalog_probe,
    discover_comprehensive_markets,
    scheduled_discovery_lanes,
)
from operations.equity_discovery import (
    discover_us_equities,
    us_equity_discovery_scheduled,
)


# Weekend eligibility follows the America/New_York market calendar.
WEEKEND_AS_OF = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
WEEKDAY_AS_OF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def _record(asset_class: CandidateAssetClass, symbol: str) -> DiscoveryCatalogRecord:
    expiration = (
        WEEKEND_AS_OF + timedelta(days=90)
        if asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION}
        else None
    )
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "international_equity",
            CandidateAssetClass.FX: "foreign_exchange",
            CandidateAssetClass.CRYPTO: "crypto",
            CandidateAssetClass.FUTURE: "broad_commodities",
            CandidateAssetClass.FIXED_INCOME: "government_bonds",
            CandidateAssetClass.OPTION: "option_strategies",
        }[asset_class],
        venue="TEST",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "common_stock",
            CandidateAssetClass.FX: "spot",
            CandidateAssetClass.CRYPTO: "token",
            CandidateAssetClass.FUTURE: "future",
            CandidateAssetClass.FIXED_INCOME: "bond",
            CandidateAssetClass.OPTION: "option",
        }[asset_class],
        provider_kind="test",
        source_identifier=f"source:{symbol}",
        expiration_at=expiration,
        underlying_symbol="SPY" if asset_class is CandidateAssetClass.OPTION else None,
        strike=500.0 if asset_class is CandidateAssetClass.OPTION else None,
        option_right="call" if asset_class is CandidateAssetClass.OPTION else None,
        contract_multiplier=100.0 if asset_class is CandidateAssetClass.OPTION else 1.0,
    )


def _all_catalogs(_as_of):
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [
            _record(CandidateAssetClass.INTERNATIONAL_EQUITY, "EQ")
        ],
        CandidateAssetClass.FX: [_record(CandidateAssetClass.FX, "EURUSD")],
        CandidateAssetClass.CRYPTO: [_record(CandidateAssetClass.CRYPTO, "BTCUSD")],
        CandidateAssetClass.FUTURE: [_record(CandidateAssetClass.FUTURE, "ESZ26")],
        CandidateAssetClass.FIXED_INCOME: [
            _record(CandidateAssetClass.FIXED_INCOME, "UST")
        ],
        CandidateAssetClass.OPTION: [
            _record(CandidateAssetClass.OPTION, "SPYOPTION")
        ],
    }


def test_weekend_schedule_keeps_only_crypto_active():
    assert scheduled_discovery_lanes(WEEKEND_AS_OF) == frozenset(
        {CandidateAssetClass.CRYPTO}
    )
    assert len(scheduled_discovery_lanes(WEEKDAY_AS_OF)) == 6
    assert us_equity_discovery_scheduled(WEEKEND_AS_OF) is False
    assert us_equity_discovery_scheduled(WEEKDAY_AS_OF) is True


def test_weekend_comprehensive_discovery_evaluates_only_crypto():
    evaluated = []

    def market_probe(records, _as_of, _policy):
        evaluated.extend(item.asset_class for item in records)
        return {
            item.symbol: DiscoveryMarketFeatures(
                price=100.0,
                observed_at=WEEKEND_AS_OF,
                one_month_return=0.01,
                three_month_return=0.02,
                six_month_return=0.03,
                twelve_month_return=0.04,
                annualized_volatility=0.20,
                maximum_drawdown=-0.10,
                average_daily_dollar_volume=20_000_000.0,
                history_bars=500,
                evidence_identifiers=(f"evidence:{item.symbol}",),
            )
            for item in records
        }

    result = discover_comprehensive_markets(
        as_of=WEEKEND_AS_OF,
        catalog_probe=_all_catalogs,
        market_probe=market_probe,
    )

    assert len(result.lanes) == 6
    assert evaluated == [CandidateAssetClass.CRYPTO]
    assert {item.catalog.asset_class for item in result.selected} == {
        CandidateAssetClass.CRYPTO
    }
    lane_by_class = {lane.asset_class: lane for lane in result.lanes}
    assert lane_by_class[CandidateAssetClass.CRYPTO].scheduled is True
    for asset_class, lane in lane_by_class.items():
        if asset_class is CandidateAssetClass.CRYPTO:
            continue
        assert lane.scheduled is False
        assert lane.schedule_reason == "weekend_market_closed"
        assert lane.selected == ()


def test_weekend_default_catalog_does_not_call_futures_or_options(monkeypatch):
    crypto = _record(CandidateAssetClass.CRYPTO, "BTCUSD")

    def directory_probe(**kwargs):
        assert kwargs["requested_asset_classes"] == frozenset(
            {CandidateAssetClass.CRYPTO}
        )
        return {CandidateAssetClass.CRYPTO: [crypto]}

    def unavailable_probe(**_kwargs):
        raise AssertionError("weekday-only provider path was called on a weekend")

    monkeypatch.setattr(comprehensive, "_catalog_from_eodhd", directory_probe)
    monkeypatch.setattr(comprehensive, "_futures_catalog", unavailable_probe)
    monkeypatch.setattr(comprehensive, "_option_catalog", unavailable_probe)

    result = default_catalog_probe(
        WEEKEND_AS_OF,
        config=ComprehensiveMarketDiscoveryConfig(
            eodhd_exchange_codes=("CC",),
            futures_roots=(),
            option_underlyings=(),
            yahoo_exchange_suffixes=(),
        ),
        eodhd_provider=object(),
        databento_options_provider=object(),
    )

    assert result[CandidateAssetClass.CRYPTO] == [crypto]
    assert all(
        result[asset_class] == []
        for asset_class in result
        if asset_class is not CandidateAssetClass.CRYPTO
    )


def test_weekend_us_equity_discovery_does_not_call_providers():
    class ProviderMustNotRun:
        def __getattr__(self, name):
            raise AssertionError(f"provider method {name} was called on a weekend")

    result = discover_us_equities(
        as_of=WEEKEND_AS_OF,
        client=ProviderMustNotRun(),
        sec_provider=ProviderMustNotRun(),
    )

    assert result.selected == ()
    assert result.observed_prices == ()
    assert result.exclusions == (("__lane__", "weekend_market_closed"),)
    assert result.security_master_snapshot_identifier.endswith(":closed")
