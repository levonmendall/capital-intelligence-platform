from __future__ import annotations

from pathlib import Path

from providers.public_live_source_catalogs import load_operating_public_live_source_catalog


ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "render.yaml"
CATALOG = ROOT / "config" / "public_live_information_sources.json"


def test_new_official_public_sources_are_declared() -> None:
    catalog = load_operating_public_live_source_catalog(CATALOG)
    identifiers = {item.identifier for item in catalog.sources}

    assert len(catalog.sources) >= 41
    assert {
        "bls-labor-inflation-live",
        "nyfed-sofr-live",
        "treasury-yield-curve-live",
        "ecb-data-portal-live",
        "eurostat-gdp-live",
        "bea-national-accounts-live",
        "census-economic-indicators-live",
        "bank-of-england-news-live",
        "bank-of-japan-live",
        "bank-of-canada-live",
        "snb-monetary-policy-live",
        "bis-statistics-releases-live",
        "eurostat-statistics-updates-live",
        "bls-unemployment-live",
        "bls-payrolls-live",
        "ecb-deposit-facility-rate-live",
        "eurostat-hicp-live",
        "oecd-leading-indicators-live",
        "usda-crop-production-live",
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
        "USDA_NASS_API_KEY",
    ):
        assert f"- key: {key}" in source


def test_public_sources_remain_non_authoritative_for_capital() -> None:
    source = (
        ROOT / "public_live_collection_runtime.py"
    ).read_text(encoding="utf-8")

    assert '"decision_evidence_authority": False' in source
    assert '"execution_authority": False' in source
    assert '"real_money_authorized": False' in source
