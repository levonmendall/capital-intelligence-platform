"""Persistent daily-history adapter for Alpaca paper evidence collection.

The adapter delegates live account/assets/clock/quotes to the underlying paper client but
serves multi-year daily history from the governed point-in-time historical store whenever
coverage is recent.  Stale complete coverage refreshes only a bounded overlapping tail;
missing horizons are fetched in full once.  It has no investment or execution authority.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

from operations.persistent_historical_evidence import PersistentHistoricalEvidenceStore

_ASSET_CLASS = "paper_listed"
_PROVIDER_SCOPE = "alpaca_iex_1day"
_MINIMUM_DELTA_DAYS = 7
_DELTA_OVERLAP_DAYS = 3


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("paper history timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _store_rows(raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    rows: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        observed = _timestamp(item.get("t", item.get("observed_at")))
        if observed is None:
            continue
        rows.append(
            {
                "t": observed,
                "c": item.get("c", item.get("close")),
                "v": item.get("v", item.get("volume", 0.0)),
                "provider_kind": str(item.get("provider_kind") or "alpaca_iex"),
                "source_identifier": str(
                    item.get("source_identifier")
                    or f"alpaca-iex-daily:{observed.date().isoformat()}"
                ),
            }
        )
    return tuple(rows)


def _client_rows(rows: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "t": _aware(item["t"]).isoformat(),  # type: ignore[arg-type]
            "c": float(item["c"]),
            "v": float(item.get("v", 0.0)),
        }
        for item in rows
    )


def _recent(requested_as_of: datetime | None, *, as_of: datetime, max_age_hours: float) -> bool:
    if requested_as_of is None:
        return False
    age = _aware(as_of) - _aware(requested_as_of)
    return timedelta(0) <= age <= timedelta(hours=max_age_hours)


def _delta_days(requested_as_of: datetime | None, *, as_of: datetime) -> int:
    if requested_as_of is None:
        return _MINIMUM_DELTA_DAYS
    age_days = max(
        0,
        math.ceil((_aware(as_of) - _aware(requested_as_of)).total_seconds() / 86400.0),
    )
    return max(_MINIMUM_DELTA_DAYS, age_days + _DELTA_OVERLAP_DAYS)


class PersistentAlpacaPaperHistoryClient:
    """Delegate Alpaca operations while deduplicating immutable daily history."""

    def __init__(self, client, *, values=None) -> None:
        self._client = client
        self._store = PersistentHistoricalEvidenceStore(values)

    def __getattr__(self, name: str):
        return getattr(self._client, name)

    def historical_bars(self, symbols, *, start, end, timeframe="1Day"):
        if timeframe != "1Day" or not self._store.enabled:
            return self._client.historical_bars(
                symbols,
                start=start,
                end=end,
                timeframe=timeframe,
            )
        as_of = _aware(end)
        requested_days = max(1, int(math.ceil((as_of - _aware(start)).total_seconds() / 86400.0)))
        normalized = tuple(
            dict.fromkeys(
                str(symbol).strip().upper()
                for symbol in symbols
                if str(symbol).strip()
            )
        )
        result: dict[str, tuple[dict[str, object], ...]] = {}
        full: list[str] = []
        refresh: dict[str, object] = {}

        for symbol in normalized:
            cached = self._store.load(
                asset_class=_ASSET_CLASS,
                instrument_identity=symbol,
                provider_scope=_PROVIDER_SCOPE,
                as_of=as_of,
            )
            if cached.maximum_history_days < requested_days or not cached.rows:
                full.append(symbol)
            elif _recent(
                cached.requested_as_of,
                as_of=as_of,
                max_age_hours=self._store.max_age_hours,
            ):
                result[symbol] = _client_rows(cached.rows)
            else:
                refresh[symbol] = cached

        if full:
            fetched = self._client.historical_bars(
                tuple(full),
                start=start,
                end=as_of,
                timeframe="1Day",
            )
            for symbol in full:
                rows = _store_rows(fetched.get(symbol, ()))
                if not rows:
                    continue
                merged = self._store.merge(
                    asset_class=_ASSET_CLASS,
                    instrument_identity=symbol,
                    provider_scope=_PROVIDER_SCOPE,
                    rows=rows,
                    requested_as_of=as_of,
                    requested_history_days=requested_days,
                )
                result[symbol] = _client_rows(merged.rows)

        if refresh:
            delta = max(
                _delta_days(cached.requested_as_of, as_of=as_of)
                for cached in refresh.values()
            )
            fetched = self._client.historical_bars(
                tuple(refresh),
                start=as_of - timedelta(days=min(requested_days, delta)),
                end=as_of,
                timeframe="1Day",
            )
            for symbol, cached in refresh.items():
                rows = _store_rows(fetched.get(symbol, ()))
                if not rows:
                    # Fail closed by withholding stale evidence when the required tail
                    # refresh could not be obtained.
                    continue
                merged = self._store.merge(
                    asset_class=_ASSET_CLASS,
                    instrument_identity=symbol,
                    provider_scope=_PROVIDER_SCOPE,
                    rows=rows,
                    requested_as_of=as_of,
                    requested_history_days=cached.maximum_history_days,
                )
                result[symbol] = _client_rows(merged.rows)

        return {symbol: result[symbol] for symbol in normalized if symbol in result}


__all__ = ["PersistentAlpacaPaperHistoryClient"]
