"""Regression coverage for bounded Twelve Data HTTP 429 continuity."""

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
from providers.twelve_data_reference_rate_limited import (
    TwelveDataRateLimitedReferenceProvider,
)


NOW = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)


class Response:
    def __init__(
        self,
        payload,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.payload


def query(exchange: str = "WAR", *, as_of: datetime = NOW) -> ProviderDatasetQuery:
    return ProviderDatasetQuery(
        dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
        provider_symbol=exchange,
        as_of=as_of,
        limit=1_000_000,
    )


def stock_row(
    *,
    symbol: str,
    exchange: str,
    mic_code: str,
    country: str,
    currency: str,
):
    return {
        "symbol": symbol,
        "name": symbol,
        "currency": currency,
        "exchange": exchange,
        "mic_code": mic_code,
        "country": country,
        "type": "Common Stock",
    }


def war_payload():
    return {
        "count": 1,
        "data": [
            stock_row(
                symbol="PKN",
                exchange="Warsaw Stock Exchange",
                mic_code="XWAR",
                country="Poland",
                currency="PLN",
            )
        ],
        "status": "ok",
    }


def lse_payload():
    return {
        "count": 1,
        "data": [
            stock_row(
                symbol="SHEL",
                exchange="London Stock Exchange",
                mic_code="XLON",
                country="United Kingdom",
                currency="GBP",
            )
        ],
        "status": "ok",
    }


def provider(
    responses,
    *,
    sleeps: list[float],
    now: datetime = NOW,
    max_rate_limit_retries: int = 2,
) -> TwelveDataRateLimitedReferenceProvider:
    queue = list(responses)
    calls = []

    def get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return queue.pop(0)

    result = TwelveDataRateLimitedReferenceProvider(
        api_key="twelve-secret",
        http_get=get,
        sleeper=sleeps.append,
        clock=lambda: now,
        max_rate_limit_retries=max_rate_limit_retries,
    )
    result.calls = calls  # type: ignore[attr-defined]
    return result


def test_http_429_honors_retry_after_then_returns_certified_directory() -> None:
    sleeps: list[float] = []
    reference = provider(
        [
            Response({}, 429, {"Retry-After": "2"}),
            Response(war_payload()),
        ],
        sleeps=sleeps,
    )

    snapshot = reference.fetch_dataset(query())

    assert snapshot.provider == "Twelve Data"
    assert snapshot.quality_state is DataQualityState.FALLBACK
    assert snapshot.payload["active"][0]["Exchange"] == "WAR"
    assert sleeps == [2.0]
    assert len(reference.calls) == 2  # type: ignore[attr-defined]


def test_http_429_without_header_waits_for_next_minute_boundary() -> None:
    now = NOW.replace(second=45, microsecond=500_000)
    sleeps: list[float] = []
    reference = provider(
        [Response({}, 429), Response(war_payload())],
        sleeps=sleeps,
        now=now,
    )

    reference.fetch_dataset(query(as_of=now))

    assert sleeps == [15.5]


def test_persistent_http_429_remains_fail_closed_after_bounded_retries() -> None:
    sleeps: list[float] = []
    reference = provider(
        [Response({}, 429), Response({}, 429), Response({}, 429)],
        sleeps=sleeps,
    )

    with pytest.raises(TwelveDataReferenceError, match="returned HTTP 429"):
        reference.fetch_dataset(query())

    assert sleeps == [61.0, 61.0]
    assert len(reference.calls) == 3  # type: ignore[attr-defined]


def test_zero_remaining_credit_defers_the_next_reference_request() -> None:
    sleeps: list[float] = []
    reference = provider(
        [
            Response(lse_payload(), headers={"api-credits-left": "0"}),
            Response(war_payload()),
        ],
        sleeps=sleeps,
    )

    reference.fetch_dataset(query("LSE"))
    reference.fetch_dataset(query("WAR"))

    assert sleeps == [61.0]
    assert len(reference.calls) == 2  # type: ignore[attr-defined]


def test_non_rate_limit_http_failure_is_not_retried() -> None:
    sleeps: list[float] = []
    reference = provider([Response({}, 403)], sleeps=sleeps)

    with pytest.raises(TwelveDataReferenceError, match="returned HTTP 403"):
        reference.fetch_dataset(query())

    assert sleeps == []
    assert len(reference.calls) == 1  # type: ignore[attr-defined]


def test_eodhd_http_402_can_survive_one_twelve_data_rate_limit(
    tmp_path: Path,
) -> None:
    sleeps: list[float] = []
    reference = provider(
        [Response({}, 429), Response(war_payload())],
        sleeps=sleeps,
    )
    eodhd = EODHDProvider(
        api_token="eodhd-secret",
        bindings=EODHDBindingRegistry(()),
        http_get=lambda *_args, **_kwargs: Response({}, 402),
        clock=lambda: NOW,
        sleeper=lambda _seconds: None,
        retrieval_policy=EODHDRetrievalPolicy(max_attempts=1),
        directory_cache_dir=tmp_path,
        directory_cache_max_age=timedelta(hours=72),
        reference_provider=reference,
    )

    snapshot = eodhd.fetch_dataset(query())

    assert snapshot.provider == "Twelve Data"
    assert snapshot.payload["active"][0]["Code"] == "PKN"
    assert sleeps == [61.0]
