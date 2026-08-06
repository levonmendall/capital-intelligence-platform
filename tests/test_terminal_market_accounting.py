from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.routes.cio_diagnostic import _market_lanes
from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryError,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    _validate_terminal_lane_accounting,
    discover_comprehensive_markets,
)


AS_OF = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)


def _record(
    asset_class: CandidateAssetClass,
    symbol: str,
    *,
    expiry: datetime | None = None,
) -> DiscoveryCatalogRecord:
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
            CandidateAssetClass.OPTION: "option",
        }[asset_class],
        provider_kind="yahoo",
        source_identifier=f"source:{symbol}",
        expiration_at=expiry,
        underlying_symbol=(
            "SPY" if asset_class is CandidateAssetClass.OPTION else None
        ),
        strike=500.0 if asset_class is CandidateAssetClass.OPTION else None,
        option_right="call" if asset_class is CandidateAssetClass.OPTION else None,
        contract_multiplier=(
            100.0 if asset_class is CandidateAssetClass.OPTION else 1.0
        ),
    )


def _catalog(_as_of: datetime):
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [
            _record(CandidateAssetClass.INTERNATIONAL_EQUITY, "AAA_LSE")
        ],
        CandidateAssetClass.FX: [
            _record(CandidateAssetClass.FX, "EURUSD")
        ],
        CandidateAssetClass.CRYPTO: [
            _record(CandidateAssetClass.CRYPTO, "BTCUSD")
        ],
        CandidateAssetClass.FUTURE: [
            _record(
                CandidateAssetClass.FUTURE,
                "ESZ26",
                expiry=AS_OF + timedelta(days=90),
            )
        ],
        CandidateAssetClass.OPTION: [
            _record(
                CandidateAssetClass.OPTION,
                "SPY261218C00500000",
                expiry=AS_OF + timedelta(days=134),
            )
        ],
    }


def _market(records, _as_of, _policy):
    return {
        item.symbol: DiscoveryMarketFeatures(
            price=100.0,
            observed_at=AS_OF,
            one_month_return=0.02,
            three_month_return=0.05,
            six_month_return=0.10,
            twelve_month_return=0.20,
            annualized_volatility=0.20,
            maximum_drawdown=-0.15,
            average_daily_dollar_volume=20_000_000.0,
            history_bars=500,
            evidence_identifiers=(f"evidence:{item.symbol}",),
        )
        for item in records
    }


def test_complete_discovery_certifies_fully_rejected_lane() -> None:
    def market(records, as_of, policy):
        result = _market(records, as_of, policy)
        for record in records:
            if record.asset_class is CandidateAssetClass.FX:
                result.pop(record.symbol)
        return result

    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=_catalog,
        market_probe=market,
    )

    fx_lane = next(
        lane for lane in result.lanes if lane.asset_class is CandidateAssetClass.FX
    )
    assert fx_lane.catalog_count == 1
    assert fx_lane.selected == ()
    assert (
        "EURUSD",
        "point_in_time_market_evidence_unavailable",
    ) in fx_lane.exclusions
    assert fx_lane.source_identifiers == ("source:EURUSD",)
    assert result.policy_version.endswith("v5-terminal-market-accounting")


def test_complete_discovery_certifies_lifecycle_only_exclusions() -> None:
    def catalog(as_of):
        payload = dict(_catalog(as_of))
        payload[CandidateAssetClass.FUTURE] = [
            _record(
                CandidateAssetClass.FUTURE,
                "EXPIRING",
                expiry=AS_OF + timedelta(days=2),
            )
        ]
        return payload

    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=catalog,
        market_probe=_market,
    )

    future_lane = next(
        lane
        for lane in result.lanes
        if lane.asset_class is CandidateAssetClass.FUTURE
    )
    assert future_lane.catalog_count == 1
    assert future_lane.deep_analyzed_count == 0
    assert future_lane.selected == ()
    assert future_lane.exclusions == (
        ("EXPIRING", "catalog_lifecycle_inside_minimum_window"),
    )
    assert future_lane.source_identifiers == ("source:EXPIRING",)


def test_complete_discovery_still_fails_closed_for_empty_catalog() -> None:
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


def test_terminal_accounting_rejects_unaccounted_record() -> None:
    record = _record(CandidateAssetClass.FX, "EURUSD")

    with pytest.raises(
        ComprehensiveMarketDiscoveryError,
        match="unaccounted=EURUSD",
    ):
        _validate_terminal_lane_accounting(
            asset_class=CandidateAssetClass.FX,
            catalog_records=(record,),
            selected=(),
            exclusions=(),
        )


def test_release_audit_represents_nonempty_all_excluded_lane() -> None:
    lanes = _market_lanes(
        {
            "fx": {
                "scheduled": True,
                "catalog": 12,
                "deep": 0,
                "selected": 0,
            }
        }
    )

    assert lanes == (
        {
            "asset_class": "fx",
            "scheduled": True,
            "schedule_reason": None,
            "catalog_count": 12,
            "deep_analyzed_count": 0,
            "selected_count": 0,
            "represented": True,
        },
    )
