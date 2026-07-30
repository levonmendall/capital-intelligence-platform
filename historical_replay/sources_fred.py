"""Point-in-time FRED/ALFRED historical adapter.

The FRED observations API defaults its real-time period to the request date. Historical
initial releases therefore require an explicit real-time window in addition to the
observation window. The adapter chunks that window, preserves valid partial series, and
never promotes a record whose release date was unavailable at the replay cutoff.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Iterable

from .http import HttpClient
from .models import HistoricalRecord, SourceResult, utc_now
from .sources import HistoricalSource

_REALTIME_CHUNK_DAYS = 366
_WARMUP_DAYS = 31


def _chunks(start: date, end: date, days: int = _REALTIME_CHUNK_DAYS):
    cursor = start
    while cursor <= end:
        stop = min(end, cursor + timedelta(days=days - 1))
        yield cursor, stop
        cursor = stop + timedelta(days=1)


class FredSource(HistoricalSource):
    """Collect initial-release macro observations through explicit ALFRED windows."""

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
        if start > end:
            raise ValueError("start must not be after end")
        if max_records < 1:
            raise ValueError("max_records must be positive")

        records: list[HistoricalRecord] = []
        seen: set[tuple[str, str, str]] = set()
        failed_series: list[str] = []
        partial_series: list[str] = []
        retrieved = utc_now()
        realtime_start = start - timedelta(days=_WARMUP_DAYS)

        for series in self.series:
            series_record_count = 0
            series_failed = False
            for left, right in _chunks(realtime_start, end):
                try:
                    payload = self.client.get(
                        "https://api.stlouisfed.org/fred/series/observations",
                        params={
                            "series_id": series,
                            "api_key": self.api_key,
                            "file_type": "json",
                            "output_type": 4,
                            "realtime_start": left.isoformat(),
                            "realtime_end": right.isoformat(),
                            "observation_start": realtime_start.isoformat(),
                            "observation_end": end.isoformat(),
                            "sort_order": "asc",
                            "limit": 100000,
                            "offset": 0,
                        },
                    ).json()
                    if not isinstance(payload, dict):
                        raise ValueError("FRED observations payload is not an object")
                    if payload.get("error_code") or payload.get("error_message"):
                        raise ValueError("FRED observations endpoint returned an error")
                    observations = payload.get("observations", [])
                    if not isinstance(observations, list):
                        raise ValueError("FRED observations payload is not a list")
                except Exception:
                    series_failed = True
                    continue

                for item in observations:
                    if not isinstance(item, dict) or item.get("value") in {None, "."}:
                        continue
                    observed = str(item.get("date") or "").strip()
                    initial_release = str(item.get("realtime_start") or "").strip()
                    if not observed:
                        continue
                    available = initial_release or observed
                    try:
                        available_date = date.fromisoformat(available)
                    except ValueError:
                        series_failed = True
                        continue
                    if available_date < realtime_start or available_date > end:
                        continue
                    key = (series, observed, available)
                    if key in seen:
                        continue
                    seen.add(key)
                    strict = bool(initial_release)
                    limitations = ["release_time_normalized_to_date"]
                    if not strict:
                        limitations.extend(
                            (
                                "initial_release_timestamp_unavailable",
                                "research_bridge_only",
                            )
                        )
                    try:
                        value = float(item["value"])
                    except (TypeError, ValueError):
                        series_failed = True
                        continue
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
                                "value": value,
                                "realtime_start": initial_release or None,
                                "realtime_end": item.get("realtime_end"),
                                "fred_output_type": 4,
                                "requested_realtime_start": left.isoformat(),
                                "requested_realtime_end": right.isoformat(),
                            },
                            provenance_url="https://fred.stlouisfed.org/",
                            limitations=tuple(limitations),
                        )
                    )
                    series_record_count += 1
                    if len(records) >= max_records:
                        warnings = [
                            "max_records_reached",
                            "fred_initial_release_explicit_realtime_window",
                        ]
                        if failed_series:
                            warnings.append(
                                f"series_failed_count:{len(failed_series)}"
                            )
                        if partial_series or series_failed:
                            warnings.append(
                                f"series_partial_count:{len(partial_series) + int(series_failed)}"
                            )
                        return SourceResult(
                            self.name,
                            "degraded",
                            tuple(records),
                            warnings=tuple(warnings),
                        )

            if series_failed:
                if series_record_count:
                    partial_series.append(series)
                else:
                    failed_series.append(series)
            elif not series_record_count:
                failed_series.append(series)

        if (failed_series or partial_series) and not records:
            return SourceResult(
                self.name,
                "unavailable",
                blockers=(
                    f"series_collection_failed_count:{len(failed_series) + len(partial_series)}",
                ),
            )

        warnings = ["fred_initial_release_explicit_realtime_window"]
        state = "available"
        if failed_series or partial_series:
            state = "degraded"
            if failed_series:
                warnings.append(f"series_failed_count:{len(failed_series)}")
            if partial_series:
                warnings.append(f"series_partial_count:{len(partial_series)}")
        return SourceResult(
            self.name,
            state,
            tuple(records),
            warnings=tuple(warnings),
        )


__all__ = ["FredSource"]
