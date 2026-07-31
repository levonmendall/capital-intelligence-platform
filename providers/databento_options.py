"""Authenticated point-in-time OPRA option definitions and daily bars.

The configured Databento account does not require live OPRA licensing for this paper
research path.  The adapter deliberately uses the latest completed weekday session,
reads provider-native contract definitions, and obtains historical daily OHLCV for a
bounded candidate set.  Missing or unlicensed evidence fails closed; no contract terms
or prices are synthesized.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

import requests

DATABENTO_OPRA_DATASET = "OPRA.PILLAR"
DATABENTO_TIMESERIES_URL = "https://hist.databento.com/v0/timeseries.get_range"


class DatabentoOptionsError(RuntimeError):
    """Raised when authenticated OPRA evidence cannot be certified."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: object, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return _aware(value, field_name=field_name)
    if not isinstance(value, str) or not value.strip():
        raise DatabentoOptionsError(f"{field_name} is unavailable")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    if "." in raw:
        prefix, suffix = raw.split(".", 1)
        offset_index = max(suffix.find("+"), suffix.find("-"))
        if offset_index >= 0:
            fraction = suffix[:offset_index]
            offset = suffix[offset_index:]
        else:
            fraction = suffix
            offset = ""
        raw = f"{prefix}.{fraction[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise DatabentoOptionsError(f"{field_name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool):
        raise DatabentoOptionsError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise DatabentoOptionsError(f"{field_name} must be numeric") from error
    if not math.isfinite(result):
        raise DatabentoOptionsError(f"{field_name} must be finite")
    return result


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatabentoOptionsError(f"{field_name} cannot be empty")
    return value.strip()


def _compact_occ_symbol(raw_symbol: str) -> str:
    compact = "".join(raw_symbol.upper().split())
    if len(compact) < 16:
        raise DatabentoOptionsError("raw OCC symbol is invalid")
    return compact


def _candidate_sessions(as_of: datetime, *, maximum_attempts: int = 7) -> tuple[date, ...]:
    timestamp = _aware(as_of, field_name="as_of")
    cursor = timestamp.date() - timedelta(days=1)
    result: list[date] = []
    while len(result) < maximum_attempts:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= timedelta(days=1)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DatabentoOptionDefinition:
    symbol: str
    raw_symbol: str
    instrument_id: int
    underlying: str
    option_right: str
    expiration_at: datetime
    strike: float
    contract_multiplier: float
    session_date: date

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, field_name="symbol").upper()
        raw_symbol = _text(self.raw_symbol, field_name="raw_symbol").upper()
        underlying = _text(self.underlying, field_name="underlying").upper()
        instrument_id = self.instrument_id
        if (
            isinstance(instrument_id, bool)
            or not isinstance(instrument_id, int)
            or instrument_id < 1
        ):
            raise ValueError("instrument_id must be a positive integer")
        if self.option_right not in {"call", "put"}:
            raise ValueError("option_right must be call or put")
        expiration = _aware(self.expiration_at, field_name="expiration_at")
        strike = _number(self.strike, field_name="strike")
        multiplier = _number(self.contract_multiplier, field_name="contract_multiplier")
        if strike <= 0.0 or multiplier <= 0.0:
            raise ValueError("strike and contract_multiplier must be positive")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "raw_symbol", raw_symbol)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "expiration_at", expiration)
        object.__setattr__(self, "strike", strike)
        object.__setattr__(self, "contract_multiplier", multiplier)


@dataclass(frozen=True, slots=True)
class DatabentoOptionBar:
    raw_symbol: str
    observed_at: datetime
    close: float
    volume: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "raw_symbol",
            _text(self.raw_symbol, field_name="raw_symbol").upper(),
        )
        object.__setattr__(
            self,
            "observed_at",
            _aware(self.observed_at, field_name="observed_at"),
        )
        close = _number(self.close, field_name="close")
        volume = _number(self.volume, field_name="volume")
        if close <= 0.0 or volume < 0.0:
            raise ValueError("close must be positive and volume cannot be negative")
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)


@dataclass(frozen=True, slots=True)
class DatabentoOptionSelection:
    definition: DatabentoOptionDefinition
    bar: DatabentoOptionBar


HttpPost = Callable[..., Any]


class DatabentoOptionsProvider:
    """Bounded authenticated access to completed-session OPRA evidence."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_post: HttpPost = requests.post,
        timeout_seconds: int = 90,
    ) -> None:
        if api_key is None:
            resolved = (
                os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
                or os.getenv("DATABENTO_API_KEY")
                or ""
            ).strip()
        else:
            resolved = str(api_key).strip()
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise TypeError("timeout_seconds must be an integer")
        if timeout_seconds < 1 or timeout_seconds > 180:
            raise ValueError("timeout_seconds must be between 1 and 180")
        self._api_key = resolved
        self._http_post = http_post
        self._timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _records(self, *, data: Mapping[str, object]) -> tuple[Mapping[str, Any], ...]:
        if not self.configured:
            raise DatabentoOptionsError("Databento API key is not configured")
        try:
            response = self._http_post(
                DATABENTO_TIMESERIES_URL,
                auth=(self._api_key, ""),
                data={key: str(value) for key, value in data.items()},
                timeout=self._timeout_seconds,
            )
        except requests.RequestException as error:
            raise DatabentoOptionsError(
                f"Databento OPRA request failed: {type(error).__name__}"
            ) from error
        status = int(getattr(response, "status_code", 0))
        text = str(getattr(response, "text", ""))
        if status < 200 or status >= 300:
            detail = ""
            for line in text.splitlines():
                try:
                    candidate = __import__("json").loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(candidate, Mapping) and candidate.get("detail"):
                    detail = str(candidate["detail"])[:300]
                    break
            suffix = f": {detail}" if detail else ""
            raise DatabentoOptionsError(f"Databento OPRA HTTP {status}{suffix}")
        records: list[Mapping[str, Any]] = []
        for line in text.splitlines():
            try:
                candidate = __import__("json").loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(candidate, Mapping) and "detail" not in candidate:
                records.append(candidate)
        return tuple(records)

    def definitions(
        self,
        underlying: str,
        *,
        as_of: datetime,
        maximum_records: int = 10_000,
    ) -> tuple[DatabentoOptionDefinition, ...]:
        """Return provider-native definitions from the latest completed session."""

        normalized = _text(underlying, field_name="underlying").upper()
        timestamp = _aware(as_of, field_name="as_of")
        if maximum_records < 1 or maximum_records > 50_000:
            raise ValueError("maximum_records must be between 1 and 50000")
        failures: list[str] = []
        for session_date in _candidate_sessions(timestamp):
            end_date = session_date + timedelta(days=1)
            try:
                rows = self._records(
                    data={
                        "dataset": DATABENTO_OPRA_DATASET,
                        "schema": "definition",
                        "symbols": f"{normalized}.OPT",
                        "stype_in": "parent",
                        "start": session_date.isoformat(),
                        "end": end_date.isoformat(),
                        "encoding": "json",
                        "pretty_px": "true",
                        "pretty_ts": "true",
                        "map_symbols": "true",
                        "limit": maximum_records,
                    }
                )
            except DatabentoOptionsError as error:
                failures.append(str(error))
                continue
            definitions: list[DatabentoOptionDefinition] = []
            for row in rows:
                try:
                    raw_symbol = _text(
                        row.get("raw_symbol", row.get("symbol")),
                        field_name="raw_symbol",
                    ).upper()
                    row_underlying = _text(
                        row.get("underlying", row.get("asset")),
                        field_name="underlying",
                    ).upper()
                    instrument_class = _text(
                        row.get("instrument_class"),
                        field_name="instrument_class",
                    ).upper()
                    if row_underlying != normalized or instrument_class not in {"C", "P"}:
                        continue
                    definitions.append(
                        DatabentoOptionDefinition(
                            symbol=_compact_occ_symbol(raw_symbol),
                            raw_symbol=raw_symbol,
                            instrument_id=int(row.get("instrument_id")),
                            underlying=row_underlying,
                            option_right="call" if instrument_class == "C" else "put",
                            expiration_at=_timestamp(
                                row.get("expiration"),
                                field_name="expiration",
                            ),
                            strike=_number(
                                row.get("strike_price"),
                                field_name="strike_price",
                            ),
                            contract_multiplier=_number(
                                row.get("contract_multiplier", 100.0),
                                field_name="contract_multiplier",
                            ),
                            session_date=session_date,
                        )
                    )
                except (DatabentoOptionsError, TypeError, ValueError):
                    continue
            if definitions:
                definitions.sort(
                    key=lambda item: (
                        item.expiration_at,
                        item.option_right,
                        item.strike,
                        item.symbol,
                    )
                )
                return tuple(definitions)
            failures.append(f"no {normalized} definitions on {session_date.isoformat()}")
        detail = failures[-1] if failures else "no completed session was available"
        raise DatabentoOptionsError(
            f"Databento OPRA definitions unavailable for {normalized}: {detail}"
        )

    def daily_bars(
        self,
        instruments: Sequence[DatabentoOptionDefinition | tuple[int, str]],
        *,
        as_of: datetime,
        session_date: date,
        history_days: int = 45,
    ) -> Mapping[str, tuple[DatabentoOptionBar, ...]]:
        """Return completed-session bars using provider-native instrument IDs."""

        timestamp = _aware(as_of, field_name="as_of")
        instrument_lookup: dict[int, str] = {}
        for item in instruments:
            if isinstance(item, DatabentoOptionDefinition):
                instrument_id = item.instrument_id
                raw_symbol = item.raw_symbol
            else:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise TypeError(
                        "instruments must contain definitions or (instrument_id, raw_symbol) tuples"
                    )
                instrument_id, raw_symbol = item
            if (
                isinstance(instrument_id, bool)
                or not isinstance(instrument_id, int)
                or instrument_id < 1
            ):
                raise ValueError("instrument_id must be a positive integer")
            normalized_symbol = _text(raw_symbol, field_name="raw_symbol").upper()
            instrument_lookup.setdefault(instrument_id, normalized_symbol)
        instrument_ids = tuple(instrument_lookup)
        if not instrument_ids:
            return {}
        if history_days < 1 or history_days > 400:
            raise ValueError("history_days must be between 1 and 400")
        end_date = session_date + timedelta(days=1)
        start_date = end_date - timedelta(days=history_days)
        grouped: dict[str, list[DatabentoOptionBar]] = {
            raw_symbol: [] for raw_symbol in instrument_lookup.values()
        }
        batch_size = 20
        for offset in range(0, len(instrument_ids), batch_size):
            batch = instrument_ids[offset : offset + batch_size]
            rows = self._records(
                data={
                    "dataset": DATABENTO_OPRA_DATASET,
                    "schema": "ohlcv-1d",
                    "symbols": ",".join(str(item) for item in batch),
                    "stype_in": "instrument_id",
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "encoding": "json",
                    "pretty_px": "true",
                    "pretty_ts": "true",
                    "limit": max(1_000, len(batch) * history_days),
                }
            )
            for row in rows:
                try:
                    instrument_id = int(row.get("instrument_id"))
                    symbol = instrument_lookup.get(instrument_id)
                    if symbol is None:
                        continue
                    observed = _timestamp(
                        row.get("pretty_ts_event", row.get("ts_event")),
                        field_name="option bar timestamp",
                    )
                    if observed > timestamp:
                        continue
                    grouped[symbol].append(
                        DatabentoOptionBar(
                            raw_symbol=symbol,
                            observed_at=observed,
                            close=_number(
                                row.get("pretty_close", row.get("close")),
                                field_name="close",
                            ),
                            volume=max(
                                0.0,
                                _number(row.get("volume", 0.0), field_name="volume"),
                            ),
                        )
                    )
                except (DatabentoOptionsError, TypeError, ValueError):
                    continue
        return {
            symbol: tuple(sorted(values, key=lambda item: item.observed_at))
            for symbol, values in grouped.items()
            if values
        }

    def latest_daily_bars(
        self,
        instruments: Sequence[DatabentoOptionDefinition | tuple[int, str]],
        *,
        as_of: datetime,
        history_days: int = 45,
    ) -> tuple[date, Mapping[str, tuple[DatabentoOptionBar, ...]]]:
        """Return the newest completed-session bars, retrying exchange holidays."""

        timestamp = _aware(as_of, field_name="as_of")
        failures: list[str] = []
        for session_date in _candidate_sessions(timestamp):
            try:
                bars = self.daily_bars(
                    instruments,
                    as_of=timestamp,
                    session_date=session_date,
                    history_days=history_days,
                )
            except DatabentoOptionsError as error:
                failures.append(str(error))
                continue
            if bars:
                return session_date, bars
            failures.append(f"no priced bars through {session_date.isoformat()}")
        detail = failures[-1] if failures else "no completed session was available"
        raise DatabentoOptionsError(
            f"Databento OPRA daily bars are unavailable: {detail}"
        )

    def select_contracts(
        self,
        underlying: str,
        *,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        maximum_expirations: int = 2,
        candidates_per_bucket: int = 8,
    ) -> tuple[DatabentoOptionSelection, ...]:
        """Select one liquid near-money call and put for each bounded expiration."""

        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        definitions = tuple(
            item
            for item in self.definitions(underlying, as_of=timestamp)
            if minimum_days_to_expiry
            <= (item.expiration_at - timestamp).days
            <= maximum_days_to_expiry
            and abs(item.strike / price - 1.0) <= 0.20
        )
        expirations = tuple(
            sorted({item.expiration_at for item in definitions})[:maximum_expirations]
        )
        buckets: dict[tuple[datetime, str], tuple[DatabentoOptionDefinition, ...]] = {}
        candidates: list[DatabentoOptionDefinition] = []
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
        _priced_session, bars = self.latest_daily_bars(
            tuple(candidates),
            as_of=timestamp,
        )
        selected: list[DatabentoOptionSelection] = []
        for key in sorted(buckets, key=lambda item: (item[0], item[1])):
            choices: list[tuple[float, DatabentoOptionDefinition, DatabentoOptionBar]] = []
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
                selected.append(
                    DatabentoOptionSelection(definition=definition, bar=latest)
                )
        return tuple(selected)

    def validate_access(
        self,
        *,
        as_of: datetime,
        underlying_price: float,
    ) -> dict[str, object]:
        """Prove the same completed-session, near-money OPRA path used in production."""

        timestamp = _aware(as_of, field_name="as_of")
        price = _number(underlying_price, field_name="underlying_price")
        if price <= 0.0:
            raise ValueError("underlying_price must be positive")
        definitions = self.definitions("SPY", as_of=timestamp)
        eligible = tuple(
            item
            for item in definitions
            if 30 <= (item.expiration_at - timestamp).days <= 365
            and abs(item.strike / price - 1.0) <= 0.20
        )
        if not eligible:
            raise DatabentoOptionsError(
                "SPY OPRA definitions contain no eligible near-money expirations"
            )
        selections = self.select_contracts(
            "SPY",
            underlying_price=price,
            as_of=timestamp,
            minimum_days_to_expiry=30,
            maximum_days_to_expiry=365,
            maximum_expirations=3,
            candidates_per_bucket=12,
        )
        if not selections:
            raise DatabentoOptionsError(
                "SPY OPRA near-money contracts contain no completed-session prices"
            )
        priced_session = max(item.bar.observed_at.date() for item in selections)
        return {
            "dataset": DATABENTO_OPRA_DATASET,
            "session_date": priced_session.isoformat(),
            "definition_count": len(definitions),
            "eligible_definition_count": len(eligible),
            "priced_sample_count": len(selections),
            "sample_symbols": tuple(
                item.definition.symbol for item in selections[:5]
            ),
        }


__all__ = [
    "DATABENTO_OPRA_DATASET",
    "DatabentoOptionBar",
    "DatabentoOptionDefinition",
    "DatabentoOptionSelection",
    "DatabentoOptionsError",
    "DatabentoOptionsProvider",
]
