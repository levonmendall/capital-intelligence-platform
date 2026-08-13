from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers import eodhd as eodhd
from providers import twelve_data_reference_rate_limited as rate_limited
from providers.catalog_reference_continuity import (
    TwelveDataCatalogContinuityProvider,
)
from providers.twelve_data_reference import TwelveDataReferenceError


NOW = datetime(2026, 8, 13, 4, 22, tzinfo=timezone.utc)


def _query(symbol: str) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol=symbol,
        as_of=NOW,
        limit=10_000,
    )


def _snapshot(
    query: ProviderDatasetQuery,
    *,
    provider: str = "Twelve Data",
) -> ProviderDatasetSnapshot:
    return ProviderDatasetSnapshot(
        query=query,
        provider=provider,
        source_version="test-reference.v1",
        observed_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        quality_state=DataQualityState.LIVE,
        availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
        payload={
            "active": [
                {
                    "Code": "7203",
                    "Name": "Toyota Motor",
                    "Exchange": query.provider_symbol,
                    "MIC": "XTKS",
                    "Currency": "JPY",
                    "CountryISO2": "JP",
                    "Type": "Common Stock",
                    "SourceProvider": "Twelve Data",
                }
            ],
            "delisted": [],
        },
        provider_record_id=f"test:{query.provider_symbol}",
        limitations=("test reference evidence",),
    )


class _Fallback:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        self.calls.append(query.provider_symbol)
        return _snapshot(query)


def test_normal_physical_market_adds_no_exchange_directory_preflight(monkeypatch) -> None:
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=_Fallback(),
    )

    def unexpected_base_fetch(*_args, **_kwargs):
        raise AssertionError("normal catalog retrieval must not add exchange-list I/O")

    monkeypatch.setattr(eodhd._base.EODHDProvider, "fetch_dataset", unexpected_base_fetch)
    monkeypatch.setattr(
        provider,
        "_active_symbol_directory",
        lambda symbol, **_kwargs: (
            [{"Code": "VOD", "Exchange": symbol, "Type": "Common Stock"}],
            DataQualityState.LIVE,
            None,
            (),
        ),
    )
    monkeypatch.setattr(provider, "_request", lambda *_args, **_kwargs: [])

    result = provider.fetch_dataset(_query("LSE"))

    assert result.provider == "EODHD"
    assert result.query.provider_symbol == "LSE"


def test_eodhd_404_preserves_requested_market_through_reference_fallback(
    monkeypatch,
) -> None:
    fallback = _Fallback()
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=fallback,
    )

    def unavailable(*_args, **_kwargs):
        raise eodhd.EODHDRetrievalFailure(
            resource="active symbol directory TSE",
            category="http_error",
            retryable=False,
            status_code=404,
        )

    monkeypatch.setattr(provider, "_active_symbol_directory", unavailable)

    result = provider.fetch_dataset(_query("TSE"))

    assert result.provider == "Twelve Data"
    assert result.query.provider_symbol == "TSE"
    assert fallback.calls == ["TSE"]


def test_non_continuity_eodhd_failure_remains_fail_closed(monkeypatch) -> None:
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=_Fallback(),
    )

    def unavailable(*_args, **_kwargs):
        raise eodhd.EODHDRetrievalFailure(
            resource="active symbol directory TSE",
            category="authentication_failed",
            retryable=False,
            status_code=401,
        )

    monkeypatch.setattr(provider, "_active_symbol_directory", unavailable)

    with pytest.raises(eodhd.EODHDRetrievalFailure, match="HTTP 401"):
        provider.fetch_dataset(_query("TSE"))


def test_stale_reference_continuity_is_used_only_after_final_429(monkeypatch) -> None:
    provider = TwelveDataCatalogContinuityProvider(
        api_key="test-key",
        cache_max_age_seconds=259_200,
        continuity_max_age_seconds=2_592_000,
    )
    query = _query("TSE")
    stale = _snapshot(query)
    continuity_calls: list[str] = []

    def rate_limited_fetch(self, _query):
        self._live_rate_limit_exhausted = True
        raise TwelveDataReferenceError("Twelve Data stock catalog returned HTTP 429")

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        rate_limited_fetch,
    )
    monkeypatch.setattr(
        provider,
        "_load_continuity_cached_snapshot",
        lambda item: continuity_calls.append(item.provider_symbol) or stale,
    )

    result = provider.fetch_dataset(query)

    assert result.quality_state is DataQualityState.CACHED
    assert continuity_calls == ["TSE"]
    assert any("30-day continuity window" in item for item in result.limitations)


def test_non_429_reference_failure_never_unlocks_stale_continuity(monkeypatch) -> None:
    provider = TwelveDataCatalogContinuityProvider(
        api_key="test-key",
        cache_max_age_seconds=259_200,
        continuity_max_age_seconds=2_592_000,
    )

    def provider_failure(_self, _query):
        raise TwelveDataReferenceError("catalog payload is invalid")

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "fetch_dataset",
        provider_failure,
    )
    monkeypatch.setattr(
        provider,
        "_load_continuity_cached_snapshot",
        lambda _query: (_ for _ in ()).throw(
            AssertionError("non-429 failures must remain fail-closed")
        ),
    )

    with pytest.raises(TwelveDataReferenceError, match="payload is invalid"):
        provider.fetch_dataset(_query("TSE"))


def test_continuity_loader_only_widens_age_and_restores_normal_ttl(monkeypatch) -> None:
    provider = TwelveDataCatalogContinuityProvider(
        api_key="test-key",
        cache_max_age_seconds=259_200,
        continuity_max_age_seconds=2_592_000,
    )
    query = _query("TSE")
    observed_ages: list[float] = []

    def fake_load(self, item):
        observed_ages.append(self.cache_max_age_seconds)
        return _snapshot(item)

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "_load_cached_snapshot",
        fake_load,
    )

    provider._load_continuity_cached_snapshot(query)

    assert observed_ages == [2_592_000]
    assert provider.cache_max_age_seconds == 259_200


def test_final_429_marker_is_set_by_wrapped_rate_limiter(monkeypatch) -> None:
    provider = TwelveDataCatalogContinuityProvider(api_key="test-key")

    class Response:
        status_code = 429

    monkeypatch.setattr(
        rate_limited.TwelveDataRateLimitedReferenceProvider,
        "_rate_limited_get",
        lambda *_args, **_kwargs: Response(),
    )

    provider._rate_limited_get(
        "https://example.invalid",
        params={"apikey": "redacted"},
        timeout=1,
    )
    assert provider._live_rate_limit_exhausted is True
