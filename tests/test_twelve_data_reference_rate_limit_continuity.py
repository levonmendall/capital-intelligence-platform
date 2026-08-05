from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

from providers.twelve_data_reference_rate_limited import (
    TwelveDataRateLimitedReferenceProvider,
)


UTC = timezone.utc


def _response(status_code: int, **headers: str) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, headers=headers)


def test_rate_limited_get_honors_numeric_retry_after_then_returns_success() -> None:
    responses = iter(
        (
            _response(429, **{"Retry-After": "2"}),
            _response(200, **{"api-credits-left": "5"}),
        )
    )
    calls: list[tuple[str, object, int]] = []
    delays: list[float] = []

    def http_get(url: str, *, params: object, timeout: int) -> object:
        calls.append((url, params, timeout))
        return next(responses)

    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=http_get,
        sleeper=delays.append,
        max_rate_limit_retries=2,
        max_rate_limit_wait_seconds=10,
        clock=lambda: datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
    )

    result = provider._rate_limited_get(
        "https://example.test/stocks",
        params={"exchange": "SA"},
        timeout=30,
    )

    assert result.status_code == 200
    assert len(calls) == 2
    assert delays == [2.0]


def test_rate_limited_get_honors_http_date_and_caps_the_wait() -> None:
    now = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)
    responses = iter(
        (
            _response(
                429,
                **{"Retry-After": format_datetime(now + timedelta(seconds=40))},
            ),
            _response(200),
        )
    )
    delays: list[float] = []
    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=lambda *args, **kwargs: next(responses),
        sleeper=delays.append,
        max_rate_limit_retries=1,
        max_rate_limit_wait_seconds=15,
        clock=lambda: now,
    )

    result = provider._rate_limited_get(
        "https://example.test/stocks",
        params={},
        timeout=30,
    )

    assert result.status_code == 200
    assert delays == [15.0]


def test_persistent_rate_limit_stops_at_the_bounded_attempt_count() -> None:
    calls = 0
    delays: list[float] = []

    def http_get(*args, **kwargs) -> object:
        nonlocal calls
        calls += 1
        return _response(429, **{"Retry-After": "1"})

    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=http_get,
        sleeper=delays.append,
        max_rate_limit_retries=2,
        max_rate_limit_wait_seconds=10,
        clock=lambda: datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
    )

    result = provider._rate_limited_get(
        "https://example.test/stocks",
        params={},
        timeout=30,
    )

    assert result.status_code == 429
    assert calls == 3
    assert delays == [1.0, 1.0]


def test_non_rate_limit_failure_is_not_retried() -> None:
    calls = 0
    delays: list[float] = []

    def http_get(*args, **kwargs) -> object:
        nonlocal calls
        calls += 1
        return _response(402)

    provider = TwelveDataRateLimitedReferenceProvider(
        api_key="test-key",
        http_get=http_get,
        sleeper=delays.append,
        max_rate_limit_retries=2,
        max_rate_limit_wait_seconds=10,
    )

    result = provider._rate_limited_get(
        "https://example.test/stocks",
        params={},
        timeout=30,
    )

    assert result.status_code == 402
    assert calls == 1
    assert delays == []
