from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4 as discovery
from operations import generalized_reference_readiness as generalized


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


def test_production_eodhd_configuration_covers_every_scheduled_reference_lane() -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    exchange_codes = tuple(str(item).strip().upper() for item in payload["eodhd_exchange_codes"])

    assert "CC" in exchange_codes
    assert _missing_scheduled_eodhd_lanes(exchange_codes) == ()


def test_crypto_lane_contract_fails_when_cc_directory_is_removed() -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    exchange_codes = tuple(
        str(item).strip().upper()
        for item in payload["eodhd_exchange_codes"]
        if str(item).strip().upper() != "CC"
    )

    assert _missing_scheduled_eodhd_lanes(exchange_codes) == (
        CandidateAssetClass.CRYPTO.value,
    )
