"""Regression coverage for certified Twelve Data FOREX reference fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.eodhd import (
    EODHDBindingRegistry,
    EODHDProvider,
    EODHDRetrievalPolicy,
)
from providers.twelve_data_reference import TwelveDataReferenceError
from providers.twelve_data_reference_runtime import (
    TwelveDataRuntimeReferenceProvider,
)


NOW = datetime(2026, 8, 4, 17, 52, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def forex_query() -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="FOREX",
        as_of=NOW,
        limit=1_000_000,
    )


def forex_rows():
    return [
        {
            "symbol": "EUR/USD",
            "currency_group": "Major",
            "currency_base": "EUR",
            "currency_quote": "USD",
        },
        {
            "symbol": "USD/JPY",
            "currency_group": "Major",
            "currency_base": "USD",
            "currency_quote": "JPY",
        },
    ]


def runtime_provider(payload) -> TwelveDataRuntimeReferenceProvider:
    requests = []

    def get(url, *, params, timeout):
        requests.append((url, params, timeout))
        return Response(payload)

    provider = TwelveDataRuntimeReferenceProvider(
        api_key="twelve-secret",
        http_get=get,
        clock=lambda: NOW,
    )
    provider.requests = requests  # type: ignore[attr-defined]
    return provider


def test_count_certified_forex_catalog_is_normalized_for_discovery() -> None:
    provider = runtime_provider(
        {"count": 2, "data": forex_rows(), "status": "ok"}
    )

    snapshot = provider.fetch_dataset(forex_query())

    assert snapshot.provider == "Twelve Data"
    assert snapshot.quality_state is DataQualityState.FALLBACK
    assert snapshot.provider_record_id.startswith(
        "twelve-data:forex-reference:FOREX:"
    )
    assert [item["Code"] for item in snapshot.payload["active"]] == [
        "EUR/USD",
        "USD/JPY",
    ]
    assert snapshot.payload["active"][0]["Exchange"] == "FOREX"
    assert snapshot.payload["active"][0]["Type"] == "Currency"
    assert snapshot.payload["active"][0]["Currency"] == "USD"
    assert any("discovery authority only" in item for item in snapshot.limitations)
    request_url, params, timeout = provider.requests[0]  # type: ignore[attr-defined]
    assert request_url.endswith("/forex_pairs")
    assert params == {"apikey": "twelve-secret", "format": "JSON"}
    assert timeout == 30


def test_forex_catalog_count_mismatch_remains_fail_closed() -> None:
    provider = runtime_provider(
        {"count": 3, "data": forex_rows(), "status": "ok"}
    )

    with pytest.raises(TwelveDataReferenceError, match="row count.*provider count"):
        provider.fetch_dataset(forex_query())


def test_forex_catalog_duplicate_pair_remains_fail_closed() -> None:
    rows = forex_rows()
    rows.append(dict(rows[0]))
    provider = runtime_provider({"count": 3, "data": rows, "status": "ok"})

    with pytest.raises(TwelveDataReferenceError, match="duplicate pair EUR/USD"):
        provider.fetch_dataset(forex_query())


def test_forex_catalog_component_mismatch_remains_fail_closed() -> None:
    rows = forex_rows()
    rows[0] = {**rows[0], "currency_quote": "JPY"}
    provider = runtime_provider({"count": 2, "data": rows, "status": "ok"})

    with pytest.raises(TwelveDataReferenceError, match="components do not match"):
        provider.fetch_dataset(forex_query())


def test_eodhd_http_402_forex_uses_certified_runtime_reference(
    tmp_path: Path,
) -> None:
    fallback = runtime_provider(
        {"count": 2, "data": forex_rows(), "status": "ok"}
    )
    provider = EODHDProvider(
        api_token="eodhd-secret",
        bindings=EODHDBindingRegistry(()),
        http_get=lambda *_args, **_kwargs: Response({}, 402),
        clock=lambda: NOW,
        sleeper=lambda _: None,
        retrieval_policy=EODHDRetrievalPolicy(max_attempts=1),
        directory_cache_dir=tmp_path,
        directory_cache_max_age=timedelta(hours=72),
        reference_provider=fallback,
    )

    snapshot = provider.fetch_dataset(forex_query())

    assert snapshot.provider == "Twelve Data"
    assert snapshot.quality_state is DataQualityState.FALLBACK
    assert snapshot.payload["active"][0]["Exchange"] == "FOREX"
    assert snapshot.payload["active"][0]["Code"] == "EUR/USD"
