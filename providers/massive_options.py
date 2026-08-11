"""Point-in-time U.S. option reference and daily-bar fallback from Massive.

This adapter is intentionally provider-only. It cannot nominate capital, change CIO
thresholds, or weaken evidence requirements. It exposes the same completed-session
contract-definition and daily-price facts needed by the existing long-premium option
research lane. Missing, malformed, rate-limited, or unavailable evidence raises and
remains fail-closed upstream.
"""

from __future__ import annotations

import math
import os
import threading
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

import requests

MASSIVE_OPTIONS_BASE_URL = "https://api.massive.com"
MASSIVE_OPRA_DATASET = "OPRA"
_DEFAULT_TIMEOUT_SECONDS = 15
_DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS = 12.1
_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_BAR_CACHE: dict[tuple[str, str], tuple["MassiveOptionBar", ...]] = {}
_BAR_CACHE_LOCK = threading.Lock()
_MAX_CACHE_ENTRIES = 4096


class MassiveOptionsError(RuntimeError):
    """Raised when Massive option evidence cannot be certified."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = bool(retryable)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MassiveOptionsError(f"{field_name} cannot be empty")
    return value.strip()


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise MassiveOptionsError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise MassiveOptionsError(f"{field_name} must be numeric") from error
    if not math.isfinite(result):
        raise MassiveOptionsError(f"{field_name} must be finite")
    return result


def _compact_occ_symbol(raw_symbol: str) -> str:
    compact = "".join(_text(raw_symbol, field_name="option ticker").upper().split())
    if compact.startswith("O:"):
        compact = compact[2:]
    if len(compact) < 16:
        raise MassiveOptionsError("Massive option ticker is not a valid OCC symbol")
    return compact


def _expiration_timestamp(value: object) -> datetime:
    raw = _text(value, field_name="expiration_date")
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError as error:
        raise MassiveOptionsError("expiration_date is invalid") from error
    return datetime.combine(parsed, time(21, 0), tzinfo=timezone.utc)


def _observed_timestamp(value: object) -> datetime:
    if isinstance(value, bool):
        raise MassiveOptionsError("aggregate timestamp is invalid")
    try:
        milliseconds = float(value)
    except (TypeError, ValueError) as error:
        raise MassiveOptionsError("aggregate timestamp is invalid") from error
    if not math.isfinite(milliseconds) or milliseconds <= 0.0:
        raise MassiveOptionsError("aggregate timestamp is invalid")
    return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)


def _cache_key(raw_symbol: str, as_of: datetime) -> tuple[str, str]:
    return raw_symbol.strip().upper(), as_of.date().isoformat()


def _cache_put(raw_symbol: str, as_of: datetime, bars: tuple["MassiveOptionBar", ...]) -> None:
    if not bars:
        return
    key = _cache_key(raw_symbol, as_of)
    with _BAR_CACHE_LOCK:
        if len(_BAR_CACHE) >= _MAX_CACHE_ENTRIES and key not in _BAR_CACHE:
            oldest = next(iter(_BAR_CACHE), None)
            if oldest is not None:
                _BAR_CACHE.pop(oldest, None)
        _BAR_CACHE[key] = bars


def _cache_get(raw_symbol: str, as_of: datetime) -> tuple["MassiveOptionBar", ...]:
    with _BAR_CACHE_LOCK:
        return _BAR_CACHE.get(_cache_key(raw_symbol, as_of), ())


@dataclass(frozen=True, slots=True)
class MassiveOptionDefinition:
    symbol: str
    raw_symbol: str
    underlying: str
    option_right: str
    expiration_at: datetime
    strike: float
    contract_multiplier: float
    session_date: date
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _compact_occ_symbol(self.symbol))
        object.__setattr__(
            self, "raw_symbol", _text(self.raw_symbol, field_name="raw_symbol").upper()
        )
        object.__setattr__(
            self, "underlying", _text(self.underlying, field_name="underlying").upper()
        )
        if self.option_right not in {"call", "put"}:
            raise ValueError("option_right must be call or put")
        object.__setattr__(
            self, "expiration_at", _aware(self.expiration_at, field_name="expiration_at")
        )
        strike = _number(self.strike, field_name="strike")
        multiplier = _number(self.contract_multiplier, field_name="contract_multiplier")
        if strike <= 0.0 or multiplier <= 0.0:
            raise ValueError("strike and contract_multiplier must be positive")
        object.__setattr__(self, "strike", strike)
        object.__setattr__(self, "contract_multiplier", multiplier)
        object.__setattr__(
            self,
            "source_identifier",
            _text(self.source_identifier, field_name="source_identifier"),
        )


@dataclass(frozen=True, slots=True)
class MassiveOptionBar:
    raw_symbol: str
    observed_at: datetime
    close: float
    volume: float
    source_identifier: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "raw_symbol", _text(self.raw_symbol, field_name="raw_symbol").upper()
        )
        object.__setattr__(
            self, "observed_at", _aware(self.observed_at, field_name="observed_at")
        )
        close = _number(self.close, field_name="close")
        volume = _number(self.volume, field_name="volume")
        if close <= 0.0 or volume < 0.0:
            raise ValueError("close must be positive and volume cannot be negative")
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(
            self,
            "source_identifier",
            _text(self.source_identifier, field_name="source_identifier"),
        )


@dataclass(frozen=True, slots=True)
class MassiveOptionSelection:
    definition: MassiveOptionDefinition
    bar: MassiveOptionBar


HttpGet = Callable[..., Any]


class MassiveOptionsProvider:
    """Bounded Massive REST access used only as an OPRA fallback provider."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: HttpGet = requests.get,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        minimum_request_interval_seconds: float | None = None,
    ) -> None:
        resolved = (
            (
                os.getenv("CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY")
                or os.getenv("MASSIVE_API_KEY")
                or os.getenv("POLYGON_API_KEY")
                or ""
            ).strip()
            if api_key is None
            else str(api_key).strip()
        )
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise TypeError("timeout_seconds must be an integer")
        if timeout_seconds < 1 or timeout_seconds > 180:
            raise ValueError("timeout_seconds must be between 1 and 180")
        if minimum_request_interval_seconds is None:
            raw_interval = os.getenv(
                "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_REQUEST_INTERVAL_SECONDS",
                str(_DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS),
            )
            try:
                interval = float(raw_interval)
            except ValueError as error:
                raise ValueError(
                    "Massive request interval must be numeric"
                ) from error
        else:
            interval = float(minimum_request_interval_seconds)
        if not math.isfinite(interval) or interval < 0.0 or interval > 60.0:
            raise ValueError("Massive request interval must be between 0 and 60 seconds")
        self._api_key = resolved
        self._http_get = http_get
        self._timeout_seconds = timeout_seconds
        self._minimum_request_interval_seconds = interval

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _throttled_get(self, url: str, *, params: Mapping[str, object]) -> Any:
        global _LAST_REQUEST_AT
        if not self.configured:
            raise MassiveOptionsError("Massive options API key is not configured")
        with _REQUEST_LOCK:
            now = time_module.monotonic()
            delay = self._minimum_request_interval_seconds - (now - _LAST_REQUEST_AT)
            if delay > 0.0:
                time_module.sleep(delay)
            try:
                response = self._http_get(
                    url,
                    params={**params, "apiKey": self._api_key},
                    timeout=self._timeout_seconds,
                )
            except requests.RequestException as error:
                raise MassiveOptionsError(
                    f"Massive OPRA request failed: {type(error).__name__}",
                    retryable=True,
                ) from error
            finally:
                _LAST_REQUEST_AT = time_module.monotonic()
        return response

    def _json(self, url: str, *, params: Mapping[str, object]) -> Mapping[str, Any]:
        response = self._throttled_get(url, params=params)
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            retryable = status in {408, 425, 429} or 500 <= status <= 599
            raise MassiveOptionsError(
                f"Massive OPRA HTTP {status}",
                status_code=status,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise MassiveOptionsError("Massive OPRA response is not valid JSON") from error
        if not isinstance(payload, Mapping):
            raise MassiveOptionsError("Massive OPRA response must be an object")
        return payload

    def definitions(
        self,
        underlying: str,
        *,
        as_of: datetime,
        minimum_days_to_expiry: int = 1,
        maximum_days_to_expiry: int = 400,
        maximum_records: int = 1_000,
    ) -> tuple[MassiveOptionDefinition, ...]:
        normalized = _text(underlying, field_name="underlying").upper()
        timestamp = _aware(as_of, field_name="as_of")
        if maximum_records < 1 or maximum_records > 5_000:
            raise ValueError("maximum_records must be between 1 and 5000")
        start_date = (timestamp + timedelta(days=minimum_days_to_expiry)).date()
        end_date = (timestamp + timedelta(days=maximum_days_to_expiry)).date()
        url = f"{MASSIVE_OPTIONS_BASE_URL}/v3/reference/options/contracts"
        params: dict[str, object] = {
            "underlying_ticker": normalized,
            "as_of": timestamp.date().isoformat(),
            "expiration_date.gte": start_date.isoformat(),
            "expiration_date.lte": end_date.isoformat(),
            "expired": "false",
            "order": "asc",
            "sort": "expiration_date",
            "limit": min(1_000, maximum_records),
        }
        payload = self._json(url, params=params)
        rows = payload.get("results", ())
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise MassiveOptionsError("Massive option contract results are unavailable")
        definitions: list[MassiveOptionDefinition] = []
        for row in rows[:maximum_records]:
            if not isinstance(row, Mapping):
                continue
            try:
                ticker = _text(row.get("ticker"), field_name="ticker").upper()
                row_underlying = _text(
                    row.get("underlying_ticker"), field_name="underlying_ticker"
                ).upper()
                if row_underlying != normalized:
                    continue
                right = _text(row.get("contract_type"), field_name="contract_type").lower()
                if right not in {"call", "put"}:
                    continue
                expiration = _expiration_timestamp(row.get("expiration_date"))
                definitions.append(
                    MassiveOptionDefinition(
                        symbol=_compact_occ_symbol(ticker),
                        raw_symbol=ticker,
                        underlying=row_underlying,
                        option_right=right,
                        expiration_at=expiration,
                        strike=_number(row.get("strike_price"), field_name="strike_price"),
                        contract_multiplier=_number(
                            row.get("shares_per_contract", 100.0),
                            field_name="shares_per_contract",
                        ),
                        session_date=timestamp.date(),
                        source_identifier=(
                            "massive-opra-definition:"
                            f"{timestamp.date().isoformat()}:{ticker}"
                        ),
                    )
                )
            except (MassiveOptionsError, TypeError, ValueError):
                continue
        if not definitions:
            raise MassiveOptionsError(
                f"Massive OPRA definitions unavailable for {normalized}"
            )
        definitions.sort(
            key=lambda item: (
                item.expiration_at,
                item.option_right,
                item.strike,
                item.symbol,
            )
        )
        return tuple(definitions)

    def daily_bars(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> Mapping[str, tuple[MassiveOptionBar, ...]]:
        timestamp = _aware(as_of, field_name="as_of")
        if history_days < 1 or history_days > 730:
            raise ValueError("history_days must be between 1 and 730")
        start_date = (timestamp - timedelta(days=history_days)).date().isoformat()
        end_date = timestamp.date().isoformat()
        result: dict[str, tuple[MassiveOptionBar, ...]] = {}
        for raw_symbol in dict.fromkeys(str(item).strip().upper() for item in raw_symbols):
            if not raw_symbol:
                continue
            cached = _cache_get(raw_symbol, timestamp)
            if cached:
                result[raw_symbol] = cached
                continue
            url = (
                f"{MASSIVE_OPTIONS_BASE_URL}/v2/aggs/ticker/"
                f"{quote(raw_symbol, safe='')}/range/1/day/{start_date}/{end_date}"
            )
            payload = self._json(
                url,
                params={"adjusted": "false", "sort": "asc", "limit": 50_000},
            )
            rows = payload.get("results", ())
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                continue
            bars: list[MassiveOptionBar] = []
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                try:
                    observed = _observed_timestamp(row.get("t"))
                    if observed > timestamp:
                        continue
                    bars.append(
                        MassiveOptionBar(
                            raw_symbol=raw_symbol,
                            observed_at=observed,
                            close=_number(row.get("c"), field_name="close"),
                            volume=max(0.0, _number(row.get("v", 0.0), field_name="volume")),
                            source_identifier=(
                                "massive-opra-bar:"
                                f"{raw_symbol}:{observed.isoformat()}"
                            ),
                        )
                    )
                except (MassiveOptionsError, TypeError, ValueError):
                    continue
            if bars:
                ordered = tuple(sorted(bars, key=lambda item: item.observed_at))
                _cache_put(raw_symbol, timestamp, ordered)
                result[raw_symbol] = ordered
        return result

    def latest_daily_bars(
        self,
        instruments: Sequence[object],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> tuple[date, Mapping[str, tuple[MassiveOptionBar, ...]]]:
        timestamp = _aware(as_of, field_name="as_of")
        raw_symbols: list[str] = []
        for item in instruments:
            if isinstance(item, MassiveOptionDefinition):
                raw_symbols.append(item.raw_symbol)
            elif isinstance(item, tuple) and len(item) >= 2:
                raw_symbols.append(str(item[-1]))
            else:
                raw_symbols.append(str(item))
        bars = self.daily_bars(raw_symbols, as_of=timestamp, history_days=history_days)
        if not bars:
            raise MassiveOptionsError("Massive OPRA daily bars are unavailable")
        session_date = max(
            values[-1].observed_at.date() for values in bars.values() if values
        )
        return session_date, bars

    def select_contracts(
        self,
        underlying: str,
        *,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        maximum_expirations: int = 2,
        candidates_per_bucket: int = 1,
    ) -> tuple[MassiveOptionSelection, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        definitions = tuple(
            item
            for item in self.definitions(
                underlying,
                as_of=timestamp,
                minimum_days_to_expiry=minimum_days_to_expiry,
                maximum_days_to_expiry=maximum_days_to_expiry,
            )
            if minimum_days_to_expiry
            <= (item.expiration_at - timestamp).days
            <= maximum_days_to_expiry
            and abs(item.strike / price - 1.0) <= 0.20
        )
        expirations = tuple(
            sorted({item.expiration_at for item in definitions})[:maximum_expirations]
        )
        buckets: dict[tuple[datetime, str], tuple[MassiveOptionDefinition, ...]] = {}
        candidates: list[MassiveOptionDefinition] = []
        for expiration in expirations:
            for right in ("call", "put"):
                ranked = sorted(
                    (
                        item
                        for item in definitions
                        if item.expiration_at == expiration and item.option_right == right
                    ),
                    key=lambda item: (abs(item.strike / price - 1.0), item.strike, item.symbol),
                )[:candidates_per_bucket]
                bucket = tuple(ranked)
                buckets[(expiration, right)] = bucket
                candidates.extend(bucket)
        if not candidates:
            return ()
        _session, bars = self.latest_daily_bars(
            candidates,
            as_of=timestamp,
            history_days=10,
        )
        selected: list[MassiveOptionSelection] = []
        for key in sorted(buckets, key=lambda item: (item[0], item[1])):
            choices: list[tuple[float, MassiveOptionDefinition, MassiveOptionBar]] = []
            for definition in buckets[key]:
                history = bars.get(definition.raw_symbol, ())
                if not history:
                    continue
                latest = history[-1]
                moneyness = abs(definition.strike / price - 1.0)
                score = math.log10(max(1.0, latest.volume)) - 5.0 * moneyness
                choices.append((score, definition, latest))
            if choices:
                choices.sort(key=lambda item: (item[0], item[1].symbol), reverse=True)
                _score, definition, latest = choices[0]
                selected.append(MassiveOptionSelection(definition=definition, bar=latest))
        return tuple(selected)


__all__ = [
    "MASSIVE_OPRA_DATASET",
    "MASSIVE_OPTIONS_BASE_URL",
    "MassiveOptionBar",
    "MassiveOptionDefinition",
    "MassiveOptionSelection",
    "MassiveOptionsError",
    "MassiveOptionsProvider",
]
