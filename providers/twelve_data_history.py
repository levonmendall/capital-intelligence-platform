"""Bounded Twelve Data daily-history adapter for governed provider failover."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from provider_environment import provider_environment_value


TWELVE_DATA_TIME_SERIES_URL = "https://api.twelvedata.com/time_series"


class TwelveDataHistoryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class TwelveDataHistoryProvider:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: int = 15,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key or provider_environment_value("TWELVE_DATA_API_KEY") or provider_environment_value("TWELVE_API_KEY")
        self.timeout = int(timeout)
        if self.timeout < 1:
            raise ValueError("timeout must be positive")
        self._http_get = http_get or requests.get

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
        candidates = tuple(dict.fromkeys(str(item).strip() for item in symbols if str(item).strip()))
        if not candidates:
            raise TwelveDataHistoryError("Twelve Data symbol candidates are empty")
        last_error: TwelveDataHistoryError | None = None
        for symbol in candidates:
            try:
                rows = self._history(symbol, as_of=as_of, history_days=history_days)
            except TwelveDataHistoryError as error:
                last_error = error
                continue
            if rows:
                return symbol, rows
        if last_error is not None:
            raise last_error
        raise TwelveDataHistoryError("Twelve Data returned no historical evidence")

    def _history(self, symbol: str, *, as_of: datetime, history_days: int) -> tuple[dict[str, object], ...]:
        cutoff = as_of.astimezone(timezone.utc)
        start = cutoff - timedelta(days=history_days)
        try:
            response = self._http_get(
                TWELVE_DATA_TIME_SERIES_URL,
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
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise TwelveDataHistoryError("Twelve Data history request failed", retryable=True) from error
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            raise TwelveDataHistoryError(
                f"Twelve Data returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=status in {408, 425, 429} or 500 <= status <= 599,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise TwelveDataHistoryError("Twelve Data returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise TwelveDataHistoryError("Twelve Data history response must be an object")
        code = payload.get("code")
        if str(payload.get("status") or "").lower() == "error" or code not in (None, ""):
            provider_status = None
            try:
                provider_status = int(code) if code not in (None, "") else None
            except (TypeError, ValueError):
                pass
            raise TwelveDataHistoryError(
                "Twelve Data rejected historical evidence request",
                status_code=provider_status,
                retryable=provider_status in {408, 425, 429} or bool(provider_status and 500 <= provider_status <= 599),
            )
        values = payload.get("values")
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise TwelveDataHistoryError("Twelve Data history values are missing")
        rows: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, Mapping):
                continue
            try:
                observed = datetime.fromisoformat(str(item["datetime"]).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                observed = observed.astimezone(timezone.utc)
                close = float(item["close"])
                volume = max(0.0, float(item.get("volume", 0.0) or 0.0))
            except (KeyError, TypeError, ValueError):
                continue
            if observed <= cutoff and close > 0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)


__all__ = ["TWELVE_DATA_TIME_SERIES_URL", "TwelveDataHistoryError", "TwelveDataHistoryProvider"]
