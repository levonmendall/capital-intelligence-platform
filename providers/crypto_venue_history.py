"""Native completed-session crypto history from independent Coinbase and Kraken venues.

The adapters are public market-data only. They do not expose accounts, custody, order
entry, ranking, construction, or real-money authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

import requests


class CryptoVenueHistoryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class CoinbaseHistoryProvider:
    endpoint = "https://api.exchange.coinbase.com/products/{product_id}/candles"

    def __init__(self, *, timeout: int = 15, http_get: Callable[..., Any] | None = None) -> None:
        self.timeout = int(timeout)
        self._http_get = http_get or requests.get

    @property
    def configured(self) -> bool:
        return True

    def daily_history(
        self,
        product_id: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[dict[str, object], ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(timezone.utc)
        # Coinbase Exchange returns at most 300 candles. A daily request is sufficient
        # for the canonical 252-bar minimum and is intentionally not polled in chunks.
        start = max(cutoff - timedelta(days=history_days), cutoff - timedelta(days=299))
        try:
            response = self._http_get(
                self.endpoint.format(product_id=str(product_id).strip().upper()),
                params={
                    "granularity": 86400,
                    "start": start.isoformat(),
                    "end": cutoff.isoformat(),
                },
                headers={"User-Agent": "Capital-Intelligence-Platform/1.0"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise CryptoVenueHistoryError("Coinbase candles request failed", retryable=True) from error
        payload = self._payload(response, provider="Coinbase")
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            raise CryptoVenueHistoryError("Coinbase candles response must be an array")
        rows: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 6:
                continue
            try:
                observed = datetime.fromtimestamp(float(item[0]), tz=timezone.utc)
                close = float(item[4])
                volume = max(0.0, float(item[5]))
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            # Only committed daily buckets may enter point-in-time evidence.
            if observed + timedelta(days=1) <= cutoff and close > 0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)

    def _payload(self, response: Any, *, provider: str) -> Any:
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            raise CryptoVenueHistoryError(
                f"{provider} returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=status in {408, 425, 429} or 500 <= status <= 599,
            )
        try:
            return response.json()
        except (TypeError, ValueError) as error:
            raise CryptoVenueHistoryError(f"{provider} returned invalid JSON") from error


class KrakenHistoryProvider:
    endpoint = "https://api.kraken.com/0/public/OHLC"

    def __init__(self, *, timeout: int = 15, http_get: Callable[..., Any] | None = None) -> None:
        self.timeout = int(timeout)
        self._http_get = http_get or requests.get

    @property
    def configured(self) -> bool:
        return True

    def daily_history(
        self,
        pair: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[dict[str, object], ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        cutoff = as_of.astimezone(timezone.utc)
        since = int((cutoff - timedelta(days=min(history_days, 719))).timestamp())
        try:
            response = self._http_get(
                self.endpoint,
                params={
                    "pair": str(pair).strip().upper(),
                    "interval": 1440,
                    "since": since,
                    "assetVersion": 1,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise CryptoVenueHistoryError("Kraken OHLC request failed", retryable=True) from error
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            raise CryptoVenueHistoryError(
                f"Kraken returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=status in {408, 425, 429} or 500 <= status <= 599,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise CryptoVenueHistoryError("Kraken returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise CryptoVenueHistoryError("Kraken OHLC response must be an object")
        errors = payload.get("error")
        if isinstance(errors, Sequence) and not isinstance(errors, (str, bytes)) and errors:
            raise CryptoVenueHistoryError("Kraken rejected the OHLC request")
        result = payload.get("result")
        if not isinstance(result, Mapping):
            raise CryptoVenueHistoryError("Kraken OHLC response is missing result")
        raw = next(
            (
                value
                for key, value in result.items()
                if key != "last" and isinstance(value, Sequence) and not isinstance(value, (str, bytes))
            ),
            None,
        )
        if raw is None:
            raise CryptoVenueHistoryError("Kraken OHLC response contains no pair history")
        rows: list[dict[str, object]] = []
        for item in raw:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) < 7:
                continue
            try:
                observed = datetime.fromtimestamp(float(item[0]), tz=timezone.utc)
                close = float(item[4])
                volume = max(0.0, float(item[6]))
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            # Kraken documents the last OHLC item as current/uncommitted; filtering by
            # full daily bucket completion removes it without relying on array position.
            if observed + timedelta(days=1) <= cutoff and close > 0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)


__all__ = [
    "CoinbaseHistoryProvider",
    "CryptoVenueHistoryError",
    "KrakenHistoryProvider",
]
