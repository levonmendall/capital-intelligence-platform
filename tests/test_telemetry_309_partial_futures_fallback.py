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
) -> tuple[MassiveFuturesReferenceProvider, _SequentialGet]:
    getter = _SequentialGet(responses)
    provider = MassiveFuturesReferenceProvider(
        api_key="super-secret-key",
        http_get=getter,
        sleeper=lambda _: None,
        minimum_call_interval_seconds=0,
        reference_max_attempts=1,
        reference_clock=lambda: datetime(2026, 8, 14, 3, 10, tzinfo=timezone.utc),
    )
    return provider, getter


def _contract(root: str, ticker: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "product_code": root,
        "trading_venue": "XCME",
        "first_trade_date": "2026-06-19",
        "last_trade_date": "2026-09-18",
        "settlement_date": "2026-09-18",
        "active": True,
        "type": "single",
    }


def test_partial_strict_success_falls_back_only_for_empty_root() -> None:
    as_of = datetime(2026, 8, 14, 3, 5, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": [_contract("ES", "ESU6")]}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": [_contract("NQ", "NQU6")]}),
        ]
    )

    contracts = provider.futures_contracts(
        as_of=as_of,
        product_codes=("ES", "NQ"),
        maximum_pages=1,
    )

    assert [contract.ticker for contract in contracts] == ["ESU6", "NQU6"]
    assert len(getter.calls) == 3
    assert getter.calls[0][1]["product_code"] == "ES"
    assert getter.calls[0][1]["date"] == "2026-08-14"
    assert getter.calls[1][1]["product_code"] == "NQ"
    assert getter.calls[1][1]["date"] == "2026-08-14"
    assert getter.calls[2][1]["product_code"] == "NQ"
    assert "date" not in getter.calls[2][1]
    assert getter.calls[2][1]["first_trade_date.lte"] == "2026-08-14"
    assert getter.calls[2][1]["last_trade_date.gte"] == "2026-08-14"

    telemetry = {str(row["root"]): row for row in provider.reference_telemetry}
    assert set(telemetry) == {"ES", "NQ"}
    assert telemetry["ES"]["failure_reason"] == "ok"
    assert telemetry["ES"].get("fallback_used") is not True
    assert telemetry["NQ"]["failure_reason"] == "ok"
    assert telemetry["NQ"]["fallback_used"] is True
    assert telemetry["NQ"]["strict_raw_result_count"] == 0


def test_partial_fallback_remains_fail_closed_and_preserves_root_telemetry() -> None:
    as_of = datetime(2026, 8, 14, 3, 5, tzinfo=timezone.utc)
    provider, getter = _provider(
        [
            _FakeResponse(200, {"results": [_contract("ES", "ESU6")]}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            _FakeResponse(200, {"results": []}),
            # Telemetry #512 repair retries an empty type=single index without the
            # provider-side type predicate. An empty response must still fail closed.
            _FakeResponse(200, {"results": []}),
        ]
    )

    with pytest.raises(MassiveMultiAssetError):
        provider.futures_contracts(
            as_of=as_of,
            product_codes=("ES", "NQ"),
            maximum_pages=1,
        )

    assert len(getter.calls) == 5
    assert getter.calls[3][1]["product_code"] == "NQ"
    assert getter.calls[3][1]["type"] == "single"
    assert getter.calls[4][1]["product_code"] == "NQ"
    assert "type" not in getter.calls[4][1]

    telemetry = {str(row["root"]): row for row in provider.reference_telemetry}
    assert set(telemetry) == {"ES", "NQ"}
    assert telemetry["ES"]["usable_count"] == 1
    assert telemetry["ES"]["failure_reason"] == "ok"
    assert telemetry["NQ"]["usable_count"] == 0
    assert telemetry["NQ"]["fallback_used"] is True
    assert telemetry["NQ"]["untyped_empty_retry_used"] is True
    assert telemetry["NQ"]["local_contract_type_validation"] is True
    assert telemetry["NQ"]["failure_reason"] == "empty_current_fallback_response"
