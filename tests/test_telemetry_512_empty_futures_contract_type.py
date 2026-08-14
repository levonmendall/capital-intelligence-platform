from __future__ import annotations

from datetime import datetime, timezone

import pytest

from providers.massive_futures_reference_bounded import MassiveFuturesReferenceProvider
from providers.massive_multi_asset import MassiveMultiAssetError


class _FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers: dict[str, str] = {}
        self.text = ""

    def json(self) -> object:
        return self._payload


class _SequentialGet:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, url: str, *, params: dict[str, object], timeout: int):
        self.calls.append((url, dict(params)))
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def _contract(*, ticker: str, contract_type: object) -> dict[str, object]:
    return {
        "ticker": ticker,
        "product_code": "ES",
        "trading_venue": "XCME",
        "first_trade_date": "2026-06-19",
        "last_trade_date": "2026-09-18",
        "settlement_date": "2026-09-18",
        "active": True,
        "type": contract_type,
    }


def _provider(responses: list[_FakeResponse]) -> tuple[MassiveFuturesReferenceProvider, _SequentialGet]:
    getter = _SequentialGet(responses)
    provider = MassiveFuturesReferenceProvider(
        api_key="super-secret-key",
        http_get=getter,
        sleeper=lambda _: None,
        minimum_call_interval_seconds=0,
        reference_max_attempts=1,
        reference_clock=lambda: datetime(2026, 8, 14, 2, 10, tzinfo=timezone.utc),
    )
    return provider, getter


def test_empty_single_index_retries_untyped_and_rejects_explicit_combo() -> None:
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {
                    "results": [
                        _contract(ticker="ESU6-ESZ6", contract_type="combo"),
                        _contract(ticker="ESU6", contract_type=""),
                    ]
                },
            ),
        ]
    )

    contracts = provider.futures_contracts(
        as_of=datetime(2026, 8, 14, 2, 5, tzinfo=timezone.utc),
        product_codes=("ES",),
        maximum_pages=1,
    )

    assert [contract.ticker for contract in contracts] == ["ESU6"]
    assert len(getter.calls) == 4
    assert getter.calls[2][1]["type"] == "single"
    assert "type" not in getter.calls[3][1]
    assert getter.calls[3][1]["product_code"] == "ES"

    telemetry = provider.reference_telemetry[0]
    assert telemetry["query_mode"] == "current_untyped_index_with_local_contract_type_validation"
    assert telemetry["untyped_empty_retry_used"] is True
    assert telemetry["server_side_contract_type_bound"] is False
    assert telemetry["local_contract_type_validation"] is True
    assert telemetry["provider_raw_result_count"] == 2
    assert telemetry["contract_type_rejected_count"] == 1
    assert telemetry["raw_result_count"] == 1
    assert telemetry["usable_count"] == 1
    assert telemetry["failure_reason"] == "ok"
    assert "type" not in telemetry["request_params"]
    assert "apiKey" not in telemetry["request_params"]
    assert "super-secret-key" not in repr(telemetry)


def test_untyped_retry_does_not_admit_combo_only_coverage() -> None:
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {"results": [_contract(ticker="ESU6-ESZ6", contract_type="combo")]},
            ),
        ]
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 14, 2, 5, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert "did not establish complete configured-root coverage: ES" in str(raised.value)
    assert len(getter.calls) == 4
    telemetry = provider.reference_telemetry[0]
    assert telemetry["provider_raw_result_count"] == 1
    assert telemetry["contract_type_rejected_count"] == 1
    assert telemetry["raw_result_count"] == 0
    assert telemetry["usable_count"] == 0
    assert telemetry["failure_reason"] == "empty_current_fallback_response"


def test_untyped_retry_keeps_pagination_completeness_fail_closed() -> None:
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {
                    "results": [_contract(ticker="ESU6", contract_type=None)],
                    "next_url": "https://api.massive.com/futures/v1/contracts?cursor=next",
                },
            ),
        ]
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 14, 2, 5, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert "pagination exceeded" in str(raised.value)
    assert len(getter.calls) == 4
    telemetry = provider.reference_telemetry[0]
    assert telemetry["failure_reason"] == "pagination_incomplete"
    assert telemetry["usable_count"] == 1
    assert telemetry["local_contract_type_validation"] is True
