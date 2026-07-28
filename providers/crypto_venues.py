"""Independent public spot-crypto top-of-book validation adapters.

Coinbase Exchange and Kraken are represented as separate providers so a single
venue cannot satisfy the product's multi-venue crypto requirement.  These
adapters are market-data only: they expose no account, custody, or order-entry
authority.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from data.market import (
    CanonicalMarketDataProvider,
    MarketDataBatch,
    MarketDataProvenance,
    MarketDataQuery,
    MarketDataType,
    MarketQuote,
)
from data.observation import DataQualityState
from data.provider import ProviderError


COINBASE_BOOK_URL = (
    "https://api.exchange.coinbase.com/products/{product_id}/book"
)
KRAKEN_PRETRADE_URL = "https://api.kraken.com/0/public/PreTrade"


class CryptoVenueProviderError(ProviderError):
    """Raised when a public crypto venue cannot return a valid book."""


@dataclass(frozen=True, slots=True)
class CryptoVenueBinding:
    """Internal identity and venue-native symbols for one spot pair."""

    instrument_id: str
    quote_currency: str
    coinbase_product_id: str
    kraken_symbol: str

    def __post_init__(self) -> None:
        for field_name in (
            "instrument_id",
            "quote_currency",
            "coinbase_product_id",
            "kraken_symbol",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{field_name} cannot be empty")
            if field_name != "instrument_id":
                normalized = normalized.upper()
            object.__setattr__(self, field_name, normalized)


class CryptoVenueBindingRegistry:
    def __init__(self, bindings: tuple[CryptoVenueBinding, ...]) -> None:
        if not isinstance(bindings, tuple):
            raise TypeError("bindings must be a tuple")
        if not all(isinstance(item, CryptoVenueBinding) for item in bindings):
            raise TypeError("bindings must contain CryptoVenueBinding values")
        mapping: dict[str, CryptoVenueBinding] = {}
        for binding in bindings:
            if binding.instrument_id in mapping:
                raise ValueError(
                    f"duplicate crypto venue binding: {binding.instrument_id}"
                )
            mapping[binding.instrument_id] = binding
        self._bindings = mapping

    @property
    def bindings(self) -> tuple[CryptoVenueBinding, ...]:
        return tuple(
            self._bindings[key] for key in sorted(self._bindings)
        )

    def resolve(self, instrument_id: str) -> CryptoVenueBinding:
        try:
            return self._bindings[instrument_id]
        except KeyError as error:
            raise CryptoVenueProviderError(
                f"no crypto venue binding exists for {instrument_id!r}"
            ) from error


class _BaseCryptoVenueProvider(CanonicalMarketDataProvider):
    venue: str

    def __init__(
        self,
        *,
        bindings: CryptoVenueBindingRegistry,
        timeout: int = 15,
        clock: Callable[[], datetime] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        self.bindings = bindings
        self.timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._http_get = http_get or requests.get

    def _validate_query(self, query: MarketDataQuery) -> CryptoVenueBinding:
        if not isinstance(query, MarketDataQuery):
            raise TypeError("query must be MarketDataQuery")
        if query.data_type is not MarketDataType.QUOTE:
            raise CryptoVenueProviderError(
                f"{self.name} validation adapter supports quote requests only"
            )
        if query.start_at is not None:
            raise CryptoVenueProviderError(
                "top-of-book quote requests cannot include start_at"
            )
        if query.venue is not None and query.venue != self.venue:
            raise CryptoVenueProviderError(
                f"query venue must be {self.venue} for {self.name}"
            )
        return self.bindings.resolve(query.instrument_id)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value

    @staticmethod
    def _timestamp(value: object, *, fallback: datetime) -> datetime:
        if not isinstance(value, str) or not value.strip():
            return fallback
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise CryptoVenueProviderError(
                "venue timestamp is not valid ISO-8601"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CryptoVenueProviderError("venue timestamp must include an offset")
        return parsed

    def _response(self, url: str, *, params: dict[str, object] | None = None) -> Any:
        try:
            response = self._http_get(url, params=params or {}, timeout=self.timeout)
        except requests.RequestException as error:
            raise CryptoVenueProviderError(
                f"{self.name} market data request failed"
            ) from error
        status_code = int(getattr(response, "status_code", 0))
        if status_code < 200 or status_code >= 300:
            raise CryptoVenueProviderError(
                f"{self.name} returned HTTP {status_code}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise CryptoVenueProviderError(
                f"{self.name} returned invalid JSON"
            ) from error


class CoinbaseExchangeProvider(_BaseCryptoVenueProvider):
    """Public Coinbase Exchange level-one order book adapter."""

    venue = "COINBASE"

    @property
    def name(self) -> str:
        return "COINBASE_EXCHANGE"

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        binding = self._validate_query(query)
        retrieved_at = self._now()
        payload = self._response(
            COINBASE_BOOK_URL.format(product_id=binding.coinbase_product_id),
            params={"level": 1},
        )
        if not isinstance(payload, dict):
            raise CryptoVenueProviderError("Coinbase book must be a JSON object")
        bids = payload.get("bids")
        asks = payload.get("asks")
        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            raise CryptoVenueProviderError("Coinbase book is missing best bid or ask")
        bid = bids[0]
        ask = asks[0]
        if not isinstance(bid, list) or len(bid) < 2 or not isinstance(ask, list) or len(ask) < 2:
            raise CryptoVenueProviderError("Coinbase best bid or ask is malformed")
        observed_at = self._timestamp(payload.get("time"), fallback=retrieved_at)
        if observed_at > retrieved_at or observed_at > query.as_of:
            raise CryptoVenueProviderError(
                "Coinbase quote is future-known relative to the query"
            )
        quote = MarketQuote(
            instrument_id=binding.instrument_id,
            currency=binding.quote_currency,
            bid=float(bid[0]),
            ask=float(ask[0]),
            bid_size=float(bid[1]),
            ask_size=float(ask[1]),
            provenance=MarketDataProvenance(
                provider=self.name,
                venue=self.venue,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
                quality_state=DataQualityState.LIVE,
                provider_record_id=str(payload.get("sequence") or "level1"),
            ),
        )
        return MarketDataBatch(query=query, records=(quote,))


class KrakenSpotProvider(_BaseCryptoVenueProvider):
    """Public Kraken spot pre-trade top-of-book adapter."""

    venue = "KRAKEN"

    @property
    def name(self) -> str:
        return "KRAKEN_SPOT"

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        binding = self._validate_query(query)
        retrieved_at = self._now()
        payload = self._response(
            KRAKEN_PRETRADE_URL,
            params={"symbol": binding.kraken_symbol},
        )
        if not isinstance(payload, dict):
            raise CryptoVenueProviderError("Kraken response must be a JSON object")
        errors = payload.get("error")
        if isinstance(errors, list) and errors:
            raise CryptoVenueProviderError(
                "Kraken rejected the quote request: " + "; ".join(map(str, errors))
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise CryptoVenueProviderError("Kraken response is missing result")
        bids = result.get("bids")
        asks = result.get("asks")
        if not isinstance(bids, list) or not bids or not isinstance(asks, list) or not asks:
            raise CryptoVenueProviderError("Kraken book is missing best bid or ask")
        bid = bids[0]
        ask = asks[0]
        if not isinstance(bid, dict) or not isinstance(ask, dict):
            raise CryptoVenueProviderError("Kraken best bid or ask is malformed")
        timestamps = tuple(
            self._timestamp(item.get("publication_ts"), fallback=retrieved_at)
            for item in (bid, ask)
        )
        observed_at = max(timestamps)
        if observed_at > retrieved_at or observed_at > query.as_of:
            raise CryptoVenueProviderError(
                "Kraken quote is future-known relative to the query"
            )
        venue = str(result.get("venue") or self.venue).strip().upper()
        quote = MarketQuote(
            instrument_id=binding.instrument_id,
            currency=binding.quote_currency,
            bid=float(bid["price"]),
            ask=float(ask["price"]),
            bid_size=float(bid["qty"]),
            ask_size=float(ask["qty"]),
            provenance=MarketDataProvenance(
                provider=self.name,
                venue=venue,
                observed_at=observed_at,
                retrieved_at=retrieved_at,
                quality_state=DataQualityState.LIVE,
                provider_record_id=(
                    f"{binding.kraken_symbol}:{observed_at.isoformat()}"
                ),
            ),
        )
        # MarketDataBatch enforces query.venue, so preserve the configured adapter
        # venue for callers that explicitly request it.
        if query.venue is not None and quote.provenance.venue != query.venue:
            quote = MarketQuote(
                instrument_id=quote.instrument_id,
                currency=quote.currency,
                bid=quote.bid,
                ask=quote.ask,
                bid_size=quote.bid_size,
                ask_size=quote.ask_size,
                provenance=MarketDataProvenance(
                    provider=quote.provenance.provider,
                    venue=query.venue,
                    observed_at=quote.provenance.observed_at,
                    retrieved_at=quote.provenance.retrieved_at,
                    quality_state=quote.provenance.quality_state,
                    provider_record_id=quote.provenance.provider_record_id,
                ),
            )
        return MarketDataBatch(query=query, records=(quote,))


def load_crypto_venue_bindings(path: str | Path) -> CryptoVenueBindingRegistry:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CryptoVenueProviderError(
            f"cannot load crypto venue bindings from {str(source)!r}"
        ) from error
    if not isinstance(payload, dict):
        raise CryptoVenueProviderError("crypto venue binding file must be an object")
    if payload.get("schema_version") != "crypto-venue-bindings.v1":
        raise CryptoVenueProviderError("unsupported crypto venue binding schema")
    raw = payload.get("bindings")
    if not isinstance(raw, list):
        raise CryptoVenueProviderError("bindings must be a JSON array")
    bindings = tuple(
        CryptoVenueBinding(
            instrument_id=str(item["instrument_id"]),
            quote_currency=str(item["quote_currency"]),
            coinbase_product_id=str(item["coinbase_product_id"]),
            kraken_symbol=str(item["kraken_symbol"]),
        )
        for item in raw
        if isinstance(item, dict)
    )
    if len(bindings) != len(raw):
        raise CryptoVenueProviderError("every binding must be a JSON object")
    return CryptoVenueBindingRegistry(bindings)


def _configured_registry() -> CryptoVenueBindingRegistry:
    path = os.getenv("CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS")
    return (
        CryptoVenueBindingRegistry(())
        if not path
        else load_crypto_venue_bindings(path)
    )


def build_coinbase_exchange_provider() -> CoinbaseExchangeProvider:
    return CoinbaseExchangeProvider(bindings=_configured_registry())


def build_kraken_spot_provider() -> KrakenSpotProvider:
    return KrakenSpotProvider(bindings=_configured_registry())


__all__ = [
    "CoinbaseExchangeProvider",
    "CryptoVenueBinding",
    "CryptoVenueBindingRegistry",
    "CryptoVenueProviderError",
    "KrakenSpotProvider",
    "build_coinbase_exchange_provider",
    "build_kraken_spot_provider",
    "load_crypto_venue_bindings",
]
