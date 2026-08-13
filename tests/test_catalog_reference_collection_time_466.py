from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers import twelve_data_reference_rate_limited as rate_limited
from providers.catalog_reference_continuity import (
    TwelveDataCatalogContinuityProvider,
)
from providers.twelve_data_reference import TwelveDataReferenceError


NOW = datetime(2026, 8, 13, 5, 35, tzinfo=timezone.utc)
OLD = NOW - timedelta(minutes=17)


def _query(*, as_of: datetime = OLD) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="FOREX",
        as_of=as_of,
        limit=10_000,
    )


def _snapshot(
    query: ProviderDatasetQuery,
    *,
    quality_state: DataQualityState = DataQualityState.FALLBACK,
) -> ProviderDatasetSnapshot:
    return ProviderDatasetSnapshot(
        query=query,
        provider="Twelve Data",
        source_version="twelve-data-reference.v5-forex-components",
        observed_at=query.as_of,
        available_at=query.as_of,
        retrieved_at=query.as_of,
        quality_state=quality_state,
        availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
        payload={
            "active": [
                {
                    "Code": "EUR/USD",
                    "Name": "EUR / USD",
                    "Exchange": "FOREX",
                    "MIC": "",
                    "Currency": "USD",
                    "CountryISO2": "GLOBAL",
                    "Type": "Currency",
                    "SourceProvider": "Twelve Data",
                }
            ],
            "delisted": [],
        },
        provider_record_id="test:forex",
        limitations=("test reference evidence",),
    )


def _provider() -> TwelveDataCatalogContinuityProvider:
    return TwelveDataCatalogContinuityProvider(
        api_key="test-key",
        clock=lambda: NOW,
        cache_max_age_seconds=259_200,
        continuity_max_age_seconds=2_592_000,
        minimum_request_interval_seconds=0,
    )


def test_delayed_live_reference_uses_collection_time_without_backdating(monkeypatch) -> None:
    provider = _provider()
    original = _query()
    seen: list[ProviderDatasetQuery] = []

    monkeypatch.setattr(
        provider,
        "_load_cached_snapshot",
        lambda _query: (_ for _ in ()).throw(
            TwelveDataReferenceError("cached catalog is expired")
        ),
    )

    def live_fetch(self, query):
        seen.append(query)
        return _snapshot(query)

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        live_fetch,
    )

    result = provider.fetch_dataset(original)

    assert seen == [seen[0]]
    assert seen[0].provider_symbol == "FOREX"
    assert seen[0].as_of == NOW
    assert result.query.as_of == NOW
    assert result.available_at == NOW
    assert any(OLD.isoformat() in item for item in result.limitations)
    assert any("not backdated" in item for item in result.limitations)
    assert any("discovery identity only" in item for item in result.limitations)


def test_original_cutoff_cache_is_checked_before_collection_time_is_advanced(monkeypatch) -> None:
    provider = _provider()
    original = _query()
    cached = _snapshot(original, quality_state=DataQualityState.CACHED)
    live_calls: list[str] = []

    monkeypatch.setattr(provider, "_load_cached_snapshot", lambda query: cached)

    def unexpected_live(self, query):
        live_calls.append(query.provider_symbol)
        raise AssertionError("valid original-cutoff cache must prevent live collection")

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        unexpected_live,
    )

    result = provider.fetch_dataset(original)

    assert result is cached
    assert result.query.as_of == OLD
    assert live_calls == []


def test_stale_on_429_continuity_uses_collection_time_query(monkeypatch) -> None:
    provider = _provider()
    original = _query()
    live_queries: list[ProviderDatasetQuery] = []
    continuity_queries: list[ProviderDatasetQuery] = []

    monkeypatch.setattr(
        provider,
        "_load_cached_snapshot",
        lambda _query: (_ for _ in ()).throw(
            TwelveDataReferenceError("cached catalog is expired")
        ),
    )

    def rate_limited_fetch(self, query):
        live_queries.append(query)
        self._live_rate_limit_exhausted = True
        raise TwelveDataReferenceError("Twelve Data forex catalog returned HTTP 429")

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        rate_limited_fetch,
    )

    def stale_snapshot(query):
        continuity_queries.append(query)
        return _snapshot(query, quality_state=DataQualityState.CACHED)

    monkeypatch.setattr(provider, "_load_continuity_cached_snapshot", stale_snapshot)

    result = provider.fetch_dataset(original)

    assert live_queries[0].as_of == NOW
    assert continuity_queries[0].as_of == NOW
    assert result.quality_state is DataQualityState.CACHED
    assert result.query.as_of == NOW
    assert any("30-day continuity window" in item for item in result.limitations)
    assert any("not backdated" in item for item in result.limitations)


def test_collection_time_never_moves_a_future_cutoff_backward(monkeypatch) -> None:
    future_cutoff = NOW + timedelta(minutes=1)
    provider = _provider()
    original = _query(as_of=future_cutoff)
    seen: list[ProviderDatasetQuery] = []

    monkeypatch.setattr(
        provider,
        "_load_cached_snapshot",
        lambda _query: (_ for _ in ()).throw(TwelveDataReferenceError("no cache")),
    )

    def live_fetch(self, query):
        seen.append(query)
        return _snapshot(query)

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        live_fetch,
    )

    result = provider.fetch_dataset(original)

    assert seen[0].as_of == future_cutoff
    assert result.query.as_of == future_cutoff
    assert not any("not backdated" in item for item in result.limitations)
