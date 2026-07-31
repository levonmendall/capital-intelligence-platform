"""Direct futures, spot-FX, and spot-crypto evidence and paper quote adapters.

The module is intentionally paper-only. It retrieves public point-in-time market
evidence, translates it into the canonical candidate and execution contracts, and
never submits an order or authorizes real money.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote as urlquote

import requests

from cio import CandidateAssetClass
from governance import TradingSessionModel
from operations.free_paper_pilot import FreePaperPilotInstrument
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    InstrumentSession,
    InstrumentSessionStatus,
    MultiAssetQuote,
)
from providers.alpaca_paper import (
    SUPPORTED_PILOT_CLASSES,
    AlpacaPaperQuoteProvider,
    AlpacaPaperSessionProvider,
    create_alpaca_paper_client,
)

DEFAULT_DIRECT_UNIVERSE_PATH = Path("config/direct_global_market_universe.json")
DEFAULT_CHART_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
DIRECT_EXECUTION_CLASSES = frozenset(
    {CandidateAssetClass.FX, CandidateAssetClass.CRYPTO, CandidateAssetClass.FUTURE}
)


class DirectGlobalMarketError(RuntimeError):
    """Raised when direct-market evidence is unavailable or invalid."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DirectGlobalMarketError(f"{field_name} must be numeric")
    result = float(value)
    if result <= 0.0:
        raise DirectGlobalMarketError(f"{field_name} must be positive")
    return result


def _timestamp(value: object, *, field_name: str) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise DirectGlobalMarketError(f"{field_name} is unavailable")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DirectGlobalMarketError(f"{field_name} is invalid") from error
    return _aware(parsed, field_name=field_name)


@dataclass(frozen=True, slots=True)
class DirectGlobalMarketUniverse:
    identifier: str
    provider_identifier: str
    instruments: tuple[FreePaperPilotInstrument, ...]
    limitations: tuple[str, ...]
    schema_version: str = "direct-global-market-universe.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.provider_identifier.strip():
            raise ValueError("direct-market universe identifiers cannot be empty")
        if not self.instruments:
            raise ValueError("direct-market universe requires instruments")
        if any(
            item.execution_asset_class not in DIRECT_EXECUTION_CLASSES
            for item in self.instruments
        ):
            raise ValueError("direct-market universe may contain only FX, crypto, and futures")
        symbols = tuple(item.symbol for item in self.instruments)
        if len(symbols) != len(set(symbols)):
            raise ValueError("direct-market symbols must be unique")

    @property
    def symbol_map(self) -> dict[str, FreePaperPilotInstrument]:
        return {item.symbol: item for item in self.instruments}


def load_direct_global_market_universe(
    path: str | Path = DEFAULT_DIRECT_UNIVERSE_PATH,
) -> DirectGlobalMarketUniverse:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load direct-market universe {str(source)!r}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("direct-market universe must be an object")
    if payload.get("schema_version") != "direct-global-market-universe.v1":
        raise ValueError("unsupported direct-market universe schema")
    raw = payload.get("instruments")
    if not isinstance(raw, list):
        raise ValueError("direct-market instruments must be a list")
    instruments = tuple(
        FreePaperPilotInstrument(
            symbol=str(item["symbol"]),
            instrument_identifier=str(item["instrument_identifier"]),
            name=str(item["name"]),
            execution_asset_class=CandidateAssetClass(
                str(item["execution_asset_class"])
            ),
            economic_exposure=str(item["economic_exposure"]),
            venue=str(item["venue"]),
            country_code=str(item["country_code"]),
            currency=str(item["currency"]),
            settlement_currency=str(item.get("settlement_currency", "USD")),
            instrument_type=str(item["instrument_type"]),
            maximum_weight=float(item["maximum_weight"]),
            provider_symbol=str(item["provider_symbol"]),
            contract_multiplier=float(item.get("contract_multiplier", 1.0)),
            trading_session_model=TradingSessionModel(
                str(item["trading_session_model"])
            ),
            quote_spread_bps=float(item.get("quote_spread_bps", 5.0)),
        )
        for item in raw
        if isinstance(item, Mapping)
    )
    if len(instruments) != len(raw):
        raise ValueError("every direct-market instrument must be an object")
    return DirectGlobalMarketUniverse(
        identifier=str(payload["identifier"]),
        provider_identifier=str(payload["provider_identifier"]),
        instruments=instruments,
        limitations=tuple(str(item) for item in payload.get("limitations", ())),
        schema_version=str(payload["schema_version"]),
    )


class DirectGlobalMarketClient:
    """Public chart client normalized to the existing Alpaca-like evidence shape."""

    def __init__(
        self,
        universe: DirectGlobalMarketUniverse | None = None,
        *,
        http_get: Callable[..., Any] | None = None,
        chart_base_url: str = DEFAULT_CHART_BASE_URL,
        timeout_seconds: int = 15,
    ) -> None:
        self.universe = universe or load_direct_global_market_universe()
        self.http_get = http_get or requests.get
        self.chart_base_url = chart_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _instrument(self, symbol: str) -> FreePaperPilotInstrument:
        normalized = str(symbol).strip().upper()
        try:
            return self.universe.symbol_map[normalized]
        except KeyError as error:
            raise DirectGlobalMarketError(
                f"{normalized} is outside the governed direct-market universe"
            ) from error

    def _chart(
        self,
        instrument: FreePaperPilotInstrument,
        *,
        interval: str,
        range_value: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Mapping[str, Any]:
        params: dict[str, object] = {
            "interval": interval,
            "events": "history",
            "includePrePost": "true",
        }
        if range_value is not None:
            params["range"] = range_value
        else:
            if start is None or end is None:
                raise ValueError("chart start and end are required")
            params["period1"] = int(_aware(start, field_name="start").timestamp())
            params["period2"] = int(_aware(end, field_name="end").timestamp())
        url = f"{self.chart_base_url}/{urlquote(instrument.provider_symbol or instrument.symbol, safe='')}"
        try:
            response = self.http_get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "capital-intelligence-paper-research/1.0",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise DirectGlobalMarketError("direct-market request failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise DirectGlobalMarketError(
                f"direct-market provider returned HTTP {status}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise DirectGlobalMarketError(
                "direct-market provider returned invalid JSON"
            ) from error
        try:
            result = payload["chart"]["result"][0]
        except (KeyError, IndexError, TypeError) as error:
            raise DirectGlobalMarketError(
                f"direct-market chart is unavailable for {instrument.symbol}"
            ) from error
        if not isinstance(result, Mapping):
            raise DirectGlobalMarketError("direct-market chart result must be an object")
        return result

    @staticmethod
    def _rows(result: Mapping[str, Any]) -> tuple[dict[str, object], ...]:
        timestamps = result.get("timestamp")
        indicators = result.get("indicators")
        quote_rows = indicators.get("quote") if isinstance(indicators, Mapping) else None
        quote_data = (
            quote_rows[0]
            if isinstance(quote_rows, Sequence)
            and not isinstance(quote_rows, (str, bytes))
            and quote_rows
            and isinstance(quote_rows[0], Mapping)
            else {}
        )
        closes = quote_data.get("close", ())
        volumes = quote_data.get("volume", ())
        if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
            return ()
        rows: list[dict[str, object]] = []
        for index, raw_time in enumerate(timestamps):
            try:
                close = closes[index]
            except (IndexError, TypeError):
                continue
            if close is None:
                continue
            price = _positive(close, field_name="direct-market close")
            raw_volume = 0.0
            try:
                raw_volume = volumes[index] or 0.0
            except (IndexError, TypeError):
                pass
            rows.append(
                {
                    "t": _timestamp(raw_time, field_name="direct-market timestamp").isoformat(),
                    "c": price,
                    "v": max(0.0, float(raw_volume)),
                }
            )
        return tuple(rows)

    def historical_bars(
        self,
        symbols: Sequence[str],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
        limit: int = 10_000,
    ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        if timeframe != "1Day":
            raise ValueError("direct-market evidence currently supports 1Day bars")
        if start >= end:
            raise ValueError("historical bar start must predate end")
        result: dict[str, tuple[Mapping[str, Any], ...]] = {}
        for symbol in tuple(dict.fromkeys(str(item).strip().upper() for item in symbols)):
            instrument = self._instrument(symbol)
            rows = self._rows(
                self._chart(
                    instrument,
                    interval="1d",
                    start=start,
                    end=end,
                )
            )
            if not rows:
                raise DirectGlobalMarketError(
                    f"historical bars are unavailable for {symbol}"
                )
            result[symbol] = rows[-limit:]
        return result

    def latest_quotes(
        self,
        symbols: Sequence[str],
    ) -> Mapping[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for symbol in tuple(dict.fromkeys(str(item).strip().upper() for item in symbols)):
            instrument = self._instrument(symbol)
            chart = self._chart(instrument, interval="5m", range_value="5d")
            rows = self._rows(chart)
            if not rows:
                raise DirectGlobalMarketError(f"latest price is unavailable for {symbol}")
            latest = rows[-1]
            price = _positive(latest["c"], field_name=f"{symbol} latest")
            half_spread = price * instrument.quote_spread_bps / 20_000.0
            observed = _timestamp(latest["t"], field_name=f"{symbol} quote timestamp")
            result[symbol] = {
                "bp": price - half_spread,
                "ap": price + half_spread,
                "bs": max(1.0, 5_000_000.0 / price),
                "as": max(1.0, 5_000_000.0 / price),
                "t": observed.isoformat(),
                "last": price,
            }
        return result

    def snapshots(
        self,
        symbols: Sequence[str],
    ) -> Mapping[str, Mapping[str, Any]]:
        snapshots: dict[str, Mapping[str, Any]] = {}
        for symbol in tuple(dict.fromkeys(str(item).strip().upper() for item in symbols)):
            instrument = self._instrument(symbol)
            chart = self._chart(instrument, interval="1d", range_value="1mo")
            rows = self._rows(chart)
            if not rows:
                continue
            latest = rows[-1]
            previous = rows[-2] if len(rows) > 1 else latest
            snapshots[symbol] = {
                "latestTrade": {"p": latest["c"], "t": latest["t"]},
                "dailyBar": {"c": latest["c"], "t": latest["t"]},
                "prevDailyBar": {"c": previous["c"], "t": previous["t"]},
            }
        return snapshots

    @staticmethod
    def session_is_open(
        instrument: FreePaperPilotInstrument,
        *,
        as_of: datetime,
    ) -> bool:
        now = _aware(as_of, field_name="as_of")
        if instrument.execution_asset_class is CandidateAssetClass.CRYPTO:
            return True
        weekday = now.weekday()
        if weekday < 4:
            return True
        if weekday == 4:
            return now.hour < 22
        if weekday == 6:
            return now.hour >= 22
        return False

    def any_open(self, symbols: Sequence[str], *, as_of: datetime) -> bool:
        return any(
            self.session_is_open(self._instrument(symbol), as_of=as_of)
            for symbol in symbols
        )


class DirectPaperSessionProvider:
    def __init__(self, client: DirectGlobalMarketClient | None = None) -> None:
        self.client = client or DirectGlobalMarketClient()

    def session(
        self,
        profile: MultiAssetInstrumentProfile,
        *,
        session_model: TradingSessionModel,
        as_of: datetime,
    ) -> InstrumentSession:
        instrument = self.client._instrument(profile.symbol)
        if profile.asset_class not in DIRECT_EXECUTION_CLASSES:
            raise DirectGlobalMarketError(
                f"{profile.symbol} is not a direct FX, crypto, or futures instrument"
            )
        status = (
            InstrumentSessionStatus.OPEN
            if self.client.session_is_open(instrument, as_of=as_of)
            else InstrumentSessionStatus.CLOSED
        )
        return InstrumentSession(
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            session_model=session_model,
            as_of=_aware(as_of, field_name="as_of"),
            status=status,
            source_identifier=f"direct-market-session:{self.client.universe.identifier}",
        )


class DirectPaperQuoteProvider:
    def __init__(self, client: DirectGlobalMarketClient | None = None) -> None:
        self.client = client or DirectGlobalMarketClient()

    def quotes(
        self,
        profiles: tuple[MultiAssetInstrumentProfile, ...],
        *,
        as_of: datetime,
    ) -> Mapping[str, MultiAssetQuote]:
        timestamp = _aware(as_of, field_name="as_of")
        raw = self.client.latest_quotes(tuple(item.symbol for item in profiles))
        result: dict[str, MultiAssetQuote] = {}
        for profile in profiles:
            if profile.asset_class not in DIRECT_EXECUTION_CLASSES:
                raise DirectGlobalMarketError(
                    f"{profile.symbol} is outside direct-market paper execution"
                )
            item = raw[profile.symbol]
            observed = min(
                _timestamp(item["t"], field_name=f"{profile.symbol} observed_at"),
                timestamp,
            )
            bid = _positive(item["bp"], field_name=f"{profile.symbol} bid")
            ask = _positive(item["ap"], field_name=f"{profile.symbol} ask")
            result[profile.symbol] = MultiAssetQuote(
                symbol=profile.symbol,
                instrument_identifier=profile.instrument_identifier,
                venue=profile.venue,
                observed_at=observed,
                bid=bid,
                ask=ask,
                last=_positive(item.get("last", (bid + ask) / 2.0), field_name="last"),
                available_base_notional=5_000_000.0,
                price_currency=profile.price_currency,
                fx_rate_to_base=1.0,
                fx_observed_at=observed,
                quote_source_identifier=(
                    f"{self.client.universe.provider_identifier}:latest-chart"
                ),
                fx_source_identifier="usd-base-rate:1.0",
                quote_certification_identifier=(
                    f"direct-paper-quote:{profile.instrument_identifier}:{observed.isoformat()}"
                ),
                halted=False,
            )
        return result


class CombinedPaperSessionProvider:
    def __init__(self) -> None:
        self.alpaca = AlpacaPaperSessionProvider(create_alpaca_paper_client())
        self.direct = DirectPaperSessionProvider()

    def session(
        self,
        profile: MultiAssetInstrumentProfile,
        *,
        session_model: TradingSessionModel,
        as_of: datetime,
    ) -> InstrumentSession:
        if profile.asset_class in SUPPORTED_PILOT_CLASSES:
            return self.alpaca.session(
                profile, session_model=session_model, as_of=as_of
            )
        return self.direct.session(
            profile, session_model=session_model, as_of=as_of
        )


class CombinedPaperQuoteProvider:
    def __init__(self) -> None:
        self.alpaca = AlpacaPaperQuoteProvider(create_alpaca_paper_client())
        self.direct = DirectPaperQuoteProvider()

    def quotes(
        self,
        profiles: tuple[MultiAssetInstrumentProfile, ...],
        *,
        as_of: datetime,
    ) -> Mapping[str, MultiAssetQuote]:
        listed = tuple(
            item for item in profiles if item.asset_class in SUPPORTED_PILOT_CLASSES
        )
        direct = tuple(
            item for item in profiles if item.asset_class in DIRECT_EXECUTION_CLASSES
        )
        unsupported = tuple(
            item.symbol for item in profiles
            if item.asset_class not in SUPPORTED_PILOT_CLASSES
            and item.asset_class not in DIRECT_EXECUTION_CLASSES
        )
        if unsupported:
            raise DirectGlobalMarketError(
                f"paper quote routing is unavailable for {unsupported}"
            )
        result: dict[str, MultiAssetQuote] = {}
        if listed:
            result.update(self.alpaca.quotes(listed, as_of=as_of))
        if direct:
            result.update(self.direct.quotes(direct, as_of=as_of))
        return result


def create_combined_paper_session_provider() -> CombinedPaperSessionProvider:
    return CombinedPaperSessionProvider()


def create_combined_paper_quote_provider() -> CombinedPaperQuoteProvider:
    return CombinedPaperQuoteProvider()


__all__ = [
    "CombinedPaperQuoteProvider",
    "CombinedPaperSessionProvider",
    "DEFAULT_DIRECT_UNIVERSE_PATH",
    "DIRECT_EXECUTION_CLASSES",
    "DirectGlobalMarketClient",
    "DirectGlobalMarketError",
    "DirectGlobalMarketUniverse",
    "DirectPaperQuoteProvider",
    "DirectPaperSessionProvider",
    "create_combined_paper_quote_provider",
    "create_combined_paper_session_provider",
    "load_direct_global_market_universe",
]
