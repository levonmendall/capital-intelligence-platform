from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.twelve_data_reference import TwelveDataReferenceError
from providers.twelve_data_reference_rate_limited import (
    TwelveDataRateLimitedReferenceProvider,
)


UTC = timezone.utc


def _query(as_of: datetime) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="HK",
        as_of=as_of,
        limit=100,
    )


def _snapshot(query: ProviderDatasetQuery, retrieved_at: datetime) -> ProviderDatasetSnapshot:
    return ProviderDatasetSnapshot(
        query=query,
        provider="Twelve Data",
        source_version="test-reference.v1",
        observed_at=retrieved_at,
        available_at=retrieved_at,
        retrieved_at=retrieved_at,
        quality_state=DataQualityState.FALLBACK,
        availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
        payload={
            "active": [
                {
                    "Code": "0005",
                    "Name": "Test Holdings",
                    "Exchange": "HK",
                    "MIC": "XHKG",
                    "Currency": "HKD",
                    "CountryISO2": "HK",
                    "Type": "Common Stock",
                    "Figi": "",
                    "CFI": "",
                    "ISIN": "",
                    "SourceProvider": "Twelve Data",
                }
            ],
            "delisted": [],
        },
        provider_record_id="twelve-data:test:HK",
        limitations=("Discovery only.",),
    )


def test_validated_cache_is_reused_with_cached_quality(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    now = retrieved_at + timedelta(minutes=10)
    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        cache_directory=tmp_path,
        clock=lambda: now,
    )
    original_query = _query(retrieved_at)
    provider._store_cached_snapshot(_snapshot(original_query, retrieved_at))

    cached = provider._load_cached_snapshot(_query(now))

    assert cached.quality_state is DataQualityState.CACHED
    assert cached.query.as_of == now
    assert cached.payload["active"][0]["Exchange"] == "HK"
    assert "discovery-only authority" in cached.limitations[-1]


def test_tampered_cached_payload_fails_closed(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    now = retrieved_at + timedelta(minutes=10)
    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        cache_directory=tmp_path,
        clock=lambda: now,
    )
    query = _query(retrieved_at)
    provider._store_cached_snapshot(_snapshot(query, retrieved_at))
    path = provider._cache_path(query)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["snapshot"]["payload"]["active"][0]["Code"] = "TAMPERED"
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(TwelveDataReferenceError, match="integrity"):
        provider._load_cached_snapshot(_query(now))


def test_expired_cached_catalog_fails_closed(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    now = retrieved_at + timedelta(minutes=2)
    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        cache_directory=tmp_path,
        cache_max_age_seconds=60,
        clock=lambda: now,
    )
    query = _query(retrieved_at)
    provider._store_cached_snapshot(_snapshot(query, retrieved_at))

    with pytest.raises(TwelveDataReferenceError, match="expired"):
        provider._load_cached_snapshot(_query(now))


def test_market_mismatch_in_cached_catalog_fails_closed(tmp_path) -> None:
    retrieved_at = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    now = retrieved_at + timedelta(minutes=10)
    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        cache_directory=tmp_path,
        clock=lambda: now,
    )
    query = _query(retrieved_at)
    snapshot = _snapshot(query, retrieved_at)
    provider._store_cached_snapshot(snapshot)
    path = provider._cache_path(query)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["snapshot"]["payload"]["active"][0]["Exchange"] = "SA"
    payload = record["snapshot"]["payload"]
    import hashlib

    record["snapshot"]["content_hash"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(TwelveDataReferenceError, match="outside the requested market"):
        provider._load_cached_snapshot(_query(now))
