"""Regression coverage for Twelve Data reference-endpoint response semantics."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from providers.twelve_data_reference import TwelveDataReferenceError
from providers.twelve_data_reference_runtime import (
    TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION,
    TwelveDataRuntimeReferenceProvider,
)


NOW = datetime(2026, 8, 4, 16, 45, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def query() -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol="HK",
        as_of=NOW,
        limit=1_000_000,
    )


def hk_row(index: int) -> dict[str, str]:
    return {
        "symbol": f"{index:04d}",
        "name": f"Hong Kong Issuer {index}",
        "currency": "HKD",
        "exchange": "Hong Kong Stock Exchange",
        "mic_code": "XHKG",
        "country": "Hong Kong",
        "type": "Common Stock",
    }


def provider(payload, *, page_size: int = 2, max_records: int = 10):
    calls: list[dict[str, object]] = []

    def get(_url, *, params, timeout):
        del timeout
        calls.append(dict(params))
        return Response(payload)

    return (
        TwelveDataRuntimeReferenceProvider(
            api_key="secret-key",
            http_get=get,
            clock=lambda: NOW,
            page_size=page_size,
            max_records=max_records,
        ),
        calls,
    )


def test_complete_exchange_response_may_exceed_requested_outputsize() -> None:
    rows = [hk_row(1), hk_row(2), hk_row(3)]
    runtime, calls = provider({"count": 3, "data": rows, "status": "ok"})

    snapshot = runtime.fetch_dataset(query())

    assert len(snapshot.payload["active"]) == 3
    assert snapshot.source_version == TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION
    assert [item["Code"] for item in snapshot.payload["active"]] == [
        "0001",
        "0002",
        "0003",
    ]
    assert len(calls) == 1
    assert calls[0]["mic_code"] == "XHKG"
    assert calls[0]["outputsize"] == 2
    assert any(
        "provider-count-certified response" in item
        for item in snapshot.limitations
    )
    assert not any(
        item.startswith("Raw pages were bounded to ")
        for item in snapshot.limitations
    )


def test_oversized_response_without_count_remains_fail_closed() -> None:
    rows = [hk_row(1), hk_row(2), hk_row(3)]
    runtime, _calls = provider({"data": rows, "status": "ok"})

    with pytest.raises(TwelveDataReferenceError, match="without an exact provider count"):
        runtime.fetch_dataset(query())


def test_oversized_response_count_mismatch_remains_fail_closed() -> None:
    rows = [hk_row(1), hk_row(2), hk_row(3)]
    runtime, _calls = provider({"count": 4, "data": rows, "status": "ok"})

    with pytest.raises(TwelveDataReferenceError, match="row count did not match"):
        runtime.fetch_dataset(query())


def test_unpaginated_response_respects_explicit_memory_bound() -> None:
    rows = [hk_row(1), hk_row(2), hk_row(3)]
    runtime, _calls = provider(
        {"count": 3, "data": rows, "status": "ok"},
        max_records=2,
    )

    with pytest.raises(TwelveDataReferenceError, match="memory safety bound"):
        runtime.fetch_dataset(query())


def test_record_outside_requested_mic_remains_fail_closed() -> None:
    rows = [hk_row(1), hk_row(2), hk_row(3)]
    rows[-1]["mic_code"] = "XNAS"
    runtime, _calls = provider({"count": 3, "data": rows, "status": "ok"})

    with pytest.raises(TwelveDataReferenceError, match="outside the requested exchange"):
        runtime.fetch_dataset(query())
