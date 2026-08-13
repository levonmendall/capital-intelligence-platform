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


def _query(
    symbol: str,
    dataset_type: ProviderDatasetType = ProviderDatasetType.SYMBOL_DIRECTORY,
) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=dataset_type,
        provider_symbol=symbol,
        as_of=NOW,
        limit=10_000,
    )


def _snapshot(
    query: ProviderDatasetQuery,
    *,
    provider: str = "Twelve Data",
    payload: object | None = None,
) -> ProviderDatasetSnapshot:
    if payload is None:
        payload = {
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
        }
    return ProviderDatasetSnapshot(
        query=query,
        provider=provider,
        source_version="test-reference.v1",
        observed_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        quality_state=DataQualityState.LIVE,
        availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
        payload=payload,
        provider_record_id=f"test:{query.provider_symbol}",
        limitations=("test reference evidence",),
    )


class _Fallback:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        self.calls.append(query.provider_symbol)
        return _snapshot(query)


def test_exchange_directory_parser_accepts_provider_code_shapes() -> None:
    assert eodhd._exchange_directory_codes(
        [
            {"Code": "LSE"},
            {"code": "PA"},
            {"ExchangeCode": "TSE"},
            {"exchange_code": "HK"},
        ]
    ) == frozenset({"LSE", "PA", "TSE", "HK"})
    assert eodhd._exchange_directory_codes({"unexpected": "shape"}) is None


def test_unadvertised_physical_market_routes_to_reference_without_direct_symbol_call(
    monkeypatch,
) -> None:
    fallback = _Fallback()
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=fallback,
    )
    base_calls: list[ProviderDatasetType] = []

    def fake_base_fetch(_self, query: ProviderDatasetQuery):
        base_calls.append(query.dataset_type)
        assert query.dataset_type is ProviderDatasetType.EXCHANGE_DIRECTORY
        return _snapshot(
            query,
            provider="EODHD",
            payload=[{"Code": "LSE"}, {"Code": "PA"}, {"Code": "HK"}],
        )

    monkeypatch.setattr(eodhd._base.EODHDProvider, "fetch_dataset", fake_base_fetch)
    monkeypatch.setattr(provider, "_load_directory_cache", lambda *_a, **_k: None)

    def unexpected_active(*_a, **_k):
        raise AssertionError("TSE must not spend a guaranteed-failing symbol request")

    monkeypatch.setattr(provider, "_active_symbol_directory", unexpected_active)

    result = provider.fetch_dataset(_query("TSE"))

    assert result.provider == "Twelve Data"
    assert fallback.calls == ["TSE"]
    assert base_calls == [ProviderDatasetType.EXCHANGE_DIRECTORY]
    assert any("market was preserved" in item for item in result.limitations)


def test_exchange_preflight_is_once_per_provider_and_advertised_market_stays_eodhd(
    monkeypatch,
) -> None:
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=_Fallback(),
    )
    base_calls: list[ProviderDatasetType] = []

    def fake_base_fetch(_self, query: ProviderDatasetQuery):
        base_calls.append(query.dataset_type)
        return _snapshot(
            query,
            provider="EODHD",
            payload=[{"Code": "LSE"}, {"Code": "PA"}],
        )

    monkeypatch.setattr(eodhd._base.EODHDProvider, "fetch_dataset", fake_base_fetch)
    monkeypatch.setattr(provider, "_load_directory_cache", lambda *_a, **_k: None)
    monkeypatch.setattr(
        provider,
        "_active_symbol_directory",
        lambda symbol, **_kwargs: (
            [{"Code": "ABC", "Exchange": symbol, "Type": "Common Stock"}],
            DataQualityState.LIVE,
            None,
            (),
        ),
    )
    monkeypatch.setattr(provider, "_request", lambda *_a, **_k: [])

    assert provider.fetch_dataset(_query("LSE")).provider == "EODHD"
    assert provider.fetch_dataset(_query("PA")).provider == "EODHD"
    assert base_calls == [ProviderDatasetType.EXCHANGE_DIRECTORY]


def test_exchange_preflight_failure_preserves_prior_direct_path(monkeypatch) -> None:
    provider = eodhd.EODHDProvider(
        api_token="test-token",
        clock=lambda: NOW,
        reference_provider=_Fallback(),
    )

    def unavailable_exchange_directory(_self, _query):
        raise eodhd.EODHDProviderError("exchange directory unavailable")

    monkeypatch.setattr(
        eodhd._base.EODHDProvider,
        "fetch_dataset",
        unavailable_exchange_directory,
    )
    monkeypatch.setattr(provider, "_load_directory_cache", lambda *_a, **_k: None)
    direct_calls: list[str] = []
    monkeypatch.setattr(
        provider,
        "_active_symbol_directory",
        lambda symbol, **_kwargs: (
            direct_calls.append(symbol)
            or (
                [{"Code": "ABC", "Exchange": symbol, "Type": "Common Stock"}],
                DataQualityState.LIVE,
                None,
                (),
            )
        ),
    )
    monkeypatch.setattr(provider, "_request", lambda *_a, **_k: [])

    assert provider.fetch_dataset(_query("LSE")).provider == "EODHD"
    assert direct_calls == ["LSE"]


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
        lambda *_a, **_k: Response(),
    )

    provider._rate_limited_get(
        "https://example.invalid",
        params={"apikey": "redacted"},
        timeout=1,
    )
    assert provider._live_rate_limit_exhausted is True
