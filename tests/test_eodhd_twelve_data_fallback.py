"""Regression coverage for uncached EODHD directory reference failover."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import (
    EODHDBindingRegistry,
    EODHDProvider,
    EODHDProviderError,
    EODHDRetrievalPolicy,
)
from providers.twelve_data_reference import TwelveDataReferenceProvider


NOW = datetime(2026, 8, 4, 15, 15, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def query(exchange: str = "HK") -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol=exchange,
        as_of=NOW,
        limit=1_000_000,
    )


def reference_provider(responses) -> TwelveDataReferenceProvider:
    queue = list(responses)

    def get(_url, *, params, timeout):
        del params, timeout
        return queue.pop(0)

    return TwelveDataReferenceProvider(
        api_key="twelve-secret",
        http_get=get,
        clock=lambda: NOW,
        page_size=5_000,
    )


def eodhd_provider(
    *,
    cache_dir: Path,
    eodhd_response: Response,
    fallback: TwelveDataReferenceProvider | None,
) -> EODHDProvider:
    return EODHDProvider(
        api_token="eodhd-secret",
        bindings=EODHDBindingRegistry(()),
        http_get=lambda *_args, **_kwargs: eodhd_response,
        clock=lambda: NOW,
        sleeper=lambda _: None,
        retrieval_policy=EODHDRetrievalPolicy(max_attempts=1),
        directory_cache_dir=cache_dir,
        directory_cache_max_age=timedelta(hours=72),
        reference_provider=fallback,
    )


def hk_row():
    return {
        "symbol": "0005",
        "name": "HSBC Holdings plc",
        "currency": "HKD",
        "exchange": "Hong Kong Stock Exchange",
        "mic_code": "XHKG",
        "country": "Hong Kong",
        "type": "Common Stock",
    }


def tokyo_row():
    return {
        "symbol": "7203",
        "name": "Toyota Motor Corporation",
        "currency": "JPY",
        "exchange": "Tokyo Stock Exchange",
        "mic_code": "XJPX",
        "country": "Japan",
        "type": "Common Stock",
    }


def test_uncached_http_402_uses_independent_twelve_data_reference(
    tmp_path: Path,
) -> None:
    fallback = reference_provider(
        [
            Response({"count": 1, "data": [hk_row()], "status": "ok"}),
            Response({"count": 1, "data": [], "status": "ok"}),
        ]
    )
    provider = eodhd_provider(
        cache_dir=tmp_path,
        eodhd_response=Response({}, 402),
        fallback=fallback,
    )

    snapshot = provider.fetch_dataset(query())

    assert snapshot.provider == "Twelve Data"
    assert snapshot.quality_state is DataQualityState.FALLBACK
    assert snapshot.payload["active"][0]["Code"] == "0005"
    assert snapshot.payload["active"][0]["Exchange"] == "HK"
    assert snapshot.provider_record_id.startswith(
        "twelve-data:stocks-reference:HK:"
    )
    assert any("discovery authority only" in item for item in snapshot.limitations)


def test_uncached_http_404_uses_certified_tokyo_reference(
    tmp_path: Path,
) -> None:
    fallback = reference_provider(
        [Response({"count": 1, "data": [tokyo_row()], "status": "ok"})]
    )
    provider = eodhd_provider(
        cache_dir=tmp_path,
        eodhd_response=Response({}, 404),
        fallback=fallback,
    )

    snapshot = provider.fetch_dataset(query("TSE"))

    assert snapshot.provider == "Twelve Data"
    assert snapshot.quality_state is DataQualityState.FALLBACK
    assert snapshot.payload["active"][0]["Code"] == "7203"
    assert snapshot.payload["active"][0]["Exchange"] == "TSE"
    assert snapshot.payload["active"][0]["CountryISO2"] == "JP"
    assert snapshot.provider_record_id.startswith(
        "twelve-data:stocks-reference:TSE:"
    )


def test_non_directory_continuity_failure_does_not_route_to_reference_provider(
    tmp_path: Path,
) -> None:
    fallback = reference_provider(
        [
            Response({"count": 1, "data": [hk_row()], "status": "ok"}),
            Response({"count": 1, "data": [], "status": "ok"}),
        ]
    )
    provider = eodhd_provider(
        cache_dir=tmp_path,
        eodhd_response=Response({}, 403),
        fallback=fallback,
    )

    with pytest.raises(EODHDProviderError, match="HTTP 403.*non-retryable"):
        provider.fetch_dataset(query())


def test_http_402_and_unavailable_reference_remain_fail_closed(
    tmp_path: Path,
) -> None:
    provider = eodhd_provider(
        cache_dir=tmp_path,
        eodhd_response=Response({}, 402),
        fallback=TwelveDataReferenceProvider(api_key=None, clock=lambda: NOW),
    )

    with pytest.raises(
        EODHDProviderError,
        match="HTTP 402.*Twelve Data reference fallback is unavailable",
    ):
        provider.fetch_dataset(query())


@pytest.mark.parametrize("status_code", (402, 404))
def test_virtual_market_without_certified_reference_selector_stays_closed(
    tmp_path: Path,
    status_code: int,
) -> None:
    provider = eodhd_provider(
        cache_dir=tmp_path,
        eodhd_response=Response({}, status_code),
        fallback=TwelveDataReferenceProvider(
            api_key="twelve-secret",
            clock=lambda: NOW,
        ),
    )

    with pytest.raises(EODHDProviderError, match="no Twelve Data reference selector"):
        provider.fetch_dataset(query("CC"))
