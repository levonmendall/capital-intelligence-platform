from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4 as discovery
from operations import generalized_reference_readiness as generalized
from operations.certified_investable_catalog import load_certified_investable_catalog


CONFIG_PATH = Path("config/comprehensive_market_discovery.json")
WEEKDAY_CUTOFF = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)


def _missing_scheduled_eodhd_lanes(exchange_codes: tuple[str, ...]) -> tuple[str, ...]:
    active_lanes = discovery._base.scheduled_discovery_lanes(WEEKDAY_CUTOFF)
    required_lanes = active_lanes & generalized._EODHD_REFERENCE_LANES
    return tuple(
        lane.value
        for lane in sorted(required_lanes, key=lambda item: item.value)
        if not any(
            lane in discovery._possible_lanes_for_exchange(exchange)
            for exchange in exchange_codes
        )
    )


def test_eodhd_reference_partition_covers_only_free_configured_directory_lanes() -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    exchange_codes = tuple(str(item).strip().upper() for item in payload["eodhd_exchange_codes"])

    assert "CC" not in exchange_codes
    assert CandidateAssetClass.CRYPTO not in generalized._EODHD_REFERENCE_LANES
    assert CandidateAssetClass.FX in generalized._EODHD_REFERENCE_LANES
    assert _missing_scheduled_eodhd_lanes(exchange_codes) == ()


def test_crypto_remains_scheduled_through_certified_provider_neutral_catalog() -> None:
    active_lanes = discovery._base.scheduled_discovery_lanes(WEEKDAY_CUTOFF)
    records = load_certified_investable_catalog(as_of=WEEKDAY_CUTOFF)
    crypto = tuple(item for item in records if item["asset_class"] == CandidateAssetClass.CRYPTO.value)

    assert CandidateAssetClass.CRYPTO in active_lanes
    assert crypto
    assert all(item["provider_kind"] == "yahoo" for item in crypto)
    assert all(item["instrument_identifier"] for item in crypto)
