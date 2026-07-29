"""Point-in-time feature generation for research-only shadow replay."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from .models import HistoricalRecord, parse_timestamp


def _price_records(records: Iterable[HistoricalRecord]) -> dict[str, list[tuple[datetime, float]]]:
    prices: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for record in records:
        close = record.payload.get("close")
        symbol = record.payload.get("symbol")
        if close is None or not symbol:
            continue
        prices[str(symbol)].append((record.observed_datetime, float(close)))
    for values in prices.values():
        values.sort(key=lambda item: item[0])
    return prices


def market_features(records: Iterable[HistoricalRecord], *, cutoff: str) -> dict[str, dict[str, Any]]:
    cutoff_dt = parse_timestamp(cutoff)
    prices = _price_records(record for record in records if record.available_datetime <= cutoff_dt)
    result: dict[str, dict[str, Any]] = {}
    for symbol, values in prices.items():
        closes = [value for timestamp, value in values if timestamp <= cutoff_dt]
        if len(closes) < 21:
            continue
        returns = [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
        lookback_20 = returns[-20:]
        lookback_252 = closes[-253:] if len(closes) >= 253 else closes
        momentum = lookback_252[-1] / lookback_252[0] - 1.0 if len(lookback_252) > 1 else 0.0
        volatility = statistics.pstdev(lookback_20) * math.sqrt(252) if len(lookback_20) > 1 else 0.0
        peak = max(closes)
        drawdown = closes[-1] / peak - 1.0
        result[symbol] = {
            "last_close": closes[-1],
            "momentum": momentum,
            "annualized_volatility": volatility,
            "drawdown": drawdown,
            "observation_count": len(closes),
        }
    return result


def event_features(records: Iterable[HistoricalRecord], *, cutoff: str, days: int = 30) -> dict[str, int]:
    cutoff_dt = parse_timestamp(cutoff)
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        age = (cutoff_dt - record.available_datetime).days
        if 0 <= age <= days and record.available_datetime <= cutoff_dt:
            counts[record.source] += 1
    return dict(sorted(counts.items()))
