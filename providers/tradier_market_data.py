"""Tradier market-data evidence for U.S. equities/ETFs and active options.

Tradier is a supplemental independent source. Historical equity/ETF pricing may satisfy
an already-established exact-symbol history role. Active option chains corroborate
current contract existence/quotes only; they never replace Databento/Massive completed-
session OPRA history and never grant execution authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from provider_environment import provider_environment_value


TRADIER_BASE_URL = "https://api.tradier.com/v1"


class TradierMarketDataError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TradierOptionChainEvidence:
    underlying: str
    expiration: date
    option_symbol: str
    strike: float
    option_type: str
    bid: float | None
    ask: float | None
    last: float | None
    observed_at: datetime
    source_identifier: str


class TradierMarketDataProvider:
    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: int = 15,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.token = (
            token
            or provider_environment_value("TRADIER_API_KEY")
            or provider_environment_value("TRADIER_API_TOKEN")
        )
        self.timeout = int(timeout)
        if self.timeout < 1:
            raise ValueError("timeout must be positive")
        self._http_get = http_get or requests.get

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def daily_history(
        self,
        symbol: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[dict[str, object], ...]:
        if not self.token:
            raise TradierMarketDataError("Tradier token is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        normalized = str(symbol).strip().upper().replace(".", "/")
        if not normalized:
            raise TradierMarketDataError("Tradier symbol cannot be empty")
        cutoff = as_of.astimezone(timezone.utc)
        start = cutoff - timedelta(days=history_days)
        payload = self._get(
            "/markets/history",
            params={
                "symbol": normalized,
                "interval": "daily",
                "start": start.date().isoformat(),
                "end": cutoff.date().isoformat(),
            },
        )
        history = payload.get("history")
        raw = history.get("day") if isinstance(history, Mapping) else None
        if isinstance(raw, Mapping):
            raw = [raw]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise TradierMarketDataError("Tradier history response is missing daily bars")
        rows: list[dict[str, object]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            try:
                observed = datetime.fromisoformat(str(item["date"])[:10]).replace(tzinfo=timezone.utc)
                close = float(item["close"])
                volume = max(0.0, float(item.get("volume", 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
            if observed <= cutoff and close > 0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)

    def active_option_chain(
        self,
        underlying: str,
        expiration: date,
        *,
        as_of: datetime,
    ) -> tuple[TradierOptionChainEvidence, ...]:
        if not self.token:
            raise TradierMarketDataError("Tradier token is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if expiration < as_of.date():
            raise TradierMarketDataError(
                "Tradier option-chain corroboration is limited to active expirations"
            )
        symbol = str(underlying).strip().upper().replace(".", "/")
        payload = self._get(
            "/markets/options/chains",
            params={"symbol": symbol, "expiration": expiration.isoformat(), "greeks": "false"},
        )
        options = payload.get("options")
        raw = options.get("option") if isinstance(options, Mapping) else None
        if isinstance(raw, Mapping):
            raw = [raw]
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise TradierMarketDataError("Tradier active option chain is missing")
        observed = as_of.astimezone(timezone.utc)
        result: list[TradierOptionChainEvidence] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            option_symbol = str(item.get("symbol") or "").strip().upper()
            option_type = str(item.get("option_type") or "").strip().lower()
            try:
                strike = float(item.get("strike"))
            except (TypeError, ValueError):
                continue
            if not option_symbol or option_type not in {"call", "put"} or strike <= 0:
                continue
            result.append(
                TradierOptionChainEvidence(
                    underlying=symbol,
                    expiration=expiration,
                    option_symbol=option_symbol,
                    strike=strike,
                    option_type=option_type,
                    bid=self._optional_price(item.get("bid")),
                    ask=self._optional_price(item.get("ask")),
                    last=self._optional_price(item.get("last")),
                    observed_at=observed,
                    source_identifier=(
                        f"tradier:active-option-chain:{symbol}:{expiration.isoformat()}:{option_symbol}"
                    ),
                )
            )
        if not result:
            raise TradierMarketDataError("Tradier returned no valid active option contracts")
        return tuple(result)

    @staticmethod
    def _optional_price(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    def _get(self, path: str, *, params: dict[str, object]) -> Mapping[str, Any]:
        try:
            response = self._http_get(
                f"{TRADIER_BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise TradierMarketDataError("Tradier request failed", retryable=True) from error
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            retryable = status in {408, 425, 429} or 500 <= status <= 599
            raise TradierMarketDataError(
                f"Tradier returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise TradierMarketDataError("Tradier returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise TradierMarketDataError("Tradier response must be an object")
        return payload


__all__ = [
    "TRADIER_BASE_URL",
    "TradierMarketDataError",
    "TradierMarketDataProvider",
    "TradierOptionChainEvidence",
]
