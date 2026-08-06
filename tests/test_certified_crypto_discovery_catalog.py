from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cio import CandidateAssetClass
from operations.certified_investable_catalog import (
    CRYPTO_VENUE_BINDINGS_ENV,
    CertifiedInvestableCatalogError,
    load_certified_investable_catalog,
)
from operations.comprehensive_market_discovery import _merge_certified_catalog


AS_OF = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
EXPECTED_SYMBOLS = {
    "ADAUSD",
    "BTCUSD",
    "DOGEUSD",
    "ETHUSD",
    "LINKUSD",
    "LTCUSD",
    "SOLUSD",
    "XRPUSD",
}


def test_default_crypto_catalog_is_complete_and_multi_venue(monkeypatch) -> None:
    monkeypatch.delenv(CRYPTO_VENUE_BINDINGS_ENV, raising=False)

    records = load_certified_investable_catalog(as_of=AS_OF)
    crypto = tuple(item for item in records if item["asset_class"] == "crypto")

    assert {str(item["symbol"]) for item in crypto} == EXPECTED_SYMBOLS
    assert {
        str(item["instrument_identifier"])
        for item in crypto
    } == {f"instrument:crypto:{symbol.lower()}" for symbol in EXPECTED_SYMBOLS}
    assert all(item["provider_kind"] == "yahoo" for item in crypto)
    assert all(item["venue"] == "COINBASE_KRAKEN" for item in crypto)
    assert all("coinbase=" in str(item["source_identifier"]) for item in crypto)
    assert all("kraken=" in str(item["source_identifier"]) for item in crypto)


def test_crypto_catalog_enters_required_discovery_lane(monkeypatch) -> None:
    monkeypatch.delenv(CRYPTO_VENUE_BINDINGS_ENV, raising=False)

    merged = _merge_certified_catalog({}, as_of=AS_OF)
    crypto = merged[CandidateAssetClass.CRYPTO]

    assert {item.symbol for item in crypto} == EXPECTED_SYMBOLS
    assert all(item.instrument_identifier for item in crypto)
    assert all(item.instrument_type == "spot" for item in crypto)
    assert all(item.provider_kind == "yahoo" for item in crypto)


def test_configured_crypto_catalog_absence_fails_closed(
    monkeypatch,
    tmp_path,
) -> None:
    missing = tmp_path / "missing-crypto-bindings.json"
    monkeypatch.setenv(CRYPTO_VENUE_BINDINGS_ENV, str(missing))

    with pytest.raises(
        CertifiedInvestableCatalogError,
        match="certified multi-venue crypto catalog is unavailable",
    ):
        load_certified_investable_catalog(as_of=AS_OF)


def test_malformed_crypto_binding_fails_closed(monkeypatch, tmp_path) -> None:
    path = tmp_path / "crypto-bindings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "crypto-venue-bindings.v1",
                "bindings": [
                    {
                        "instrument_id": "instrument:crypto:btcusd",
                        "quote_currency": "USD",
                        "coinbase_product_id": "BTC-EUR",
                        "kraken_symbol": "XBT/USD",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(CRYPTO_VENUE_BINDINGS_ENV, str(path))

    with pytest.raises(
        CertifiedInvestableCatalogError,
        match="BASE-QUOTE Coinbase product",
    ):
        load_certified_investable_catalog(as_of=AS_OF)
