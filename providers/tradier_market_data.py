"""Tradier market-data evidence for U.S. equities/ETFs and active options.

Tradier is an independent secondary source. Its expiration directory, complete active
chains (including Greeks/IV), and OCC-symbol daily history may establish option contract
selection only when every requested expiration/right bucket has completed-session price
evidence. The adapter never grants ranking, CIO, construction, execution, or real-money
authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

import requests

from provider_environment import provider_environment_value


TRADIER_BASE_URL = "https://api.tradier.com/v1"
TRADIER_OPTIONS_DATASET = (
    "markets/options/expirations+markets/options/chains+markets/history"
)
_DEFAULT_MONEYNESS_LIMIT = 0.35
_DEFAULT_SELECTION_HISTORY_DAYS = 365


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
    volume: float
    contract_size: float
    implied_volatility: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    observed_at: datetime
    source_identifier: str


@dataclass(frozen=True, slots=True)
class TradierOptionDefinition:
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
class TradierOptionBar:
    raw_symbol: str
    observed_at: datetime
    close: float
    volume: float
    source_identifier: str


@dataclass(frozen=True, slots=True)
class TradierOptionSelection:
    definition: TradierOptionDefinition
    bar: TradierOptionBar


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
        if raw is None:
            return ()
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
            # A provider daily row stamped with the current calendar date may still
            # represent an open session. Only prior dates are completed-session bars.
            if observed.date() < cutoff.date() and close > 0:
                rows.append({"t": observed, "c": close, "v": volume})
        rows.sort(key=lambda row: row["t"])  # type: ignore[arg-type]
        return tuple(rows)

    def option_expirations(
        self,
        underlying: str,
        *,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
    ) -> tuple[date, ...]:
        """Return every provider-declared expiration inside the governed horizon."""

        if not self.token:
            raise TradierMarketDataError("Tradier token is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if minimum_days_to_expiry < 1 or maximum_days_to_expiry <= minimum_days_to_expiry:
            raise ValueError("option expiry bounds are invalid")
        symbol = str(underlying).strip().upper().replace(".", "/")
        if not symbol:
            raise TradierMarketDataError("Tradier symbol cannot be empty")
        payload = self._get(
            "/markets/options/expirations",
            params={
                "symbol": symbol,
                "includeAllRoots": "true",
                "strikes": "false",
                "contractSize": "true",
                "expirationType": "true",
            },
        )
        raw = payload.get("expirations")
        if raw is None:
            raise TradierMarketDataError(
                "Tradier option-expiration response is missing expirations"
            )
        discovered: set[date] = set()

        def collect(value: object) -> None:
            if isinstance(value, str):
                try:
                    discovered.add(date.fromisoformat(value.strip()))
                except ValueError:
                    pass
                return
            if isinstance(value, Mapping):
                for nested in value.values():
                    collect(nested)
                return
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                for nested in value:
                    collect(nested)

        collect(raw)
        cutoff = as_of.astimezone(timezone.utc)
        eligible = tuple(
            item
            for item in sorted(discovered)
            if minimum_days_to_expiry
            <= (
                datetime.combine(item, datetime.min.time(), tzinfo=timezone.utc)
                + timedelta(hours=21)
                - cutoff
            ).days
            <= maximum_days_to_expiry
        )
        return eligible

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
            params={
                "symbol": symbol,
                "expiration": expiration.isoformat(),
                "greeks": "true",
            },
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
                contract_size = float(item.get("contract_size"))
                volume = max(0.0, float(item.get("volume", 0.0)))
            except (TypeError, ValueError):
                continue
            if (
                not option_symbol
                or option_type not in {"call", "put"}
                or strike <= 0
                or contract_size <= 0
            ):
                continue
            greeks = item.get("greeks")
            greek_values = greeks if isinstance(greeks, Mapping) else {}
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
                    volume=volume,
                    contract_size=contract_size,
                    implied_volatility=self._optional_number(
                        greek_values.get("mid_iv")
                        or greek_values.get("smv_vol")
                        or greek_values.get("iv")
                    ),
                    delta=self._optional_number(greek_values.get("delta")),
                    gamma=self._optional_number(greek_values.get("gamma")),
                    theta=self._optional_number(greek_values.get("theta")),
                    vega=self._optional_number(greek_values.get("vega")),
                    observed_at=observed,
                    source_identifier=(
                        f"tradier:active-option-chain:{symbol}:{expiration.isoformat()}:{option_symbol}"
                    ),
                )
            )
        if not result:
            raise TradierMarketDataError("Tradier returned no valid active option contracts")
        return tuple(result)

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
    ) -> tuple[TradierOptionSelection, ...]:
        """Select one completed-session contract per right and eligible expiration."""

        if not self.token:
            raise TradierMarketDataError("Tradier token is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        try:
            price = float(underlying_price)
        except (TypeError, ValueError) as error:
            raise ValueError("underlying_price must be positive") from error
        if not math.isfinite(price) or price <= 0.0:
            raise ValueError("underlying_price must be positive")
        if (
            isinstance(maximum_expirations, bool)
            or not isinstance(maximum_expirations, int)
            or maximum_expirations < 1
        ):
            raise ValueError("maximum_expirations must be positive")
        if (
            isinstance(candidates_per_bucket, bool)
            or not isinstance(candidates_per_bucket, int)
            or candidates_per_bucket < 1
        ):
            raise ValueError("candidates_per_bucket must be positive")
        timestamp = as_of.astimezone(timezone.utc)
        symbol = str(underlying).strip().upper().replace(".", "/")
        expirations = self.option_expirations(
            symbol,
            as_of=timestamp,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
        )[:maximum_expirations]
        selections: list[TradierOptionSelection] = []
        missing_buckets: list[str] = []
        for expiration in expirations:
            chain = self.active_option_chain(symbol, expiration, as_of=timestamp)
            for right in ("call", "put"):
                candidates = sorted(
                    (
                        item
                        for item in chain
                        if item.option_type == right
                        and abs(item.strike / price - 1.0)
                        <= _DEFAULT_MONEYNESS_LIMIT
                    ),
                    key=lambda item: (
                        abs(item.strike / price - 1.0),
                        -item.volume,
                        (
                            float("inf")
                            if item.bid is None or item.ask is None
                            else max(0.0, item.ask - item.bid)
                        ),
                        item.option_symbol,
                    ),
                )[:candidates_per_bucket]
                selected: TradierOptionSelection | None = None
                for candidate in candidates:
                    history = self.daily_history(
                        candidate.option_symbol,
                        as_of=timestamp,
                        history_days=_DEFAULT_SELECTION_HISTORY_DAYS,
                    )
                    if not history:
                        continue
                    latest = history[-1]
                    observed = latest.get("t")
                    if not isinstance(observed, datetime):
                        continue
                    close = self._optional_price(latest.get("c"))
                    if close is None:
                        continue
                    try:
                        volume = max(0.0, float(latest.get("v", 0.0)))
                    except (TypeError, ValueError):
                        continue
                    expiration_at = datetime.combine(
                        expiration,
                        datetime.min.time(),
                        tzinfo=timezone.utc,
                    ) + timedelta(hours=21)
                    definition = TradierOptionDefinition(
                        symbol=candidate.option_symbol,
                        raw_symbol=candidate.option_symbol,
                        underlying=symbol,
                        option_right=right,
                        expiration_at=expiration_at,
                        strike=candidate.strike,
                        contract_multiplier=candidate.contract_size,
                        session_date=observed.date(),
                        source_identifier=candidate.source_identifier,
                    )
                    bar = TradierOptionBar(
                        raw_symbol=candidate.option_symbol,
                        observed_at=observed,
                        close=close,
                        volume=volume,
                        source_identifier=(
                            "tradier:option-history:"
                            f"{candidate.option_symbol}:{observed.date().isoformat()}"
                        ),
                    )
                    selected = TradierOptionSelection(definition=definition, bar=bar)
                    break
                if selected is None:
                    missing_buckets.append(f"{expiration.isoformat()}:{right}")
                else:
                    selections.append(selected)
        if missing_buckets:
            raise TradierMarketDataError(
                "Tradier option selection lacks completed-session evidence for "
                "eligible expiration/right buckets: " + ", ".join(missing_buckets[:8])
            )
        return tuple(selections)

    @staticmethod
    def _optional_price(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

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
    "TRADIER_OPTIONS_DATASET",
    "TradierMarketDataError",
    "TradierMarketDataProvider",
    "TradierOptionBar",
    "TradierOptionChainEvidence",
    "TradierOptionDefinition",
    "TradierOptionSelection",
]
