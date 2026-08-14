from __future__ import annotations

from datetime import datetime, timezone

import pytest

from providers.massive_futures_reference_resilient import MassiveFuturesReferenceProvider
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


def test_current_strict_empty_retries_without_date_and_keeps_local_pit_guard() -> None:
    as_of = datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {
                    "results": [
                        {
                            "ticker": "ESU6",
                            "product_code": "ES",
                            "trading_venue": "XCME",
                            "first_trade_date": "2026-06-19",
                            "last_trade_date": "2026-09-18",
                            "settlement_date": "2026-09-18",
                            "active": True,
                        }
                    ]
                },
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
    assert len(getter.calls) == 2
    strict_params = getter.calls[0][1]
    fallback_params = getter.calls[1][1]
    assert strict_params["date"] == "2026-08-14"
    assert strict_params["active"] == "true"
    assert strict_params["product_code"] == "ES"
    assert "date" not in fallback_params
    assert fallback_params["active"] == "true"
    assert fallback_params["product_code"] == "ES"

    telemetry = provider.reference_telemetry[0]
    assert telemetry["query_mode"] == "current_active_without_date"
    assert telemetry["fallback_used"] is True
    assert telemetry["strict_http_status"] == 200
    assert telemetry["strict_raw_result_count"] == 0
    assert telemetry["usable_count"] == 1
    assert telemetry["failure_reason"] == "ok"
    assert "apiKey" not in telemetry["request_params"]
    assert "super-secret-key" not in repr(telemetry)


def test_current_fallback_still_rejects_contract_outside_original_as_of_window() -> None:
    as_of = datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc)
    provider, _ = _provider(
        [
            _FakeResponse(200, {"results": []}),
            _FakeResponse(
                200,
                {
                    "results": [
                        {
                            "ticker": "ESM6",
                            "product_code": "ES",
                            "trading_venue": "XCME",
                            "first_trade_date": "2026-03-20",
                            "last_trade_date": "2026-06-19",
                            "active": True,
                        }
                    ]
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

    assert "configured-root coverage" in str(raised.value)
    telemetry = provider.reference_telemetry[0]
    assert telemetry["raw_result_count"] == 1
    assert telemetry["root_matched_count"] == 1
    assert telemetry["point_in_time_valid_count"] == 0
    assert telemetry["usable_count"] == 0
    assert telemetry["failure_reason"] == "point_in_time_filter"


def test_historical_empty_response_remains_fail_closed_without_current_fallback() -> None:
    provider, getter = _provider(
        [_FakeResponse(200, {"results": []})],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert len(getter.calls) == 1
    assert getter.calls[0][1]["date"] == "2026-06-01"
    assert '"reason":"empty_provider_response"' in str(raised.value)


def test_entitlement_failure_never_uses_current_fallback() -> None:
    provider, getter = _provider(
        [_FakeResponse(403, {"error": "forbidden"})],
        now=datetime(2026, 8, 14, 1, 40, tzinfo=timezone.utc),
    )

    with pytest.raises(MassiveMultiAssetError) as raised:
        provider.futures_contracts(
            as_of=datetime(2026, 8, 14, 1, 35, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert len(getter.calls) == 1
    assert '"reason":"provider_auth_or_entitlement"' in str(raised.value)
