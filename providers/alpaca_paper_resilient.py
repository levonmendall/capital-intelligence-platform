"""Complete-scope Alpaca historical bars for governed paper evidence.

The base Alpaca client historically limited one multi-symbol request to 100 pages.
That fixed count is not a data-quality boundary: a broad listed universe with ten years
of daily history can legitimately require more pages. This adapter preserves every
requested symbol and the full point-in-time range while bounding each request by an
estimated record budget and rejecting pagination that does not make progress.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from math import ceil
from typing import Any

from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    AlpacaPaperSettings,
    _text,
)


_HISTORY_POLICY_VERSION = "alpaca-complete-historical-bars.v1"
_MAX_SYMBOLS_PER_BATCH = 200
_TARGET_PAGES_PER_BATCH = 80
_MAX_DERIVED_PAGE_BUDGET = 10_000
_TIMEFRAME_PATTERN = re.compile(
    r"^(?P<count>[1-9][0-9]*)(?P<unit>Min|Hour|Day|Week|Month)$",
    re.IGNORECASE,
)
_TIMEFRAME_SECONDS = {
    "min": 60,
    "hour": 60 * 60,
    "day": 24 * 60 * 60,
    "week": 7 * 24 * 60 * 60,
    # Twenty-eight days deliberately overestimates the maximum number of monthly
    # intervals and therefore keeps the page budget conservative.
    "month": 28 * 24 * 60 * 60,
}


def _estimated_bars_per_symbol(
    *,
    start: datetime,
    end: datetime,
    timeframe: str,
) -> int:
    """Return a conservative wall-clock upper estimate for one symbol."""

    match = _TIMEFRAME_PATTERN.fullmatch(timeframe)
    if match is None:
        # Unknown Alpaca timeframe syntax receives the safest one-symbol batching.
        return _MAX_DERIVED_PAGE_BUDGET
    interval_seconds = (
        int(match.group("count"))
        * _TIMEFRAME_SECONDS[match.group("unit").lower()]
    )
    span_seconds = max(1.0, (end - start).total_seconds())
    return max(1, ceil(span_seconds / interval_seconds) + 2)


def _historical_symbol_batch_size(
    *,
    start: datetime,
    end: datetime,
    timeframe: str,
    limit: int,
) -> int:
    """Keep each batch comfortably below its data-derived pagination budget."""

    estimated = _estimated_bars_per_symbol(
        start=start,
        end=end,
        timeframe=timeframe,
    )
    target_records = limit * _TARGET_PAGES_PER_BATCH
    return max(
        1,
        min(
            _MAX_SYMBOLS_PER_BATCH,
            target_records // max(1, estimated),
        ),
    )


def _historical_page_budget(
    *,
    symbol_count: int,
    start: datetime,
    end: datetime,
    timeframe: str,
    limit: int,
) -> int:
    """Derive a finite page ceiling from the requested scope, not a fixed count."""

    estimated_records = symbol_count * _estimated_bars_per_symbol(
        start=start,
        end=end,
        timeframe=timeframe,
    )
    return min(
        _MAX_DERIVED_PAGE_BUDGET,
        max(2, ceil(estimated_records / limit) + 2),
    )


class CompleteHistoricalAlpacaPaperClient(AlpacaPaperClient):
    """Retrieve complete paginated IEX history without order authority."""

    history_policy_version = _HISTORY_POLICY_VERSION

    def historical_bars(
        self,
        symbols: Sequence[str],
        *,
        start: datetime,
        end: datetime,
        timeframe: str = "1Day",
        limit: int = 10_000,
    ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        """Return all requested bars through deterministic scope-sized batches."""

        normalized = tuple(
            dict.fromkeys(_text(item, field_name="symbol").upper() for item in symbols)
        )
        if not normalized:
            return {}
        for field_name, value in (("start", start), ("end", end)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if start >= end:
            raise ValueError("historical bar start must predate end")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise ValueError("historical bar limit must be between 1 and 10000")

        normalized_timeframe = _text(timeframe, field_name="timeframe")
        batch_size = _historical_symbol_batch_size(
            start=start,
            end=end,
            timeframe=normalized_timeframe,
            limit=limit,
        )
        result: dict[str, tuple[Mapping[str, Any], ...]] = {}
        for offset in range(0, len(normalized), batch_size):
            batch = normalized[offset : offset + batch_size]
            batch_result = self._historical_bars_batch(
                batch,
                start=start,
                end=end,
                timeframe=normalized_timeframe,
                limit=limit,
            )
            result.update(batch_result)
        return {symbol: result[symbol] for symbol in normalized}

    def _historical_bars_batch(
        self,
        symbols: tuple[str, ...],
        *,
        start: datetime,
        end: datetime,
        timeframe: str,
        limit: int,
    ) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        """Follow one Alpaca token chain until completion or proven non-progress."""

        result: dict[str, list[Mapping[str, Any]]] = {
            symbol: [] for symbol in symbols
        }
        page_token: str | None = None
        seen_tokens: set[str] = set()
        page_budget = _historical_page_budget(
            symbol_count=len(symbols),
            start=start,
            end=end,
            timeframe=timeframe,
            limit=limit,
        )

        for _page in range(page_budget):
            params: dict[str, object] = {
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "limit": limit,
                "adjustment": "all",
                "feed": self.settings.data_feed.lower(),
                "sort": "asc",
            }
            if page_token is not None:
                params["page_token"] = page_token
            payload = self._get(
                self.settings.data_base_url,
                "/v2/stocks/bars",
                params=params,
            )
            bars = payload.get("bars")
            if not isinstance(bars, Mapping):
                raise AlpacaPaperProviderError(
                    "Alpaca historical-bars response is missing bars"
                )

            page_item_count = 0
            for symbol in symbols:
                values = bars.get(symbol, ())
                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                    raise AlpacaPaperProviderError(
                        f"Alpaca historical bars are invalid for {symbol}"
                    )
                for item in values:
                    if not isinstance(item, Mapping):
                        raise AlpacaPaperProviderError(
                            f"Alpaca historical bar is invalid for {symbol}"
                        )
                    result[symbol].append(item)
                    page_item_count += 1

            raw_token = payload.get("next_page_token")
            if raw_token is None or not str(raw_token).strip():
                return {symbol: tuple(values) for symbol, values in result.items()}
            next_token = str(raw_token).strip()
            if page_item_count == 0:
                raise AlpacaPaperProviderError(
                    "Alpaca historical-bars pagination returned a token without data"
                )
            if next_token in seen_tokens:
                raise AlpacaPaperProviderError(
                    "Alpaca historical-bars pagination token repeated"
                )
            seen_tokens.add(next_token)
            page_token = next_token

        raise AlpacaPaperProviderError(
            "Alpaca historical bars exceeded the data-derived pagination budget "
            f"for {len(symbols)} symbols; pages={page_budget}, "
            f"timeframe={timeframe}, policy={self.history_policy_version}"
        )


def create_complete_alpaca_paper_client(
    *,
    http_get: Callable[..., Any] | None = None,
) -> CompleteHistoricalAlpacaPaperClient:
    """Authenticate the complete-history client against paper-only credentials."""

    candidates = AlpacaPaperSettings.candidates_from_env()
    for _label, settings in candidates:
        client = CompleteHistoricalAlpacaPaperClient(
            settings,
            http_get=http_get,
        )
        try:
            client.account()
        except AlpacaPaperProviderError:
            continue
        return client
    raise AlpacaPaperProviderError(
        "no configured Alpaca paper credential pair authenticated "
        f"({len(candidates)} combinations attempted)"
    )


__all__ = [
    "CompleteHistoricalAlpacaPaperClient",
    "create_complete_alpaca_paper_client",
]
