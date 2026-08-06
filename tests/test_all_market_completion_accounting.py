from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.routes.cio_diagnostic import _market_lanes
from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryError,
    DiscoveryCatalogRecord,
    discover_comprehensive_markets,
)


AS_OF = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def _record(asset_class: CandidateAssetClass, symbol: str) -> DiscoveryCatalogRecord:
    expiration_at = (
        AS_OF + timedelta(days=90)
        if asset_class in {CandidateAssetClass.FUTURE, CandidateAssetClass.OPTION}
        else None
    )
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=f"Test {symbol}",
        asset_class=asset_class,
        economic_exposure={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "international_equity",
            CandidateAssetClass.FX: "foreign_exchange",
            CandidateAssetClass.CRYPTO: "crypto",
            CandidateAssetClass.FUTURE: "broad_commodities",
            CandidateAssetClass.OPTION: "option_strategies",
        }[asset_class],
        venue="TEST",
        country_code="GLOBAL",
        currency="USD",
        settlement_currency="USD",
        instrument_type={
            CandidateAssetClass.INTERNATIONAL_EQUITY: "common_stock",
            CandidateAssetClass.FX: "spot",
            CandidateAssetClass.CRYPTO: "spot",
            CandidateAssetClass.FUTURE: "future",
            CandidateAssetClass.OPTION: "option",
        }[asset_class],
        provider_kind="yahoo",
        source_identifier=f"catalog:{asset_class.value}:{symbol}",
        instrument_identifier=f"instrument:{asset_class.value}:{symbol.lower()}",
        expiration_at=expiration_at,
        underlying_symbol=(
            "SPY" if asset_class is CandidateAssetClass.OPTION else None
        ),
        strike=500.0 if asset_class is CandidateAssetClass.OPTION else None,
        option_right="call" if asset_class is CandidateAssetClass.OPTION else None,
    )


def _catalogs() -> dict[CandidateAssetClass, list[DiscoveryCatalogRecord]]:
    return {
        CandidateAssetClass.INTERNATIONAL_EQUITY: [
            _record(CandidateAssetClass.INTERNATIONAL_EQUITY, "GLOBAL_TEST")
        ],
        CandidateAssetClass.FX: [
            _record(CandidateAssetClass.FX, "EURUSD")
        ],
        CandidateAssetClass.CRYPTO: [
            _record(CandidateAssetClass.CRYPTO, "BTCUSD")
        ],
        CandidateAssetClass.FUTURE: [
            _record(CandidateAssetClass.FUTURE, "ESZ26")
        ],
        CandidateAssetClass.OPTION: [
            _record(CandidateAssetClass.OPTION, "SPY261106C00500000")
        ],
    }


def test_nonempty_lanes_can_complete_with_explicit_all_excluded_outcomes() -> None:
    result = discover_comprehensive_markets(
        as_of=AS_OF,
        catalog_probe=lambda _as_of: _catalogs(),
        market_probe=lambda _records, _as_of, _policy: {},
    )

    assert len(result.lanes) == 5
    assert result.selected == ()
    assert all(lane.catalog_count == 1 for lane in result.lanes)
    assert all(lane.explicitly_resolved_count == 1 for lane in result.lanes)
    assert all(lane.selected == () for lane in result.lanes)
    assert all(
        next(iter(lane.exclusions))[1]
        == "point_in_time_market_evidence_unavailable"
        for lane in result.lanes
    )
    assert all(
        lane["explicitly_resolved_count"] == lane["catalog_count"] == 1
        for lane in result.to_dict()["lanes"]
    )


def test_empty_required_lane_still_fails_closed() -> None:
    catalogs = _catalogs()
    catalogs[CandidateAssetClass.FX] = []

    with pytest.raises(
        ComprehensiveMarketDiscoveryError,
        match="nonempty certified catalog.*fx",
    ):
        discover_comprehensive_markets(
            as_of=AS_OF,
            catalog_probe=lambda _as_of: catalogs,
            market_probe=lambda _records, _as_of, _policy: {},
        )


def test_release_audit_represents_truthful_no_candidate_lane() -> None:
    lanes = _market_lanes(
        {
            "crypto": {
                "scheduled": True,
                "catalog": 8,
                "deep": 0,
                "selected": 0,
            },
            "fx": {
                "scheduled": True,
                "catalog": 0,
                "deep": 0,
                "selected": 0,
            },
            "option": {
                "scheduled": False,
                "schedule_reason": "weekend_market_closed",
                "catalog": 0,
                "deep": 0,
                "selected": 0,
            },
        }
    )

    by_asset_class = {str(item["asset_class"]): item for item in lanes}
    assert by_asset_class["crypto"]["represented"] is True
    assert by_asset_class["crypto"]["selected_count"] == 0
    assert by_asset_class["fx"]["represented"] is False
    assert by_asset_class["option"]["represented"] is True
