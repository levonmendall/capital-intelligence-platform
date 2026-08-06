from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryConfig,
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    _catalog_from_eodhd,
    DiscoveryMarketFeatures,
    discover_comprehensive_markets,
)


AS_OF = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def _record(asset_class: CandidateAssetClass, symbol: str, *, expiry: datetime | None = None):
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
        country_code="US" if asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.FIXED_INCOME, CandidateAssetClass.OPTION} else "GLOBAL",
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
        provider_kind="yahoo",
        source_identifier=f"source:{symbol}",
        expiration_at=expiry,
        underlying_symbol="SPY" if asset_class is CandidateAssetClass.OPTION else None,
        strike=500.0 if asset_class is CandidateAssetClass.OPTION else None,
        option_right="call" if asset_class is CandidateAssetClass.OPTION else None,
        contract_multiplier=100.0 if asset_class is CandidateAssetClass.OPTION else 1.0,
    )


def _catalog(_as_of):
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [_record(CandidateAssetClass.INTERNATIONAL_EQUITY, "AAA_LSE"), _record(CandidateAssetClass.INTERNATIONAL_EQUITY, "HELD_LSE")],
        CandidateAssetClass.FX: [_record(CandidateAssetClass.FX, "EURUSD")],
        CandidateAssetClass.CRYPTO: [_record(CandidateAssetClass.CRYPTO, "SOLUSD")],
        CandidateAssetClass.FUTURE: [_record(CandidateAssetClass.FUTURE, "ESU26", expiry=AS_OF + timedelta(days=60))],
        CandidateAssetClass.FIXED_INCOME: [_record(CandidateAssetClass.FIXED_INCOME, "UST2035")],
        CandidateAssetClass.OPTION: [_record(CandidateAssetClass.OPTION, "SPY261218C00500000", expiry=AS_OF + timedelta(days=140))],
    }


def _market(records, _as_of, _policy):
    return {
        item.symbol: DiscoveryMarketFeatures(
            price=100.0,
            observed_at=AS_OF,
            one_month_return=0.02,
            three_month_return=0.05,
            six_month_return=0.10,
            twelve_month_return=(0.01 if item.symbol == "HELD_LSE" else 0.20),
            annualized_volatility=0.20,
            maximum_drawdown=-0.15,
            average_daily_dollar_volume=20_000_000.0,
            history_bars=500,
            evidence_identifiers=(f"evidence:{item.symbol}",),
        )
        for item in records
    }


def test_eodhd_cc_currency_rows_are_classified_as_crypto():
    class Provider:
        def fetch_dataset(self, query):
            assert query.provider_symbol == "CC"
            return SimpleNamespace(
                payload={
                    "active": [
                        {
                            "Code": "BTC-USD",
                            "Name": "Bitcoin",
                            "Type": "Currency",
                            "Currency": "USD",
                            "Exchange": "CC",
                        }
                    ]
                },
                provider_record_id="eodhd-symbol-directory:CC",
            )

    catalogs = _catalog_from_eodhd(
        as_of=AS_OF,
        config=ComprehensiveMarketDiscoveryConfig(
            eodhd_exchange_codes=("CC",),
            futures_roots=(),
            option_underlyings=(),
            yahoo_exchange_suffixes=(),
        ),
        provider=Provider(),
        policy=ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.CRYPTO}),
    )

    assert CandidateAssetClass.FX not in catalogs
    assert len(catalogs[CandidateAssetClass.CRYPTO]) == 1
    record = catalogs[CandidateAssetClass.CRYPTO][0]
    assert record.symbol == "BTCUSD"
    assert record.provider_symbol == "BTC-USD"
    assert record.asset_class is CandidateAssetClass.CRYPTO
    assert record.instrument_type == "token"
    assert record.provider_kind == "yahoo"


def test_discovers_all_six_lanes_and_retains_holdings():
    result = discover_comprehensive_markets(
        as_of=AS_OF,
        held_symbols=("HELD_LSE",),
        catalog_probe=_catalog,
        market_probe=_market,
        policy=ComprehensiveMarketDiscoveryPolicy(
            selected_global_equities=1,
            selected_fx_pairs=1,
            selected_crypto_assets=1,
            selected_futures_contracts=1,
            selected_bonds=1,
            selected_options=1,
        ),
    )
    assert len(result.lanes) == 6
    assert {lane.asset_class for lane in result.lanes} == {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.FUTURE,
        CandidateAssetClass.FIXED_INCOME,
        CandidateAssetClass.OPTION,
    }
    symbols = {item.catalog.symbol for item in result.selected}
    assert "HELD_LSE" in symbols
    instruments = {item.symbol: item for item in result.instruments_for_holdings(("HELD_LSE",))}
    assert instruments["HELD_LSE"].maximum_weight == 0.06
    assert instruments["SPY261218C00500000"].option_right == "call"
    assert instruments["ESU26"].expiration_at is not None
    assert result.manifest_fingerprint
    assert result.to_dict()["real_money_authorized"] is False


def test_expired_contracts_are_excluded_before_market_probe():
    def catalog(_as_of):
        payload = dict(_catalog(_as_of))
        payload[CandidateAssetClass.FUTURE] = [
            _record(CandidateAssetClass.FUTURE, "OLD", expiry=AS_OF + timedelta(days=2)),
            _record(CandidateAssetClass.FUTURE, "NEW", expiry=AS_OF + timedelta(days=90)),
        ]
        return payload

    seen = []

    def market(records, as_of, policy):
        seen.extend(item.symbol for item in records)
        return _market(records, as_of, policy)

    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=catalog,
        market_probe=market,
    )
    assert "OLD" not in seen
    assert any(item.catalog.symbol == "NEW" for item in result.selected)


def test_absent_direct_fixed_income_catalog_is_not_a_required_empty_lane():
    def catalog(as_of):
        payload = dict(_catalog(as_of))
        payload.pop(CandidateAssetClass.FIXED_INCOME)
        return payload

    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=catalog,
        market_probe=_market,
    )

    assert CandidateAssetClass.FIXED_INCOME not in {
        lane.asset_class for lane in result.lanes
    }
    assert len(result.lanes) == 5


def test_complete_discovery_still_fails_closed_for_empty_required_lane():
    def catalog(as_of):
        payload = dict(_catalog(as_of))
        payload[CandidateAssetClass.FX] = []
        return payload

    with pytest.raises(ComprehensiveMarketDiscoveryError, match="fx"):
        discover_comprehensive_markets(
            as_of=AS_OF,
            catalog_probe=catalog,
            market_probe=_market,
        )
