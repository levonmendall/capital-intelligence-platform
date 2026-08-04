from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "render.yaml"
CATALOG = ROOT / "config" / "public_live_information_sources.json"


def test_new_official_public_sources_are_declared() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    identifiers = {item["identifier"] for item in payload["sources"]}

    assert {
        "bls-labor-inflation-live",
        "nyfed-sofr-live",
        "treasury-yield-curve-live",
        "ecb-data-portal-live",
        "eurostat-gdp-live",
        "bea-national-accounts-live",
        "census-economic-indicators-live",
    } <= identifiers


def test_render_exposes_existing_bindings_and_optional_public_credentials() -> None:
    source = RENDER.read_text(encoding="utf-8")

    for key in (
        "CAPITAL_INTELLIGENCE_EODHD_BINDINGS",
        "CAPITAL_INTELLIGENCE_DATABENTO_INSTRUMENT_BINDINGS",
        "CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS",
        "OPENFIGI_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
        "TWELVE_DATA_API_KEY",
        "EIA_API_KEY",
        "NASA_FIRMS_MAP_KEY",
        "BEA_API_KEY",
        "CENSUS_API_KEY",
    ):
        assert f"- key: {key}" in source


def test_public_sources_remain_non_authoritative_for_capital() -> None:
    source = (
        ROOT / "public_live_collection_runtime.py"
    ).read_text(encoding="utf-8")

    assert '"decision_evidence_authority": False' in source
    assert '"execution_authority": False' in source
    assert '"real_money_authorized": False' in source
