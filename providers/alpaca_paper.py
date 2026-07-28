"""Free Alpaca paper-market adapters for the controlled listed-wrapper pilot.

The adapters expose account, asset, clock, and IEX quote evidence only. They do
not submit orders and cannot authorize real-money activity. The canonical paper
executor remains the sole fill and portfolio-state authority.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any

import requests

from cio import CandidateAssetClass
from governance import TradingSessionModel
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    InstrumentSession,
    InstrumentSessionStatus,
    MultiAssetQuote,
)


DEFAULT_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DEFAULT_DATA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_DATA_FEED = "iex"
SUPPORTED_PILOT_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.US_ETF,
        CandidateAssetClass.CASH_EQUIVALENT,
    }
)


class AlpacaPaperProviderError(RuntimeError):
    """Raised when Alpaca cannot provide valid free paper-market evidence."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _environment_value(*names: str, default: str = "") -> str:
    """Return the first non-empty credential/configuration alias without logging it."""

    for name in names:
        value = os.getenv(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AlpacaPaperProviderError(f"{field_name} is unavailable")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise AlpacaPaperProviderError(f"{field_name} is not valid ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AlpacaPaperProviderError(f"{field_name} must include a UTC offset")
    return parsed


@dataclass(frozen=True, slots=True)
class AlpacaPaperSettings:
    api_key_id: str
    secret_key: str
    paper_base_url: str = DEFAULT_PAPER_BASE_URL
    data_base_url: str = DEFAULT_DATA_BASE_URL
    data_feed: str = DEFAULT_DATA_FEED
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        for name in (
            "api_key_id",
            "secret_key",
            "paper_base_url",
            "data_base_url",
            "data_feed",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds,
            int,
        ):
            raise TypeError("timeout_seconds must be an integer")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")

    @classmethod
    def from_env(cls) -> "AlpacaPaperSettings":
        settings = cls(
            api_key_id=_environment_value(
                "APCA_API_KEY_ID",
                "ALPACA_API_KEY_ID",
                "ALPACA_API_KEY",
            ),
            secret_key=_environment_value(
                "APCA_API_SECRET_KEY",
                "ALPACA_API_SECRET_KEY",
                "ALPACA_SECRET_KEY",
                "ALPACA_API_SECRET",
            ),
            paper_base_url=_environment_value(
                "APCA_API_BASE_URL",
                "ALPACA_API_BASE_URL",
                default=DEFAULT_PAPER_BASE_URL,
            ),
            data_base_url=_environment_value(
                "APCA_DATA_BASE_URL",
                "ALPACA_DATA_BASE_URL",
                default=DEFAULT_DATA_BASE_URL,
            ),
            data_feed=_environment_value(
                "APCA_DATA_FEED",
                "ALPACA_DATA_FEED",
                default=DEFAULT_DATA_FEED,
            ),
        )
        host = (urlparse(settings.paper_base_url).hostname or "").lower()
        if host != "paper-api.alpaca.markets":
            raise AlpacaPaperProviderError(
                "APCA_API_BASE_URL must use the Alpaca paper endpoint; live brokerage endpoints are prohibited"
            )
        if settings.data_feed.lower() != "iex":
            raise AlpacaPaperProviderError(
                "the free paper pilot requires APCA_DATA_FEED=iex"
            )
        return settings


class AlpacaPaperClient:
    """Small authenticated client restricted to non-order Alpaca endpoints."""

    def __init__(
        self,
        settings: AlpacaPaperSettings,
        *,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        if not isinstance(settings, AlpacaPaperSettings):
            raise TypeError("settings must be AlpacaPaperSettings")
        self.settings = settings
        self._http_get = http_get or requests.get

    @property
    def headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.settings.api_key_id,
            "APCA-API-SECRET-KEY": self.settings.secret_key,
            "Accept": "application/json",
        }

    def _get(
        self,
        base_url: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
    ) -> Mapping[str, Any]:
        try:
            response = self._http_get(
                base_url.rstrip("/") + path,
                headers=self.headers,
                params=dict(params or {}),
                timeout=self.settings.timeout_seconds,
            )
        except requests.RequestException as error:
            raise AlpacaPaperProviderError("Alpaca request failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise AlpacaPaperProviderError(f"Alpaca returned HTTP {status}")
        try:
            payload = response.json()
        except ValueError as error:
            raise AlpacaPaperProviderError("Alpaca returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise AlpacaPaperProviderError("Alpaca response must be a JSON object")
        return payload

    def account(self) -> Mapping[str, Any]:
        return self._get(self.settings.paper_base_url, "/v2/account")

    def clock(self) -> Mapping[str, Any]:
        return self._get(self.settings.paper_base_url, "/v2/clock")

    def asset(self, symbol: str) -> Mapping[str, Any]:
        normalized = _text(symbol, field_name="symbol").upper()
        return self._get(self.settings.paper_base_url, f"/v2/assets/{normalized}")

    def latest_quotes(self, symbols: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
        normalized = tuple(
            dict.fromkeys(_text(item, field_name="symbol").upper() for item in symbols)
        )
        if not normalized:
            return {}
        payload = self._get(
            self.settings.data_base_url,
            "/v2/stocks/quotes/latest",
            params={
                "symbols": ",".join(normalized),
                "feed": self.settings.data_feed.lower(),
            },
        )
        quotes = payload.get("quotes")
        if not isinstance(quotes, Mapping):
            raise AlpacaPaperProviderError("Alpaca latest-quotes response is missing quotes")
        result: dict[str, Mapping[str, Any]] = {}
        for symbol in normalized:
            quote = quotes.get(symbol)
            if not isinstance(quote, Mapping):
                raise AlpacaPaperProviderError(f"Alpaca quote is unavailable for {symbol}")
            result[symbol] = quote
        return result


class AlpacaPaperSessionProvider:
    """Map the Alpaca paper clock to canonical listed-security sessions."""

    def __init__(self, client: AlpacaPaperClient) -> None:
        self.client = client

    def session(
        self,
        profile: MultiAssetInstrumentProfile,
        *,
        session_model: TradingSessionModel,
        as_of: datetime,
    ) -> InstrumentSession:
        if profile.asset_class not in SUPPORTED_PILOT_CLASSES:
            raise AlpacaPaperProviderError(
                f"{profile.asset_class.value} is outside the free listed-wrapper pilot"
            )
        if session_model is not TradingSessionModel.EXCHANGE_LOCAL:
            raise AlpacaPaperProviderError(
                "free listed-wrapper instruments require exchange-local sessions"
            )
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        payload = self.client.clock()
        observed_at = _timestamp(payload.get("timestamp"), field_name="Alpaca clock timestamp")
        if observed_at > as_of:
            raise AlpacaPaperProviderError(
                "Alpaca clock is future-known relative to execution"
            )
        status = (
            InstrumentSessionStatus.OPEN
            if payload.get("is_open") is True
            else InstrumentSessionStatus.CLOSED
        )
        return InstrumentSession(
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            session_model=session_model,
            as_of=observed_at,
            status=status,
            source_identifier="alpaca-paper-clock:v2",
        )


class AlpacaPaperQuoteProvider:
    """Convert free IEX top-of-book evidence into canonical paper quotes."""

    def __init__(self, client: AlpacaPaperClient) -> None:
        self.client = client

    @staticmethod
    def _positive(value: object, *, field_name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AlpacaPaperProviderError(f"{field_name} must be numeric")
        result = float(value)
        if result <= 0.0:
            raise AlpacaPaperProviderError(f"{field_name} must be positive")
        return result

    def quotes(
        self,
        profiles: tuple[MultiAssetInstrumentProfile, ...],
        *,
        as_of: datetime,
    ) -> Mapping[str, MultiAssetQuote]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(profiles, tuple):
            raise TypeError("profiles must be a tuple")
        symbols: list[str] = []
        for profile in profiles:
            if profile.asset_class not in SUPPORTED_PILOT_CLASSES:
                raise AlpacaPaperProviderError(
                    f"{profile.symbol} is outside the free listed-wrapper pilot"
                )
            if profile.price_currency != "USD" or profile.settlement_currency != "USD":
                raise AlpacaPaperProviderError(
                    f"{profile.symbol} must price and settle in USD"
                )
            asset = self.client.asset(profile.symbol)
            if str(asset.get("status", "")).lower() != "active":
                raise AlpacaPaperProviderError(f"{profile.symbol} is not active at Alpaca")
            if asset.get("tradable") is not True:
                raise AlpacaPaperProviderError(f"{profile.symbol} is not tradable at Alpaca")
            if asset.get("fractionable") is not True:
                raise AlpacaPaperProviderError(
                    f"{profile.symbol} is not fractionable and is excluded from the $250,000 pilot"
                )
            symbols.append(profile.symbol)

        raw_quotes = self.client.latest_quotes(symbols)
        result: dict[str, MultiAssetQuote] = {}
        for profile in profiles:
            raw = raw_quotes[profile.symbol]
            bid = self._positive(raw.get("bp"), field_name=f"{profile.symbol} bid")
            ask = self._positive(raw.get("ap"), field_name=f"{profile.symbol} ask")
            if ask < bid:
                raise AlpacaPaperProviderError(
                    f"{profile.symbol} quote is crossed"
                )
            bid_size = self._positive(
                raw.get("bs"),
                field_name=f"{profile.symbol} bid size",
            )
            ask_size = self._positive(
                raw.get("as"),
                field_name=f"{profile.symbol} ask size",
            )
            observed_at = _timestamp(
                raw.get("t"),
                field_name=f"{profile.symbol} quote timestamp",
            )
            if observed_at > as_of:
                raise AlpacaPaperProviderError(
                    f"{profile.symbol} quote is future-known relative to execution"
                )
            available = min(bid * bid_size, ask * ask_size)
            result[profile.symbol] = MultiAssetQuote(
                symbol=profile.symbol,
                instrument_identifier=profile.instrument_identifier,
                venue=profile.venue,
                observed_at=observed_at,
                bid=bid,
                ask=ask,
                last=(bid + ask) / 2.0,
                available_base_notional=available,
                price_currency="USD",
                fx_rate_to_base=1.0,
                fx_observed_at=observed_at,
                quote_source_identifier=(
                    f"alpaca-paper:{self.client.settings.data_feed.lower()}:latest-quote"
                ),
                fx_source_identifier="usd-base-rate:1.0",
                quote_certification_identifier=(
                    f"free-paper-pilot-quote:{profile.instrument_identifier}:"
                    f"{observed_at.isoformat()}"
                ),
                halted=False,
            )
        return result


def create_alpaca_paper_client() -> AlpacaPaperClient:
    return AlpacaPaperClient(AlpacaPaperSettings.from_env())


def create_alpaca_paper_session_provider() -> AlpacaPaperSessionProvider:
    return AlpacaPaperSessionProvider(create_alpaca_paper_client())


def create_alpaca_paper_quote_provider() -> AlpacaPaperQuoteProvider:
    return AlpacaPaperQuoteProvider(create_alpaca_paper_client())


__all__ = [
    "AlpacaPaperClient",
    "AlpacaPaperProviderError",
    "AlpacaPaperQuoteProvider",
    "AlpacaPaperSessionProvider",
    "AlpacaPaperSettings",
    "SUPPORTED_PILOT_CLASSES",
    "create_alpaca_paper_client",
    "create_alpaca_paper_quote_provider",
    "create_alpaca_paper_session_provider",
]
