"""Free market and macro-series historical adapters."""

from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from .http import HttpClient
from .models import HistoricalRecord, SourceResult, utc_now
from .sources import HistoricalSource

UTC = timezone.utc


def _chunks(start: date, end: date, days: int):
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=days - 1))
        yield cursor, stop
        cursor = stop + timedelta(days=1)


class FredSource(HistoricalSource):
    """Collect point-in-time macro observations from FRED/ALFRED.

    ``output_type=4`` requests the initial release for each observation. This is both
    materially smaller than a decade-wide real-time-period response and better aligned
    with the replay requirement to use the value first available to decision makers.
    Series failures are isolated so one unavailable endpoint cannot erase every valid
    macro series from the historical archive.
    """

    name = "fred"

    def __init__(
        self,
        client: HttpClient,
        series: Iterable[str],
        api_key: str | None = None,
    ) -> None:
        self.client = client
        self.series = tuple(
            dict.fromkeys(
                str(item).strip().upper()
                for item in series
                if str(item).strip()
            )
        )
        self.api_key = (api_key or os.getenv("FRED_API_KEY", "")).strip()

    def collect(
        self,
        start: date,
        end: date,
        *,
        max_records: int,
    ) -> SourceResult:
        if not self.api_key:
            return SourceResult(
                self.name,
                "unavailable",
                blockers=("FRED_API_KEY_missing",),
            )
        records: list[HistoricalRecord] = []
        failed_series: list[str] = []
        retrieved = utc_now()
        for series in self.series:
            try:
                payload = self.client.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series,
                        "api_key": self.api_key,
                        "file_type": "json",
                        "output_type": 4,
                        "observation_start": start.isoformat(),
                        "observation_end": end.isoformat(),
                        "sort_order": "asc",
                        "limit": 100000,
                    },
                ).json()
                observations = payload.get("observations", [])
                if not isinstance(observations, list):
                    raise ValueError("FRED observations payload is not a list")
                for item in observations:
                    if not isinstance(item, dict) or item.get("value") in {None, "."}:
                        continue
                    observed = str(item["date"])
                    initial_release = item.get("realtime_start")
                    available = str(initial_release or observed)
                    strict = bool(initial_release)
                    limitations = ["release_time_normalized_to_date"]
                    if not strict:
                        limitations.extend(
                            (
                                "initial_release_timestamp_unavailable",
                                "research_bridge_only",
                            )
                        )
                    records.append(
                        HistoricalRecord(
                            source=self.name,
                            dataset=f"series.{series.lower()}",
                            observed_at=observed,
                            available_at=available,
                            retrieved_at=retrieved,
                            strict_replay_eligible=strict,
                            payload={
                                "series_id": series,
                                "value": float(item["value"]),
                                "realtime_start": initial_release,
                                "realtime_end": item.get("realtime_end"),
                                "fred_output_type": 4,
                            },
                            provenance_url="https://fred.stlouisfed.org/",
                            limitations=tuple(limitations),
                        )
                    )
                    if len(records) >= max_records:
                        warnings = [
                            "max_records_reached",
                            "fred_initial_release_only",
                        ]
                        if failed_series:
                            warnings.append(
                                f"series_failed_count:{len(failed_series)}"
                            )
                        return SourceResult(
                            self.name,
                            "degraded",
                            tuple(records),
                            warnings=tuple(warnings),
                        )
            except Exception:
                failed_series.append(series)
                continue

        if failed_series and not records:
            return SourceResult(
                self.name,
                "unavailable",
                blockers=(
                    f"series_collection_failed_count:{len(failed_series)}",
                ),
            )
        warnings = ["fred_initial_release_only"]
        state = "available"
        if failed_series:
            state = "degraded"
            warnings.append(f"series_failed_count:{len(failed_series)}")
        return SourceResult(
            self.name,
            state,
            tuple(records),
            warnings=tuple(warnings),
        )


class CoinbaseSource(HistoricalSource):
    name = "coinbase"

    def __init__(self, client: HttpClient, products: Iterable[str]) -> None:
        self.client = client
        self.products = tuple(
            dict.fromkeys(
                str(item).strip().upper()
                for item in products
                if str(item).strip()
            )
        )

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        retrieved = utc_now()
        try:
            for product in self.products:
                for left, right in _chunks(start, end, 299):
                    rows = self.client.get(
                        f"https://api.exchange.coinbase.com/products/{product}/candles",
                        params={
                            "granularity": 86400,
                            "start": f"{left.isoformat()}T00:00:00Z",
                            "end": f"{(right + timedelta(days=1)).isoformat()}T00:00:00Z",
                        },
                    ).json()
                    for timestamp, low, high, open_, close, volume in rows:
                        observed = datetime.fromtimestamp(int(timestamp), tz=UTC)
                        records.append(
                            HistoricalRecord(
                                source=self.name,
                                dataset=f"daily_ohlcv.{product.lower()}",
                                observed_at=observed,
                                available_at=observed + timedelta(days=1),
                                retrieved_at=retrieved,
                                strict_replay_eligible=True,
                                payload={
                                    "symbol": product,
                                    "open": float(open_),
                                    "high": float(high),
                                    "low": float(low),
                                    "close": float(close),
                                    "volume": float(volume),
                                    "currency": product.split("-")[-1],
                                },
                                provenance_url="https://exchange.coinbase.com/",
                                limitations=(
                                    "single_venue_history",
                                    "daily_bar_available_after_close",
                                ),
                            )
                        )
                        if len(records) >= max_records:
                            return SourceResult(
                                self.name,
                                "degraded",
                                tuple(records),
                                warnings=("max_records_reached",),
                            )
            return SourceResult(self.name, "available", tuple(records))
        except Exception as error:
            return self._degraded(records, error)


class StooqSource(HistoricalSource):
    name = "stooq"

    def __init__(self, client: HttpClient, symbols: Iterable[str]) -> None:
        self.client = client
        self.symbols = tuple(
            dict.fromkeys(
                str(item).strip().lower()
                for item in symbols
                if str(item).strip()
            )
        )

    def collect(self, start: date, end: date, *, max_records: int) -> SourceResult:
        records: list[HistoricalRecord] = []
        missing_symbols: list[str] = []
        retrieved = utc_now()
        try:
            for symbol in self.symbols:
                before = len(records)
                response = self.client.get(
                    "https://stooq.com/q/d/l/",
                    params={
                        "s": symbol,
                        "d1": start.strftime("%Y%m%d"),
                        "d2": end.strftime("%Y%m%d"),
                        "i": "d",
                    },
                )
                for item in csv.DictReader(
                    io.StringIO(response.body.decode("utf-8", errors="replace"))
                ):
                    if not item.get("Date") or not item.get("Close"):
                        continue
                    records.append(
                        HistoricalRecord(
                            source=self.name,
                            dataset=f"daily_ohlcv.{symbol}",
                            observed_at=item["Date"],
                            available_at=item["Date"],
                            retrieved_at=retrieved,
                            strict_replay_eligible=False,
                            payload={
                                "symbol": symbol.upper(),
                                "open": float(item["Open"]),
                                "high": float(item["High"]),
                                "low": float(item["Low"]),
                                "close": float(item["Close"]),
                                "volume": float(item.get("Volume") or 0),
                            },
                            provenance_url="https://stooq.com/",
                            limitations=(
                                "publication_timestamp_unavailable",
                                "survivorship_and_adjustment_policy_not_certified",
                                "research_bridge_only",
                            ),
                        )
                    )
                    if len(records) >= max_records:
                        return SourceResult(
                            self.name,
                            "degraded",
                            tuple(records),
                            warnings=("max_records_reached",),
                        )
                if len(records) == before:
                    missing_symbols.append(symbol)

            if not records:
                return SourceResult(
                    self.name,
                    "unavailable",
                    blockers=("configured_symbols_returned_no_records",),
                    warnings=tuple(
                        ["non_strict_research_bridge"]
                        + [f"missing_symbol:{item}" for item in missing_symbols]
                    ),
                )

            warnings = ["non_strict_research_bridge"]
            state = "available"
            if missing_symbols:
                state = "degraded"
                warnings.append(f"missing_symbol_count:{len(missing_symbols)}")
                warnings.extend(f"missing_symbol:{item}" for item in missing_symbols)
            return SourceResult(
                self.name,
                state,
                tuple(records),
                warnings=tuple(warnings),
            )
        except Exception as error:
            return self._degraded(records, error)
