"""Bounded Twelve Data daily-history adapter for governed provider failover.

The adapter is evidence-only. It supplies point-in-time historical bars when a caller
has already established that the requested Twelve Data symbol represents the same
instrument. It has no ranking, sizing, portfolio, order-entry, or real-money authority.
"""

from __future__ import annotations

import os
import time as time_module
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


TWELVE_DATA_TIME_SERIES_URL = "https://api.twelvedata.com/time_series"


class TwelveDataHistoryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class TwelveDataHistoryProvider:
    """Retrieve UTC-normalized completed daily bars from Twelve Data."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: int = 15,
        max_attempts: int = 2,
        backoff_seconds: float = 0.25,
        http_get: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("TWELVE_API_KEY")
            or os.getenv("TWELVE_DATA_API_KEY")
        )
        self.timeout = int(timeout)
        self.max_attempts = int(max_attempts)
        self.backoff_seconds = float(backoff_seconds)
        if self.timeout < 1 or self.max_attempts < 1 or self.backoff_seconds < 0.0:
            raise ValueError("Twelve Data timeout/retry settings are invalid")
        self._http_get = http_get or requests.get
        self._sleeper = sleeper or time_module.sleep

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def daily_history(
        self,
        symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[str, tuple[dict[str, object], ...]]:
        if not self.api_key:
            raise TwelveDataHistoryError("Twelve Data API key is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(history_days, bool) or not isinstance(history_days, int) or history_days < 1:
            raise ValueError("history_days must be a positive integer")
        candidates = tuple(dict.fromkeys(str(item).strip() for item in symbols if str(item).strip()))
        if not candidates:
            raise TwelveDataHistoryError("Twelve Data symbol candidates are empty")
        last_error: TwelveDataHistoryError | None = None
        for symbol in candidates:
            try:
                rows = self._daily_history(symbol, as_of=as_of, history_days=history_days)
            except TwelveDataHistoryError as error:
                last_error = error
                continue
            if rows:
                return symbol, rows
        if last_error is not None:
            raise last_error
        raise TwelveDataHistoryError("Twelve Data returned no historical evidence")

    def _daily_history(
        self,
        symbol: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[dict[str, object], ...]:
        cutoff = as_of.astimezone(timezone.utc)
        start = cutoff - timedelta(days=history_days)
        payload = self._request(
            params={
                "symbol": symbol,
                "interval": "1day",
                "timezone": "UTC",
                "start_date": start.strftime("%Y-%m-%d"),
                "end_date": cutoff.strftime("%Y-%m-%d"),
                "outputsize": min(5000, max(400, history_days * 2)),
                "order": "ASC",
                "apikey": self.api_key,
            },
            symbol=symbol,
        )
        if not isinstance(payload, Mapping):
            raise TwelveDataHistoryError("Twelve Data history response must be an object")
        code = payload.get("code")
        if str(payload.get("status") or "").lower() == "error" or code not in (None, ""):
            status = None
            try:
                status = int(code) if code not in (None, "") else None
            except (TypeError, ValueError):
                status = None
            raise TwelveDataHistoryError(
                "Twelve Data rejected historical evidence request",
                status_code=status,
                retryable=status in {408, 425, 429} or bool(status and 500 <= status <= 599),
            )
        values = payload.get("values")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise TwelveDataHistoryError("Twelve Data history values are missing")
        rows: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, Mapping):
                continue
            observed = self._timestamp(item.get("datetime"))
            if observed is None or observed > cutoff:
                continue
            close = self._number(item.get("close"))
            volume = self._number(item.get("volume"), default=0.0)
            if close <= 0.0:
                continue
            rows.append({"t": observed, "c": close, "v": max(0.0, volume)})
        rows.sort(key=lambda item: item["t"])  # type: ignore[arg-type]
        return tuple(rows)

    def _request(self, *, params: dict[str, object], symbol: str) -> Any:
        last_error: TwelveDataHistoryError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http_get(
                    TWELVE_DATA_TIME_SERIES_URL,
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as error:
                last_error = TwelveDataHistoryError(
                    f"Twelve Data history request failed for {symbol}",
                    retryable=True,
                )
            else:
                status = int(getattr(response, "status_code", 0))
                if 200 <= status < 300:
                    try:
                        return response.json()
                    except (TypeError, ValueError) as error:
                        raise TwelveDataHistoryError(
                            "Twelve Data returned invalid JSON",
                            status_code=status,
                        ) from error
                retryable = status in {408, 425, 429} or 500 <= status <= 599
                last_error = TwelveDataHistoryError(
                    f"Twelve Data returned HTTP {status or 'unknown'}",
                    status_code=status or None,
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error
            if attempt < self.max_attempts and last_error is not None and last_error.retryable:
                self._sleeper(self.backoff_seconds * attempt)
                continue
            break
        if last_error is not None:
            raise last_error
        raise TwelveDataHistoryError("Twelve Data history request failed")

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _number(value: object, *, default: float = 0.0) -> float:
        if isinstance(value, bool) or value in (None, ""):
            return default
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default
        return result


__all__ = [
    "TWELVE_DATA_TIME_SERIES_URL",
    "TwelveDataHistoryError",
    "TwelveDataHistoryProvider",
]
