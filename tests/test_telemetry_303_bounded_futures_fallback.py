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


def _provider(
    responses: list[_FakeResponse],
    *,
    now: datetime,
) -> tuple[MassiveFuturesReferenceProvider, _SequentialGet]:
    getter = _SequentialGet(responses)
    provider = MassiveFuturesReferenceProvider(
        api_key="super-secret-key",
        http_get=getter,
        sleeper=lambda _: None,
        minimum_call_interval_seconds=0,
        reference_max_attempts=1,
        reference_clock=lambda: now,
    )
    return provider, getter


def _valid_es_contract() -> dict[str, object]:
    return {
        "ticker": "ESU6",
        "product_code": "ES",
        "trading_venue": "XCME",
        "first_trade_date": "2026-06-19",
        "last_trade_date": "2026-09-18",
        "settlement_date": "2026-09-18",
        "active": True,
        "type": "single",
    }


def _expired_es_contract() -> dict[str, object]:
    return {
        "ticker": "ESM6",
        "product_code": "ES",
        "trading_venue": "XCME",
        "first_trade_date": "2025-12-19",
        "last_trade_date": "2026-06-19",
        "settlement_date": "2026-06-19",
        "active": False,
        "type": "single",
    }


def test_current_fallback_is_server_bounded_before_pagination() -> None:
    as_of = datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": [_valid_es_contract()]}),
        ],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    contracts = provider.futures_contracts(
        as_of=as_of,
        product_codes=("ES",),
        maximum_pages=1,
    )

    assert [contract.ticker for contract in contracts] == ["ESU6"]
    assert len(getter.calls) == 2

    strict_params = getter.calls[0][1]
    fallback_params = getter.calls[1][1]
    assert strict_params["date"] == "2026-08-14"
    assert "type" not in strict_params
    assert fallback_params["product_code"] == "ES"
    assert fallback_params["active"] == "true"
    assert fallback_params["type"] == "single"
    assert "date" not in fallback_params
    assert fallback_params["first_trade_date.lte"] == "2026-08-14"
    assert fallback_params["last_trade_date.gte"] == "2026-08-14"

    telemetry = provider.reference_telemetry[0]
    assert telemetry["query_mode"] == "current_active_single_trade_window_without_date"
    assert telemetry["server_side_point_in_time_bound"] is True
    assert telemetry["server_side_contract_type_bound"] is True
    assert telemetry["bounded_empty_retry_used"] is False
    assert telemetry["request_params"]["first_trade_date.lte"] == "2026-08-14"
    assert telemetry["request_params"]["last_trade_date.gte"] == "2026-08-14"
    assert telemetry["request_params"]["type"] == "single"
    assert telemetry["usable_count"] == 1
    assert telemetry["failure_reason"] == "ok"
    assert "apiKey" not in telemetry["request_params"]
    assert "super-secret-key" not in repr(telemetry)


def test_empty_bounded_query_retries_single_index_with_local_point_in_time_filter() -> None:
    as_of = datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {"results": [_expired_es_contract(), _valid_es_contract()]},
            ),
        ],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    contracts = provider.futures_contracts(
        as_of=as_of,
        product_codes=("ES",),
        maximum_pages=1,
    )

    assert [contract.ticker for contract in contracts] == ["ESU6"]
    assert len(getter.calls) == 3

    bounded_params = getter.calls[1][1]
    index_params = getter.calls[2][1]
    assert bounded_params["active"] == "true"
    assert bounded_params["type"] == "single"
    assert bounded_params["first_trade_date.lte"] == "2026-08-14"
    assert bounded_params["last_trade_date.gte"] == "2026-08-14"

    assert index_params["product_code"] == "ES"
    assert index_params["type"] == "single"
    assert index_params["limit"] == 1000
    assert "active" not in index_params
    assert "date" not in index_params
    assert "first_trade_date.lte" not in index_params
    assert "last_trade_date.gte" not in index_params

    telemetry = provider.reference_telemetry[0]
    assert telemetry["query_mode"] == "current_single_index_without_active_window"
    assert telemetry["bounded_empty_retry_used"] is True
    assert telemetry["server_side_point_in_time_bound"] is False
    assert telemetry["local_point_in_time_validation"] is True
    assert telemetry["server_side_contract_type_bound"] is True
    assert telemetry["request_params"] == {
        "limit": 1000,
        "product_code": "ES",
        "type": "single",
    }
    assert telemetry["raw_result_count"] == 2
    assert telemetry["point_in_time_valid_count"] == 1
    assert telemetry["usable_count"] == 1
    assert telemetry["failure_reason"] == "ok"
    assert "super-secret-key" not in repr(telemetry)


def test_bounded_fallback_keeps_existing_pagination_completeness_guard() -> None:
    as_of = datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {
                    "results": [_valid_es_contract()],
                    "next_url": "https://api.massive.com/futures/v1/contracts?cursor=next",
                },
            ),
        ],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=as_of,
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert "pagination exceeded" in str(raised.value)
    assert len(getter.calls) == 2
    assert getter.calls[1][1]["first_trade_date.lte"] == "2026-08-14"
    assert getter.calls[1][1]["last_trade_date.gte"] == "2026-08-14"
    assert getter.calls[1][1]["type"] == "single"
    telemetry = provider.reference_telemetry[0]
    assert telemetry["failure_reason"] == "pagination_incomplete"
    assert telemetry["usable_count"] == 1


def test_historical_strict_empty_does_not_use_bounded_current_fallback() -> None:
    provider, getter = _provider(
        [_FakeResponse(200, {"results": []})],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    with pytest.raises(MassiveMultiAssetError):
        provider.futures_contracts(
            as_of=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert len(getter.calls) == 1
    params = getter.calls[0][1]
    assert params["date"] == "2026-06-01"
    assert "first_trade_date.lte" not in params
    assert "last_trade_date.gte" not in params
    assert "type" not in params
