"""Bounded Massive market-data adapters for independent multi-asset failover.

Supported evidence roles are U.S. stocks/ETFs, spot FX, spot crypto, and exact U.S.
dated futures contracts.  The adapter is evidence-only and has no ranking, CIO,
construction, order-entry, or real-money authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from provider_environment import provider_environment_value


MASSIVE_BASE_URL = "https://api.massive.com"


class MassiveMultiAssetError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class MassiveFuturesContract:
    ticker: str
    product_code: str
    trading_venue: str
    first_trade_date: str
    last_trade_date: str
    settlement_date: str | None
    active: bool
    source_identifier: str


class MassiveMultiAssetProvider:
    """Retrieve point-in-time historical evidence across Massive asset APIs."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: int = 15,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key or provider_environment_value("MASSIVE_API_KEY") or provider_environment_value(
            "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY"
        )
        self.timeout = int(timeout)
        if self.timeout < 1:
            raise ValueError("timeout must be positive")
        self._http_get = http_get or requests.get

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def daily_history(
        self,
        asset_kind: str,
        symbol: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[dict[str, object], ...]:
        if not self.api_key:
            raise MassiveMultiAssetError("Massive API key is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if history_days < 1:
            raise ValueError("history_days must be positive")
        kind = str(asset_kind).strip().lower()
        ticker = self._ticker(kind, symbol)
        cutoff = as_of.astimezone(timezone.utc)
        start = cutoff - timedelta(days=history_days)
        if kind == "future":
            return self._future_history(ticker, start=start, cutoff=cutoff)
        if kind not in {"stock", "etf", "fx", "crypto"}:
            raise MassiveMultiAssetError(f"unsupported Massive asset kind: {kind}")
        path = (
            f"/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start.date().isoformat()}/{cutoff.date().isoformat()}"
        )
        payload = self._get(
            path,
            params={"adjusted": "true", "sort": "asc", "limit": 50000},
        )
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise MassiveMultiAssetError("Massive aggregate response is missing results")
        rows: list[dict[str, object]] = []
        for item in results:
            if not isinstance(item, Mapping):
                continue
            try:
                observed = datetime.fromtimestamp(float(item["t"]) / 1000.0, tz=timezone.utc)
                close = float(item["c"])
                volume = max(0.0, float(item.get("v", 0.0)))
            except (KeyError, TypeError, ValueError, OSError, OverflowError):
                continue
            if observed <= cutoff and close > 0.0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        if not self.api_key:
            raise MassiveMultiAssetError("Massive API key is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(maximum_pages, bool) or not isinstance(maximum_pages, int):
            raise TypeError("maximum_pages must be an integer")
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be positive")
        target_codes = {str(item).strip().upper() for item in product_codes if str(item).strip()}
        url = f"{MASSIVE_BASE_URL}/futures/v1/contracts"
        params: dict[str, object] = {
            "date": as_of.astimezone(timezone.utc).date().isoformat(),
            "active": "true",
            "limit": 1000,
            "apiKey": self.api_key,
        }
        result: dict[str, MassiveFuturesContract] = {}
        pagination_complete = False
        for _ in range(maximum_pages):
            payload = self._get_url(url, params=params)
            raw = payload.get("results") if isinstance(payload, Mapping) else None
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise MassiveMultiAssetError("Massive futures contract response is missing results")
            for item in raw:
                if not isinstance(item, Mapping):
                    continue
                ticker = str(item.get("ticker") or "").strip().upper()
                product = str(item.get("product_code") or "").strip().upper()
                venue = str(item.get("trading_venue") or "").strip().upper()
                first = str(item.get("first_trade_date") or "").strip()
                last = str(item.get("last_trade_date") or "").strip()
                if not ticker or not product or not venue or not first or not last:
                    continue
                if target_codes and product not in target_codes:
                    continue
                raw_active = item.get("active", True)
                active = (
                    raw_active.strip().lower() == "true"
                    if isinstance(raw_active, str)
                    else bool(raw_active)
                )
                result[ticker] = MassiveFuturesContract(
                    ticker=ticker,
                    product_code=product,
                    trading_venue=venue,
                    first_trade_date=first,
                    last_trade_date=last,
                    settlement_date=(str(item.get("settlement_date")).strip() if item.get("settlement_date") else None),
                    active=active,
                    source_identifier=f"massive:futures-contract:{ticker}:{as_of.date().isoformat()}",
                )
            next_url = str(payload.get("next_url") or "").strip() if isinstance(payload, Mapping) else ""
            if not next_url:
                pagination_complete = True
                break
            parsed = urlparse(next_url)
            if parsed.scheme != "https" or parsed.netloc != "api.massive.com":
                raise MassiveMultiAssetError("Massive futures pagination returned an invalid next_url")
            url = next_url
            params = {"apiKey": self.api_key}
        if not pagination_complete:
            raise MassiveMultiAssetError(
                "Massive futures contract pagination exceeded the completeness guard"
            )
        return tuple(result[key] for key in sorted(result))

    def _future_history(self, ticker: str, *, start: datetime, cutoff: datetime) -> tuple[dict[str, object], ...]:
        payload = self._get(
            f"/futures/v1/aggs/{ticker}",
            params={
                "resolution": "1session",
                "window_start.gte": start.date().isoformat(),
                "window_start.lte": cutoff.date().isoformat(),
                "limit": 50000,
            },
        )
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise MassiveMultiAssetError("Massive futures aggregates are missing results")
        rows: list[dict[str, object]] = []
        for item in results:
            if not isinstance(item, Mapping):
                continue
            try:
                raw_time = float(item["window_start"])
                # Futures API publishes nanosecond timestamps for window_start.
                observed = datetime.fromtimestamp(raw_time / 1_000_000_000.0, tz=timezone.utc)
                close = float(item.get("settlement_price") or item["close"])
                volume = max(0.0, float(item.get("volume", 0.0)))
            except (KeyError, TypeError, ValueError, OSError, OverflowError):
                continue
            if observed <= cutoff and close > 0.0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)

    @staticmethod
    def _ticker(kind: str, symbol: str) -> str:
        normalized = "".join(str(symbol).strip().upper().split())
        if not normalized:
            raise MassiveMultiAssetError("Massive symbol cannot be empty")
        if kind in {"stock", "etf", "future"}:
            return normalized
        if kind == "fx":
            return normalized if normalized.startswith("C:") else "C:" + normalized.replace("/", "")
        if kind == "crypto":
            return normalized if normalized.startswith("X:") else "X:" + normalized.replace("-", "").replace("/", "")
        return normalized

    def _get(self, path: str, *, params: dict[str, object]) -> Mapping[str, Any]:
        return self._get_url(f"{MASSIVE_BASE_URL}{path}", params={**params, "apiKey": self.api_key})

    def _get_url(self, url: str, *, params: dict[str, object]) -> Mapping[str, Any]:
        try:
            response = self._http_get(url, params=params, timeout=self.timeout)
        except requests.RequestException as error:
            raise MassiveMultiAssetError("Massive request failed", retryable=True) from error
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            retryable = status in {408, 425, 429} or 500 <= status <= 599
            raise MassiveMultiAssetError(
                f"Massive returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise MassiveMultiAssetError("Massive returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise MassiveMultiAssetError("Massive response must be an object")
        status_text = str(payload.get("status") or "OK").upper()
        if status_text not in {"OK", "SUCCESS"}:
            raise MassiveMultiAssetError("Massive rejected the request")
        return payload


__all__ = [
    "MASSIVE_BASE_URL",
    "MassiveFuturesContract",
    "MassiveMultiAssetError",
    "MassiveMultiAssetProvider",
]
