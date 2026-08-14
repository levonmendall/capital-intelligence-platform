from __future__ import annotations

from datetime import datetime, timezone

import pytest

from providers.massive_futures_reference_rate_resilient import (
    MassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import MassiveMultiAssetError


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: object,
        *,
        retry_after: str | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}

    def json(self) -> object:
        return self._payload


class _SequentialGet:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected Massive request")
        return self.responses.pop(0)


def _contract() -> dict[str, object]:
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


def test_massive_429_honors_retry_after_and_recovers() -> None:
    sleeps: list[float] = []
    getter = _SequentialGet(
        [
            _FakeResponse(429, {}, retry_after="17"),
            _FakeResponse(200, {"results": [_contract()]}),
        ]
    )
    provider = MassiveFuturesReferenceProvider(
        api_key="secret",
        http_get=getter,
        sleeper=sleeps.append,
        minimum_call_interval_seconds=0,
        rate_limit_retry_seconds=60,
        reference_max_attempts=2,
    )

    contracts = provider.futures_contracts(
        as_of=datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
        product_codes=("ES",),
        maximum_pages=1,
    )

    assert [contract.ticker for contract in contracts] == ["ESU6"]
    assert getter.calls == 2
    assert sleeps == [17.0]
    telemetry = provider.reference_telemetry[0]
    assert telemetry["rate_limited"] is True
    assert telemetry["retry_count"] == 1
    assert telemetry["retry_after_seconds"] == 17.0
    assert telemetry["last_retry_delay_seconds"] == 17.0
    assert telemetry["rate_limit_retry_source"] == "provider_retry_after"
    assert telemetry["failure_reason"] == "ok"


def test_exhausted_massive_429_remains_fail_closed() -> None:
    sleeps: list[float] = []
    getter = _SequentialGet(
        [
            _FakeResponse(429, {}, retry_after="9"),
            _FakeResponse(429, {}, retry_after="9"),
        ]
    )
    provider = MassiveFuturesReferenceProvider(
        api_key="secret",
        http_get=getter,
        sleeper=sleeps.append,
        minimum_call_interval_seconds=0,
        rate_limit_retry_seconds=60,
        reference_max_attempts=2,
    )

    with pytest.raises(MassiveMultiAssetError, match="HTTP 429"):
        provider.futures_contracts(
            as_of=datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
            product_codes=("ES",),
            maximum_pages=1,
        )

    assert getter.calls == 2
    assert sleeps == [9.0]
    telemetry = provider.reference_telemetry[0]
    assert telemetry["failure_reason"] == "provider_rate_limited"
    assert telemetry["rate_limited"] is True
