"""Bounded Twelve Data rate-limit continuity for production discovery.

Twelve Data publishes plan-specific API credit limits. A 429 response can represent a
transient minute-bucket exhaustion, so the production reference provider serializes its
requests, spaces production catalog calls below the configured burst ceiling, honors a
bounded ``Retry-After`` value when supplied, otherwise waits for the next UTC minute
boundary, and retries a small fixed number of times.

Successful responses that report ``api-credits-left: 0`` arm the same minute-boundary
pause before the next request. Persistent throttling, daily quota exhaustion, malformed
headers, and all non-429 failures remain fail-closed in the underlying provider.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Any

import requests

from providers.twelve_data_reference_runtime import (
    TwelveDataRuntimeReferenceProvider,
)


_DEFAULT_RATE_LIMIT_RETRIES = 2
_DEFAULT_MAX_RATE_LIMIT_WAIT_SECONDS = 65.0
_DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS = 0.0
_DEFAULT_PRODUCTION_REQUEST_INTERVAL_SECONDS = 8.0
_PRODUCTION_INTERVAL_ENV = (
    "CAPITAL_INTELLIGENCE_TWELVE_DATA_MINIMUM_REQUEST_INTERVAL_SECONDS"
)


def _response_status_code(response: Any) -> int | None:
    try:
        return int(getattr(response, "status_code", 0))
    except (TypeError, ValueError):
        return None


def _response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            text = str(value).strip()
            return text or None
    return None


class TwelveDataRateLimitedReferenceProvider(TwelveDataRuntimeReferenceProvider):
    """Serialize, pace, and boundedly retry Twelve Data reference requests."""

    def __init__(
        self,
        *args: Any,
        http_get: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        max_rate_limit_retries: int = _DEFAULT_RATE_LIMIT_RETRIES,
        max_rate_limit_wait_seconds: float = _DEFAULT_MAX_RATE_LIMIT_WAIT_SECONDS,
        minimum_request_interval_seconds: float = (
            _DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS
        ),
        **kwargs: Any,
    ) -> None:
        retries = int(max_rate_limit_retries)
        maximum_wait = float(max_rate_limit_wait_seconds)
        minimum_interval = float(minimum_request_interval_seconds)
        if retries < 0:
            raise ValueError("max_rate_limit_retries must be non-negative")
        if not 1.0 <= maximum_wait <= 300.0:
            raise ValueError(
                "max_rate_limit_wait_seconds must be between 1 and 300"
            )
        if not 0.0 <= minimum_interval <= 60.0:
            raise ValueError(
                "minimum_request_interval_seconds must be between 0 and 60"
            )
        self._raw_http_get = http_get or requests.get
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self.max_rate_limit_retries = retries
        self.max_rate_limit_wait_seconds = maximum_wait
        self.minimum_request_interval_seconds = minimum_interval
        self._request_lock = Lock()
        self._pause_before_next_request = False
        self._last_request_started_at: float | None = None
        super().__init__(*args, http_get=self._rate_limited_get, **kwargs)

    def _rate_limited_get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        timeout: int,
    ) -> Any:
        with self._request_lock:
            if self._pause_before_next_request:
                self._sleeper(self._minute_reset_wait_seconds())
                self._pause_before_next_request = False

            response: Any = None
            for attempt in range(self.max_rate_limit_retries + 1):
                self._pace_next_request()
                self._last_request_started_at = self._monotonic()
                response = self._raw_http_get(
                    url,
                    params=params,
                    timeout=timeout,
                )
                if _response_status_code(response) != 429:
                    if self._credits_left(response) == 0:
                        self._pause_before_next_request = True
                    return response
                if attempt >= self.max_rate_limit_retries:
                    return response
                self._sleeper(self._rate_limit_wait_seconds(response))
            return response

    def _pace_next_request(self) -> None:
        last_started_at = self._last_request_started_at
        if last_started_at is None or self.minimum_request_interval_seconds <= 0.0:
            return
        elapsed = max(0.0, self._monotonic() - last_started_at)
        remaining = self.minimum_request_interval_seconds - elapsed
        if remaining > 0.0:
            self._sleeper(remaining)

    def _rate_limit_wait_seconds(self, response: Any) -> float:
        retry_after = _response_header(response, "Retry-After")
        if retry_after is not None:
            parsed = self._parse_retry_after(retry_after)
            if parsed is not None:
                return min(
                    self.max_rate_limit_wait_seconds,
                    max(1.0, parsed),
                )
        return min(
            self.max_rate_limit_wait_seconds,
            self._minute_reset_wait_seconds(),
        )

    def _parse_retry_after(self, value: str) -> float | None:
        try:
            numeric = float(value)
        except ValueError:
            numeric = math.nan
        if math.isfinite(numeric):
            return numeric
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at.astimezone(timezone.utc) - self._now()).total_seconds())

    def _minute_reset_wait_seconds(self) -> float:
        now = self._now()
        elapsed = now.second + (now.microsecond / 1_000_000.0)
        return max(1.0, min(self.max_rate_limit_wait_seconds, 61.0 - elapsed))

    @staticmethod
    def _credits_left(response: Any) -> int | None:
        value = _response_header(response, "api-credits-left")
        if value is None:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None


def build_twelve_data_rate_limited_reference_provider(
) -> TwelveDataRateLimitedReferenceProvider:
    """Build the production reference provider with bounded 429 continuity."""

    raw_interval = os.getenv(
        _PRODUCTION_INTERVAL_ENV,
        str(_DEFAULT_PRODUCTION_REQUEST_INTERVAL_SECONDS),
    )
    try:
        minimum_interval = float(raw_interval)
    except ValueError as error:
        raise ValueError(
            f"{_PRODUCTION_INTERVAL_ENV} must be numeric"
        ) from error
    return TwelveDataRateLimitedReferenceProvider(
        minimum_request_interval_seconds=minimum_interval
    )


__all__ = [
    "TwelveDataRateLimitedReferenceProvider",
    "build_twelve_data_rate_limited_reference_provider",
]
