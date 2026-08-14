from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4 as discovery
from operations import reference_readiness as legacy
from operations.generalized_reference_readiness import (
    _lane_config_fingerprint,
    _lane_coverage,
    _prime_legacy_components,
    asset_reference_component_path,
    load_asset_reference_component,
    store_asset_reference_component,
)


NOW = datetime(2026, 8, 13, 21, 30, tzinfo=timezone.utc)


def _config():
    return SimpleNamespace(
        eodhd_exchange_codes=("LSE", "FOREX", "CC"),
        futures_roots=(
            {
                "root": "ES",
                "name": "E-mini S&P 500",
                "month_codes": ["H", "M", "U", "Z"],
            },
        ),
        option_underlyings=("SPY",),
        yahoo_exchange_suffixes=(("LSE", ".L"),),
    )


def test_asset_reference_storage_is_generic_and_fail_closed(tmp_path) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    payload = store_asset_reference_component(
        values,
        asset_class=CandidateAssetClass.US_EQUITY,
        captured_at=NOW,
        config_fingerprint="us-equity-config",
        coverage=("XNYS", "XNAS"),
        records=({"symbol": "AAPL", "instrument_identifier": "alpaca:AAPL"},),
        metadata={"collector": "test-security-master"},
    )

    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    loaded = load_asset_reference_component(
        values,
        asset_class=CandidateAssetClass.US_EQUITY,
        as_of=NOW + timedelta(minutes=10),
        config_fingerprint="us-equity-config",
        coverage=("XNYS", "XNAS"),
    )
    assert loaded is not None
    assert loaded["records"][0]["symbol"] == "AAPL"

    path = asset_reference_component_path(values, CandidateAssetClass.US_EQUITY)
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["records"][0]["symbol"] = "MSFT"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert (
        load_asset_reference_component(
            values,
            asset_class=CandidateAssetClass.US_EQUITY,
            as_of=NOW + timedelta(minutes=10),
            config_fingerprint="us-equity-config",
            coverage=("XNYS", "XNAS"),
        )
        is None
    )


def test_lane_components_rebind_across_scheduling_cohorts(tmp_path) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    config = _config()
    equity = CandidateAssetClass.INTERNATIONAL_EQUITY
    future = CandidateAssetClass.FUTURE

    store_asset_reference_component(
        values,
        asset_class=equity,
        captured_at=NOW,
        config_fingerprint=_lane_config_fingerprint(config, equity),
        coverage=_lane_coverage(discovery, config, equity),
        records=({"symbol": "VOD.L", "asset_class": equity.value},),
    )
    store_asset_reference_component(
        values,
        asset_class=future,
        captured_at=NOW,
        config_fingerprint=_lane_config_fingerprint(config, future),
        coverage=_lane_coverage(discovery, config, future),
        records=({"symbol": "ESZ26", "asset_class": future.value},),
    )

    active_lanes = frozenset({equity, future})
    _prime_legacy_components(
        values=values,
        timestamp=NOW + timedelta(minutes=15),
        discovery=discovery,
        config=config,
        active_lanes=active_lanes,
    )

    active_names = tuple(sorted(item.value for item in active_lanes))
    full_fingerprint = legacy._fingerprint(legacy._config_material(config))
    directory = legacy._validated_component(
        path=legacy._component_path(values, legacy._DIRECTORY_COMPONENT),
        component=legacy._DIRECTORY_COMPONENT,
        timestamp=NOW + timedelta(minutes=15),
        values=values,
        config_fingerprint=full_fingerprint,
        active_lanes=active_names,
        coverage=config.eodhd_exchange_codes,
    )
    futures = legacy._validated_component(
        path=legacy._component_path(values, legacy._FUTURES_COMPONENT),
        component=legacy._FUTURES_COMPONENT,
        timestamp=NOW + timedelta(minutes=15),
        values=values,
        config_fingerprint=full_fingerprint,
        active_lanes=active_names,
        coverage=("ES",),
    )

    assert directory is not None
    assert directory["catalogs"][equity.value][0]["symbol"] == "VOD.L"
    assert futures is not None
    assert futures["catalogs"][future.value][0]["symbol"] == "ESZ26"
