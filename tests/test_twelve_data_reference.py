"""Regression coverage for the Twelve Data global equity reference catalog."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.observation import DataQualityState
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.twelve_data_reference import (
    TwelveDataReferenceError,
    TwelveDataReferenceProvider,
)


NOW = datetime(2026, 8, 4, 15, 10, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def query(exchange: str) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol=exchange,
        as_of=NOW,
        limit=1_000_000,
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
        "figi_code": "BBG000BVPV84",
        "cfi_code": "ESVUFR",
    }


def lse_row():
    return {
        "symbol": "VOD",
        "name": "Vodafone Group Plc",
        "currency": "GBP",
        "exchange": "London Stock Exchange",
        "mic_code": "XLON",
        "country": "United Kingdom",
        "type": "Common Stock",
    }


def us_row():
    return {
        "symbol": "AAPL",
        "name": "Apple Inc",
        "currency": "USD",
        "exchange": "NASDAQ",
        "mic_code": "XNGS",
        "country": "United States",
        "type": "Common Stock",
    }


def test_global_catalog_is_fully_paginated_and_reused_across_exchanges() -> None:
    calls: list[dict[str, object]] = []
    responses = [
        Response({"count": 3, "data": [hk_row(), lse_row()], "status": "ok"}),
        Response({"count": 3, "data": [us_row()], "status": "ok"}),
        Response({"count": 3, "data": [], "status": "ok"}),
    ]

    def get(_url, *, params, timeout):
        del timeout
        calls.append(dict(params))
        return responses.pop(0)

    provider = TwelveDataReferenceProvider(
        api_key="secret-key",
        http_get=get,
        clock=lambda: NOW,
        page_size=2,
        max_pages=10,
    )

    hk_snapshot = provider.fetch_dataset(query("HK"))
    lse_snapshot = provider.fetch_dataset(query("LSE"))

    assert hk_snapshot.provider == "Twelve Data"
    assert hk_snapshot.quality_state is DataQualityState.FALLBACK
    assert hk_snapshot.payload["active"][0]["Code"] == "0005"
    assert hk_snapshot.payload["active"][0]["CountryISO2"] == "HK"
    assert hk_snapshot.payload["active"][0]["Exchange"] == "HK"
    assert hk_snapshot.payload["delisted"] == []
    assert lse_snapshot.payload["active"][0]["Code"] == "VOD"
    assert lse_snapshot.payload["active"][0]["CountryISO2"] == "GB"
    assert [item["page"] for item in calls] == [1, 2, 3]
    assert all(item["include_delisted"] == "false" for item in calls)
    assert all(item["apikey"] == "secret-key" for item in calls)


def test_country_fallback_is_used_only_for_certified_single_market_selector() -> None:
    rows = [
        {
            "symbol": "0700",
            "name": "Tencent Holdings",
            "currency": "HKD",
            "exchange": "Unknown Hong Kong Venue",
            "mic_code": "",
            "country": "HK",
            "type": "Common Stock",
        }
    ]
    responses = [
        Response({"count": 1, "data": rows, "status": "ok"}),
        Response({"count": 1, "data": [], "status": "ok"}),
    ]

    provider = TwelveDataReferenceProvider(
        api_key="secret-key",
        http_get=lambda *_args, **_kwargs: responses.pop(0),
        clock=lambda: NOW,
        page_size=5_000,
    )

    snapshot = provider.fetch_dataset(query("HK"))
    assert snapshot.payload["active"][0]["Code"] == "0700"


def test_missing_reference_credential_remains_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("TWELVE_API_KEY", raising=False)
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)

    with pytest.raises(TwelveDataReferenceError, match="is not configured"):
        TwelveDataReferenceProvider(api_key=None).fetch_dataset(query("HK"))


def test_unsupported_virtual_directory_remains_fail_closed() -> None:
    provider = TwelveDataReferenceProvider(api_key="secret-key")

    with pytest.raises(TwelveDataReferenceError, match="no Twelve Data reference selector"):
        provider.fetch_dataset(query("CC"))


def test_repeated_page_cannot_be_certified_as_complete() -> None:
    page = {"count": 4, "data": [hk_row(), lse_row()], "status": "ok"}
    responses = [Response(page), Response(page)]

    provider = TwelveDataReferenceProvider(
        api_key="secret-key",
        http_get=lambda *_args, **_kwargs: responses.pop(0),
        clock=lambda: NOW,
        page_size=2,
        max_pages=10,
    )

    with pytest.raises(TwelveDataReferenceError, match="repeated a prior page"):
        provider.fetch_dataset(query("HK"))


def test_reported_count_cannot_exceed_completed_pagination() -> None:
    responses = [
        Response({"count": 10, "data": [hk_row()], "status": "ok"}),
        Response({"count": 10, "data": [], "status": "ok"}),
    ]
    provider = TwelveDataReferenceProvider(
        api_key="secret-key",
        http_get=lambda *_args, **_kwargs: responses.pop(0),
        clock=lambda: NOW,
    )

    with pytest.raises(TwelveDataReferenceError, match="before the reported count"):
        provider.fetch_dataset(query("HK"))


def test_http_failure_diagnostic_does_not_disclose_api_key() -> None:
    provider = TwelveDataReferenceProvider(
        api_key="super-secret-value",
        http_get=lambda *_args, **_kwargs: Response({}, status_code=401),
        clock=lambda: NOW,
    )

    with pytest.raises(TwelveDataReferenceError) as captured:
        provider.fetch_dataset(query("HK"))

    detail = str(captured.value)
    assert "HTTP 401" in detail
    assert "super-secret-value" not in detail
