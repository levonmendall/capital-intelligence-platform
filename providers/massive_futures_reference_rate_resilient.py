"""Rate-limit-resilient Massive futures reference acquisition.

This wrapper keeps the existing bounded point-in-time futures discovery and configured-
root completeness rules, but makes the HTTP 429 boundary provider-aware. Massive's
``Retry-After`` response header is honored when present; otherwise the governed fallback
retry delay is used. Retries remain bounded and exhausted throttling remains fail-closed.

The adapter is reference-data-only. It has no investment, CIO, construction, execution,
or real-money authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests

from providers.massive_futures_reference_bounded import (
    MassiveFuturesReferenceProvider as _BoundedMassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import MassiveMultiAssetError


_MAX_REFERENCE_RETRY_AFTER_SECONDS = 120.0


class _ReferenceRequestError(MassiveMultiAssetError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            retryable=retryable,
        )
        self.retry_after_seconds = retry_after_seconds


class MassiveFuturesReferenceProvider(_BoundedMassiveFuturesReferenceProvider):
    """Bounded futures reference provider that honors Massive throttle windows."""

    @staticmethod
    def _reference_retry_after_seconds(response: Any) -> float | None:
        headers = getattr(response, "headers", None)
        if not isinstance(headers, Mapping):
            return None
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw in (None, ""):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(value, _MAX_REFERENCE_RETRY_AFTER_SECONDS))

    def _single_reference_request(
        self,
        url: str,
        *,
        params: dict[str, object],
    ) -> Mapping[str, Any]:
        response = None
        try:
            self._reserve_request()
            response = self._http_get(url, params=params, timeout=self.timeout)
        except requests.RequestException as error:
            raise _ReferenceRequestError(
                "Massive request failed",
                retryable=True,
            ) from error

        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            retryable = status in {408, 425, 429} or 500 <= status <= 599
            raise _ReferenceRequestError(
                f"Massive returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=retryable,
                retry_after_seconds=(
                    self._reference_retry_after_seconds(response)
                    if status == 429
                    else None
                ),
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise _ReferenceRequestError("Massive returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise _ReferenceRequestError("Massive response must be an object")
        status_text = str(payload.get("status") or "OK").upper()
        if status_text not in {"OK", "SUCCESS"}:
            raise _ReferenceRequestError("Massive rejected the request")
        return payload

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        last_error: MassiveMultiAssetError | None = None
        for attempt in range(1, self.reference_max_attempts + 1):
            root_telemetry["request_attempts"] = int(
                root_telemetry.get("request_attempts", 0)
            ) + 1
            try:
                payload = self._single_reference_request(url, params=params)
            except MassiveMultiAssetError as error:
                last_error = error
                if error.status_code is not None:
                    root_telemetry["http_status"] = int(error.status_code)
                root_telemetry["last_error"] = type(error).__name__
                if error.status_code == 429:
                    root_telemetry["rate_limited"] = True
                    retry_after = getattr(error, "retry_after_seconds", None)
                    if retry_after is not None:
                        root_telemetry["retry_after_seconds"] = float(retry_after)
                if not error.retryable or attempt >= self.reference_max_attempts:
                    if error.status_code in {401, 403}:
                        root_telemetry["failure_reason"] = "provider_auth_or_entitlement"
                    elif error.status_code == 429:
                        root_telemetry["failure_reason"] = "provider_rate_limited"
                    elif error.status_code is not None:
                        root_telemetry["failure_reason"] = "provider_http_error"
                    else:
                        root_telemetry["failure_reason"] = "provider_transport_error"
                    raise

                if error.status_code == 429:
                    retry_after = getattr(error, "retry_after_seconds", None)
                    if retry_after is None:
                        delay = self.rate_limit_retry_seconds
                        root_telemetry["rate_limit_retry_source"] = "configured_fallback"
                    else:
                        delay = float(retry_after)
                        root_telemetry["rate_limit_retry_source"] = "provider_retry_after"
                else:
                    delay = min(30.0, 2.0 ** (attempt - 1))

                root_telemetry["failure_reason"] = "pending"
                root_telemetry["retry_count"] = int(
                    root_telemetry.get("retry_count", 0)
                ) + 1
                root_telemetry["last_retry_delay_seconds"] = float(delay)
                if delay > 0.0:
                    self._sleeper(delay)
            else:
                root_telemetry["http_status"] = 200
                return payload

        assert last_error is not None
        raise last_error


__all__ = ["MassiveFuturesReferenceProvider"]
