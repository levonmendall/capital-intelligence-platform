"""Opportunity-complete Alpaca Basic option evidence.

The provider uses Alpaca market-data endpoints only. Contract opportunity discovery is
performed through the paginated option-chain endpoint with the free ``indicative``
feed, so paper-brokerage options approval is never required merely to enumerate the
candidate universe. Historical daily bars are requested only through a point in time
that is safely outside Alpaca Basic's latest-15-minute restriction.

This module grants no order authority. It does not reduce expiration coverage, lower
qualification thresholds, fabricate evidence, or substitute indicative snapshots for
historical bars. The option chain supplies contract identity; completed historical bars
supply the evidence used by screening and downstream CIO analysis.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

import requests

from providers.alpaca_paper import AlpacaPaperSettings


ALPACA_INDICATIVE_OPTIONS_DATASET = "ALPACA.OPTIONS.INDICATIVE"
ALPACA_INDICATIVE_OPTIONS_FEED = "indicative"
_MAX_CHAIN_PAGES = 500
_MAX_BAR_PAGES = 500
_CHAIN_PAGE_LIMIT = 1_000
_BAR_PAGE_LIMIT = 10_000
_BAR_SYMBOL_BATCH = 100
_DEFAULT_SELECTION_HISTORY_DAYS = 365
_DEFAULT_MONEYNESS_LIMIT = 0.20
_BASIC_HISTORY_DELAY_MINUTES = 16


class AlpacaIndicativeOptionsError(RuntimeError):
    """Raised when authenticated Alpaca option evidence is unavailable or invalid."""

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


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _timestamp(value: object, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return _aware(value, field_name=field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return _aware(parsed, field_name=field_name)


def _alpaca_symbol(raw_symbol: str) -> str:
    compact = "".join(str(raw_symbol).strip().upper().split())
    return compact[2:] if compact.startswith("O:") else compact


def _occ_identity(symbol: str) -> tuple[date, str, float]:
    """Parse OCC compact option identity from the final 15 characters."""

    compact = _alpaca_symbol(symbol)
    if len(compact) < 16:
        raise ValueError("option symbol is too short for OCC compact format")
    suffix = compact[-15:]
    expiration = datetime.strptime(suffix[:6], "%y%m%d").date()
    right_code = suffix[6]
    if right_code == "C":
        right = "call"
    elif right_code == "P":
        right = "put"
    else:
        raise ValueError("option symbol has an invalid OCC right code")
    strike_text = suffix[7:]
    if len(strike_text) != 8 or not strike_text.isdigit():
        raise ValueError("option symbol has an invalid OCC strike")
    return expiration, right, int(strike_text) / 1000.0


@dataclass(frozen=True, slots=True)
class AlpacaIndicativeOptionDefinition:
    symbol: str
    raw_symbol: str
    underlying: str
    option_right: str
    expiration_at: datetime
    strike: float
    contract_multiplier: float
    session_date: date
    source_identifier: str


@dataclass(frozen=True, slots=True)
class AlpacaIndicativeOptionBar:
    raw_symbol: str
    observed_at: datetime
    close: float
    volume: float
    source_identifier: str


@dataclass(frozen=True, slots=True)
class AlpacaIndicativeOptionSelection:
    definition: AlpacaIndicativeOptionDefinition
    bar: AlpacaIndicativeOptionBar


# Process-wide because catalog construction and provider preselection instantiate
# independent routers in the same diagnostic process. Coverage is stored with each
# entry so a short request can never satisfy a later deeper-history request.
_BAR_CACHE_LOCK = threading.Lock()
_BAR_CACHE: dict[
    tuple[str, date],
    tuple[int, tuple[AlpacaIndicativeOptionBar, ...]],
] = {}


class AlpacaIndicativeOptionsProvider:
    """Authenticated market-data adapter with complete eligible-expiration coverage."""

    def __init__(
        self,
        settings: AlpacaPaperSettings | None = None,
        *,
        http_get: Callable[..., Any] = requests.get,
        moneyness_limit: float = _DEFAULT_MONEYNESS_LIMIT,
    ) -> None:
        if not math.isfinite(float(moneyness_limit)) or not 0.0 < float(moneyness_limit) <= 1.0:
            raise ValueError("moneyness_limit must be in (0, 1]")
        if settings is not None:
            candidates = (settings,)
        else:
            try:
                candidates = tuple(
                    candidate
                    for _label, candidate in AlpacaPaperSettings.candidates_from_env()
                )
            except ValueError:
                candidates = ()
        self._settings_candidates = candidates
        self._active_settings: AlpacaPaperSettings | None = None
        self._http_get = http_get
        self._moneyness_limit = float(moneyness_limit)
        self._settings_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._settings_candidates)

    def _settings_order(self) -> tuple[AlpacaPaperSettings, ...]:
        active = self._active_settings
        if active is None:
            return self._settings_candidates
        return (active, *tuple(item for item in self._settings_candidates if item != active))

    def _get(self, *, path: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        if not self.configured:
            raise AlpacaIndicativeOptionsError("Alpaca market-data credentials are not configured")
        last_status: int | None = None
        last_error: str | None = None
        for settings in self._settings_order():
            try:
                response = self._http_get(
                    settings.data_base_url.rstrip("/") + path,
                    headers={
                        "APCA-API-KEY-ID": settings.api_key_id,
                        "APCA-API-SECRET-KEY": settings.secret_key,
                        "Accept": "application/json",
                    },
                    params=dict(params),
                    timeout=settings.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = type(error).__name__
                continue
            status = int(getattr(response, "status_code", 0))
            last_status = status
            if status in {401, 403}:
                last_error = f"HTTP {status}"
                continue
            if status < 200 or status >= 300:
                retryable = status in {408, 425, 429} or 500 <= status <= 599
                raise AlpacaIndicativeOptionsError(
                    f"Alpaca option market-data endpoint {path} returned HTTP {status}",
                    status_code=status,
                    retryable=retryable,
                )
            try:
                payload = response.json()
            except (TypeError, ValueError) as error:
                raise AlpacaIndicativeOptionsError(
                    f"Alpaca option market-data endpoint {path} returned invalid JSON"
                ) from error
            if not isinstance(payload, Mapping):
                raise AlpacaIndicativeOptionsError(
                    f"Alpaca option market-data endpoint {path} must return a JSON object"
                )
            with self._settings_lock:
                self._active_settings = settings
            return payload
        raise AlpacaIndicativeOptionsError(
            f"Alpaca option market-data access unavailable for {path}"
            + (f": {last_error}" if last_error else ""),
            status_code=last_status,
        )

    def definitions(
        self,
        underlying: str,
        *,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
    ) -> tuple[AlpacaIndicativeOptionDefinition, ...]:
        normalized = _text(underlying, field_name="underlying").upper()
        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        if minimum_days_to_expiry < 1 or maximum_days_to_expiry <= minimum_days_to_expiry:
            raise ValueError("option expiry bounds are invalid")
        lower_strike = price * (1.0 - self._moneyness_limit)
        upper_strike = price * (1.0 + self._moneyness_limit)
        expiration_gte = (timestamp + timedelta(days=minimum_days_to_expiry)).date()
        expiration_lte = (timestamp + timedelta(days=maximum_days_to_expiry + 1)).date()
        definitions: dict[str, AlpacaIndicativeOptionDefinition] = {}
        page_token: str | None = None
        path = f"/v1beta1/options/snapshots/{quote(normalized, safe='')}"
        for _page in range(_MAX_CHAIN_PAGES):
            params: dict[str, object] = {
                "feed": ALPACA_INDICATIVE_OPTIONS_FEED,
                "expiration_date_gte": expiration_gte.isoformat(),
                "expiration_date_lte": expiration_lte.isoformat(),
                "strike_price_gte": f"{lower_strike:.8f}",
                "strike_price_lte": f"{upper_strike:.8f}",
                "limit": _CHAIN_PAGE_LIMIT,
            }
            if page_token is not None:
                params["page_token"] = page_token
            payload = self._get(path=path, params=params)
            raw_snapshots = payload.get("snapshots")
            if not isinstance(raw_snapshots, Mapping):
                raise AlpacaIndicativeOptionsError(
                    "Alpaca option-chain response is missing snapshots"
                )
            for raw_symbol in raw_snapshots:
                try:
                    symbol = _alpaca_symbol(str(raw_symbol))
                    expiration_date, right, strike = _occ_identity(symbol)
                    expiration_at = datetime.combine(
                        expiration_date,
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ) + timedelta(hours=21)
                    days = (expiration_at - timestamp).days
                    if not (
                        minimum_days_to_expiry <= days <= maximum_days_to_expiry
                        and strike > 0.0
                        and abs(strike / price - 1.0) <= self._moneyness_limit
                    ):
                        continue
                    definitions[symbol] = AlpacaIndicativeOptionDefinition(
                        symbol=symbol,
                        raw_symbol=symbol,
                        underlying=normalized,
                        option_right=right,
                        expiration_at=expiration_at,
                        strike=strike,
                        contract_multiplier=100.0,
                        session_date=timestamp.date(),
                        source_identifier=(
                            "alpaca-indicative-option-chain:"
                            f"{timestamp.date().isoformat()}:{normalized}:{symbol}"
                        ),
                    )
                except (TypeError, ValueError):
                    continue
            raw_token = payload.get("next_page_token")
            if raw_token is None or not str(raw_token).strip():
                break
            page_token = str(raw_token).strip()
        else:
            raise AlpacaIndicativeOptionsError(
                "Alpaca option-chain pagination exceeded the completeness guard"
            )
        return tuple(
            sorted(
                definitions.values(),
                key=lambda item: (
                    item.expiration_at,
                    item.option_right,
                    item.strike,
                    item.symbol,
                ),
            )
        )

    def _cached_bars(
        self,
        symbol: str,
        *,
        as_of: datetime,
        history_days: int,
    ) -> tuple[AlpacaIndicativeOptionBar, ...] | None:
        with _BAR_CACHE_LOCK:
            cached = _BAR_CACHE.get((symbol, as_of.date()))
        if cached is None:
            return None
        covered_days, bars = cached
        return bars if covered_days >= history_days else None

    def daily_bars(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> Mapping[str, tuple[AlpacaIndicativeOptionBar, ...]]:
        timestamp = _aware(as_of, field_name="as_of")
        if history_days < 1 or history_days > 730:
            raise ValueError("history_days must be between 1 and 730")
        normalized = tuple(
            dict.fromkeys(
                _alpaca_symbol(item)
                for item in raw_symbols
                if str(item).strip()
            )
        )
        if not normalized:
            return {}
        result: dict[str, tuple[AlpacaIndicativeOptionBar, ...]] = {}
        missing: list[str] = []
        for symbol in normalized:
            cached = self._cached_bars(
                symbol,
                as_of=timestamp,
                history_days=history_days,
            )
            if cached is None:
                missing.append(symbol)
            elif cached:
                result[symbol] = cached

        # Alpaca Basic blocks requests that include the latest 15 minutes of options
        # history. Keep the query point-in-time and safely behind that boundary.
        safe_end = timestamp - timedelta(minutes=_BASIC_HISTORY_DELAY_MINUTES)
        start = timestamp - timedelta(days=history_days)
        for offset in range(0, len(missing), _BAR_SYMBOL_BATCH):
            batch = tuple(missing[offset : offset + _BAR_SYMBOL_BATCH])
            grouped: dict[str, list[AlpacaIndicativeOptionBar]] = {
                symbol: [] for symbol in batch
            }
            page_token: str | None = None
            for _page in range(_MAX_BAR_PAGES):
                params: dict[str, object] = {
                    "symbols": ",".join(batch),
                    "timeframe": "1Day",
                    "start": start.isoformat(),
                    "end": safe_end.isoformat(),
                    "limit": _BAR_PAGE_LIMIT,
                    "sort": "asc",
                }
                if page_token is not None:
                    params["page_token"] = page_token
                payload = self._get(path="/v1beta1/options/bars", params=params)
                raw_bars = payload.get("bars")
                if not isinstance(raw_bars, Mapping):
                    raise AlpacaIndicativeOptionsError(
                        "Alpaca option-history response is missing bars"
                    )
                for raw_symbol, values in raw_bars.items():
                    symbol = _alpaca_symbol(str(raw_symbol))
                    if symbol not in grouped:
                        continue
                    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                        continue
                    for raw in values:
                        if not isinstance(raw, Mapping):
                            continue
                        try:
                            observed = _timestamp(raw.get("t"), field_name="bar timestamp")
                            close = _number(raw.get("c"), field_name="bar close")
                            volume = max(0.0, _number(raw.get("v", 0.0), field_name="bar volume"))
                        except (TypeError, ValueError):
                            continue
                        if observed > safe_end or close <= 0.0:
                            continue
                        grouped[symbol].append(
                            AlpacaIndicativeOptionBar(
                                raw_symbol=symbol,
                                observed_at=observed,
                                close=close,
                                volume=volume,
                                source_identifier=(
                                    "alpaca-basic-option-bar:"
                                    f"{symbol}:{observed.isoformat()}"
                                ),
                            )
                        )
                raw_token = payload.get("next_page_token")
                if raw_token is None or not str(raw_token).strip():
                    break
                page_token = str(raw_token).strip()
            else:
                raise AlpacaIndicativeOptionsError(
                    "Alpaca option-history pagination exceeded the completeness guard"
                )
            for symbol, values in grouped.items():
                bars = tuple(sorted(values, key=lambda item: item.observed_at))
                with _BAR_CACHE_LOCK:
                    _BAR_CACHE[(symbol, timestamp.date())] = (history_days, bars)
                if bars:
                    result[symbol] = bars
        return result

    def latest_daily_bars(
        self,
        instruments: Sequence[tuple[int | None, str]],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> tuple[date, Mapping[str, tuple[AlpacaIndicativeOptionBar, ...]]]:
        timestamp = _aware(as_of, field_name="as_of")
        symbols = tuple(
            dict.fromkeys(
                _alpaca_symbol(raw_symbol)
                for _instrument_id, raw_symbol in instruments
                if str(raw_symbol).strip()
            )
        )
        bars = self.daily_bars(symbols, as_of=timestamp, history_days=history_days)
        session_date = max(
            (history[-1].observed_at.date() for history in bars.values() if history),
            default=timestamp.date(),
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
        maximum_expirations: int = 1_000,
        candidates_per_bucket: int = 8,
    ) -> tuple[AlpacaIndicativeOptionSelection, ...]:
        """Select one evidence-bearing contract per right for every eligible expiration."""

        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        if maximum_expirations < 1:
            raise ValueError("maximum_expirations must be positive")
        if candidates_per_bucket < 1:
            raise ValueError("candidates_per_bucket must be positive")
        definitions = self.definitions(
            underlying,
            underlying_price=price,
            as_of=timestamp,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
        )
        all_expirations = tuple(sorted({item.expiration_at for item in definitions}))
        expirations = all_expirations[:maximum_expirations]
        buckets: dict[
            tuple[datetime, str],
            tuple[AlpacaIndicativeOptionDefinition, ...],
        ] = {}
        candidates: list[AlpacaIndicativeOptionDefinition] = []
        for expiration in expirations:
            for right in ("call", "put"):
                ranked = sorted(
                    (
                        item
                        for item in definitions
                        if item.expiration_at == expiration and item.option_right == right
                    ),
                    key=lambda item: (
                        abs(item.strike / price - 1.0),
                        item.strike,
                        item.symbol,
                    ),
                )[:candidates_per_bucket]
                bucket = tuple(ranked)
                buckets[(expiration, right)] = bucket
                candidates.extend(bucket)
        if not candidates:
            return ()

        short_bars = self.daily_bars(
            tuple(item.raw_symbol for item in candidates),
            as_of=timestamp,
            history_days=10,
        )
        provisional: list[AlpacaIndicativeOptionSelection] = []
        for key in sorted(buckets, key=lambda item: (item[0], item[1])):
            choices: list[
                tuple[
                    float,
                    AlpacaIndicativeOptionDefinition,
                    AlpacaIndicativeOptionBar,
                ]
            ] = []
            for definition in buckets[key]:
                history = short_bars.get(definition.raw_symbol, ())
                if not history:
                    continue
                latest = history[-1]
                moneyness = abs(definition.strike / price - 1.0)
                score = math.log10(max(1.0, latest.volume)) - 5.0 * moneyness
                choices.append((score, definition, latest))
            if choices:
                choices.sort(key=lambda item: (item[0], item[1].symbol), reverse=True)
                _score, definition, latest = choices[0]
                provisional.append(
                    AlpacaIndicativeOptionSelection(definition=definition, bar=latest)
                )
        if not provisional:
            return ()

        deep_bars = self.daily_bars(
            tuple(item.definition.raw_symbol for item in provisional),
            as_of=timestamp,
            history_days=_DEFAULT_SELECTION_HISTORY_DAYS,
        )
        selected: list[AlpacaIndicativeOptionSelection] = []
        for item in provisional:
            history = deep_bars.get(item.definition.raw_symbol, ())
            if not history:
                continue
            selected.append(
                AlpacaIndicativeOptionSelection(
                    definition=item.definition,
                    bar=history[-1],
                )
            )
        return tuple(selected)


__all__ = [
    "ALPACA_INDICATIVE_OPTIONS_DATASET",
    "ALPACA_INDICATIVE_OPTIONS_FEED",
    "AlpacaIndicativeOptionBar",
    "AlpacaIndicativeOptionDefinition",
    "AlpacaIndicativeOptionSelection",
    "AlpacaIndicativeOptionsError",
    "AlpacaIndicativeOptionsProvider",
]
