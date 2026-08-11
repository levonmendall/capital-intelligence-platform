"""Governed supplemental quote cross-checks across independent U.S. market sources.

These sources corroborate broad market observations. They never provide canonical
execution quotes, paper-order authority, or real-money authority.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any

import requests

from provider_environment import provider_environment_value


class SupplementalQuoteError(RuntimeError):
    """Raised when a supplemental quote cannot be retrieved or reconciled."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _price(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or value in (None, ""):
        raise ValueError(f"{field_name} must contain a price")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return result


@dataclass(frozen=True, slots=True)
class SupplementalQuote:
    provider: str
    symbol: str
    price: float
    observed_at: datetime
    retrieved_at: datetime
    source_field: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, field_name="provider"))
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        object.__setattr__(self, "price", _price(self.price, field_name="price"))
        for field_name in ("observed_at", "retrieved_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.observed_at > self.retrieved_at:
            raise ValueError("observed_at cannot follow retrieved_at")
        object.__setattr__(
            self, "source_field", _text(self.source_field, field_name="source_field")
        )


@dataclass(frozen=True, slots=True)
class SupplementalQuoteCrossCheck:
    symbol: str
    quotes: tuple[SupplementalQuote, ...]
    maximum_divergence_bps: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        if not isinstance(self.quotes, tuple):
            raise TypeError("quotes must be a tuple")
        if not all(isinstance(item, SupplementalQuote) for item in self.quotes):
            raise TypeError("quotes must contain SupplementalQuote values")
        if any(item.symbol != self.symbol for item in self.quotes):
            raise ValueError("quote symbols must match the cross-check symbol")
        if isinstance(self.maximum_divergence_bps, bool):
            raise TypeError("maximum_divergence_bps must be numeric")
        threshold = float(self.maximum_divergence_bps)
        if not isfinite(threshold) or threshold < 0:
            raise ValueError("maximum_divergence_bps must be finite and nonnegative")
        object.__setattr__(self, "maximum_divergence_bps", threshold)

    @property
    def divergence_bps(self) -> float | None:
        if len(self.quotes) < 2:
            return None
        prices = [item.price for item in self.quotes]
        midpoint = sum(prices) / len(prices)
        return round((max(prices) - min(prices)) / midpoint * 10_000, 6)

    @property
    def state(self) -> str:
        divergence = self.divergence_bps
        if divergence is None:
            return "partial"
        return "agree" if divergence <= self.maximum_divergence_bps else "disagree"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "supplemental-quote-cross-check.v1",
            "symbol": self.symbol,
            "state": self.state,
            "maximum_divergence_bps": self.maximum_divergence_bps,
            "divergence_bps": self.divergence_bps,
            "quotes": [
                {
                    "provider": item.provider,
                    "symbol": item.symbol,
                    "price": item.price,
                    "observed_at": item.observed_at.isoformat(),
                    "retrieved_at": item.retrieved_at.isoformat(),
                    "source_field": item.source_field,
                }
                for item in self.quotes
            ],
            "canonical_execution_authority": False,
            "paper_execution_authority": False,
            "real_money_authorized": False,
            "secret_values_disclosed": False,
        }


class SupplementalQuoteProvider:
    """Retrieve bounded corroborating quotes from configured supplemental sources."""

    def __init__(
        self,
        *,
        alpha_vantage_key: str | None = None,
        twelve_data_key: str | None = None,
        tradier_key: str | None = None,
        timeout: int = 20,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.alpha_vantage_key = (
            alpha_vantage_key
            or provider_environment_value("ALPHA_VANTAGE_API_KEY")
            or provider_environment_value("ALPHAVANTAGE_API_KEY")
        )
        self.twelve_data_key = (
            twelve_data_key
            or provider_environment_value("TWELVE_DATA_API_KEY")
            or provider_environment_value("TWELVE_API_KEY")
        )
        self.tradier_key = (
            tradier_key
            or provider_environment_value("TRADIER_API_KEY")
            or provider_environment_value("TRADIER_API_TOKEN")
        )
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_get = http_get or requests.get

    def cross_check(
        self, symbol: str, *, maximum_divergence_bps: float = 100.0
    ) -> SupplementalQuoteCrossCheck:
        normalized = _text(symbol, field_name="symbol").upper()
        quotes: list[SupplementalQuote] = []
        errors: list[str] = []
        if self.alpha_vantage_key:
            try:
                quotes.append(self._alpha_vantage(normalized))
            except SupplementalQuoteError as error:
                errors.append(f"alpha_vantage:{error}")
        else:
            errors.append("alpha_vantage:credential_missing")
        if self.twelve_data_key:
            try:
                quotes.append(self._twelve_data(normalized))
            except SupplementalQuoteError as error:
                errors.append(f"twelve_data:{error}")
        else:
            errors.append("twelve_data:credential_missing")
        if self.tradier_key:
            try:
                quotes.append(self._tradier(normalized))
            except SupplementalQuoteError as error:
                errors.append(f"tradier:{error}")
        else:
            errors.append("tradier:credential_missing")
        if not quotes:
            raise SupplementalQuoteError("; ".join(errors))
        return SupplementalQuoteCrossCheck(
            symbol=normalized,
            quotes=tuple(quotes),
            maximum_divergence_bps=maximum_divergence_bps,
        )

    def _alpha_vantage(self, symbol: str) -> SupplementalQuote:
        retrieved_at = self._now()
        response = self._get(
            "https://www.alphavantage.co/query",
            params={
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": self.alpha_vantage_key,
            },
            provider="Alpha Vantage",
        )
        if not isinstance(response, dict):
            raise SupplementalQuoteError("Alpha Vantage response must be an object")
        for field in ("Error Message", "Information", "Note"):
            if response.get(field):
                raise SupplementalQuoteError(f"Alpha Vantage returned {field}")
        quote = response.get("Global Quote")
        if not isinstance(quote, dict):
            raise SupplementalQuoteError("Alpha Vantage quote is missing")
        returned_symbol = str(quote.get("01. symbol") or "").upper()
        if returned_symbol != symbol:
            raise SupplementalQuoteError("Alpha Vantage symbol mismatch")
        observed_at = retrieved_at
        day = quote.get("07. latest trading day")
        if isinstance(day, str) and day.strip():
            try:
                observed_at = datetime.fromisoformat(day.strip()).replace(tzinfo=timezone.utc)
            except ValueError:
                observed_at = retrieved_at
        return SupplementalQuote(
            provider="ALPHA_VANTAGE",
            symbol=symbol,
            price=_price(quote.get("05. price"), field_name="Alpha Vantage price"),
            observed_at=min(observed_at, retrieved_at),
            retrieved_at=retrieved_at,
            source_field="Global Quote.05. price",
        )

    def _twelve_data(self, symbol: str) -> SupplementalQuote:
        retrieved_at = self._now()
        response = self._get(
            "https://api.twelvedata.com/quote",
            params={"symbol": symbol, "apikey": self.twelve_data_key},
            provider="Twelve Data",
        )
        if not isinstance(response, dict):
            raise SupplementalQuoteError("Twelve Data response must be an object")
        if str(response.get("status") or "").lower() == "error" or response.get("code"):
            raise SupplementalQuoteError("Twelve Data rejected the quote request")
        returned_symbol = str(response.get("symbol") or "").upper()
        if returned_symbol != symbol:
            raise SupplementalQuoteError("Twelve Data symbol mismatch")
        observed_at = retrieved_at
        timestamp = response.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            observed_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
        elif isinstance(response.get("datetime"), str):
            try:
                parsed = datetime.fromisoformat(str(response["datetime"]).replace("Z", "+00:00"))
                observed_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                observed_at = retrieved_at
        source_field = "close" if response.get("close") not in (None, "") else "price"
        return SupplementalQuote(
            provider="TWELVE_DATA",
            symbol=symbol,
            price=_price(response.get(source_field), field_name="Twelve Data price"),
            observed_at=min(observed_at.astimezone(timezone.utc), retrieved_at),
            retrieved_at=retrieved_at,
            source_field=source_field,
        )

    def _tradier(self, symbol: str) -> SupplementalQuote:
        retrieved_at = self._now()
        response = self._get(
            "https://api.tradier.com/v1/markets/quotes",
            params={"symbols": symbol, "greeks": "false"},
            provider="Tradier",
            headers={
                "Authorization": f"Bearer {self.tradier_key}",
                "Accept": "application/json",
            },
        )
        if not isinstance(response, dict):
            raise SupplementalQuoteError("Tradier response must be an object")
        quotes_payload = response.get("quotes")
        if not isinstance(quotes_payload, dict):
            raise SupplementalQuoteError("Tradier quote container is missing")
        quote = quotes_payload.get("quote")
        if isinstance(quote, list):
            quote = next(
                (
                    item
                    for item in quote
                    if isinstance(item, dict)
                    and str(item.get("symbol") or "").upper() == symbol
                ),
                None,
            )
        if not isinstance(quote, dict):
            raise SupplementalQuoteError("Tradier quote is missing")
        returned_symbol = str(quote.get("symbol") or "").upper()
        if returned_symbol != symbol:
            raise SupplementalQuoteError("Tradier symbol mismatch")
        observed_at = retrieved_at
        trade_date = quote.get("trade_date")
        if isinstance(trade_date, (int, float)) and not isinstance(trade_date, bool):
            value = float(trade_date)
            # Tradier publishes market timestamps in epoch milliseconds.
            if value > 10_000_000_000:
                value /= 1000.0
            try:
                observed_at = datetime.fromtimestamp(value, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                observed_at = retrieved_at
        source_field = next(
            (field for field in ("last", "close", "prevclose") if quote.get(field) not in (None, "")),
            None,
        )
        if source_field is None:
            raise SupplementalQuoteError("Tradier quote has no usable price")
        return SupplementalQuote(
            provider="TRADIER",
            symbol=symbol,
            price=_price(quote.get(source_field), field_name="Tradier price"),
            observed_at=min(observed_at, retrieved_at),
            retrieved_at=retrieved_at,
            source_field=source_field,
        )

    def _get(
        self,
        url: str,
        *,
        params: dict[str, object],
        provider: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = self._http_get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise SupplementalQuoteError(f"{provider} request failed") from error
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            raise SupplementalQuoteError(
                f"{provider} returned HTTP {status_code or 'unknown'}"
            )
        try:
            return response.json()
        except (TypeError, ValueError) as error:
            raise SupplementalQuoteError(f"{provider} returned invalid JSON") from error

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


__all__ = [
    "SupplementalQuote",
    "SupplementalQuoteCrossCheck",
    "SupplementalQuoteError",
    "SupplementalQuoteProvider",
]
