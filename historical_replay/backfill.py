"""Resumable ten-year historical backfill coordinator."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import BackfillReport, SourceResult, iso_timestamp, utc_now
from .sources import HistoricalSource, build_sources
from .store import HistoricalStore

UTC = timezone.utc


def ten_year_window(as_of: date | None = None) -> tuple[date, date]:
    end = as_of or datetime.now(tz=UTC).date()
    try:
        start = end.replace(year=end.year - 10)
    except ValueError:
        start = end.replace(year=end.year - 10, day=28)
    return start, end


def load_config(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class HistoricalBackfillCoordinator:
    def __init__(self, *, store: HistoricalStore, sources: Iterable[HistoricalSource]) -> None:
        self.store = store
        self.sources = tuple(sources)

    def run(self, *, start: date, end: date, max_records_per_source: int = 100_000) -> BackfillReport:
        if start > end:
            raise ValueError("start must not be after end")
        started = utc_now()
        results: list[SourceResult] = []
        written = duplicates = strict_records = 0
        for source in self.sources:
            checkpoint = self.store.read_checkpoint(source.name)
            effective_start = start
            completed_through = checkpoint.get("completed_through")
            if completed_through:
                next_day = date.fromisoformat(str(completed_through)) + timedelta(days=1)
                if next_day > effective_start:
                    effective_start = next_day
            if effective_start > end:
                results.append(SourceResult(source.name, "available", warnings=("already_current",)))
                continue
            result = source.collect(effective_start, end, max_records=max_records_per_source)
            source_written, source_duplicates = self.store.append(result.records)
            written += source_written
            duplicates += source_duplicates
            strict_records += sum(1 for record in result.records if record.strict_replay_eligible)
            results.append(result)
            if result.state in {"available", "degraded"} and result.records:
                self.store.write_checkpoint(
                    source.name,
                    {
                        "completed_through": end.isoformat(),
                        "last_state": result.state,
                        "last_record_count": len(result.records),
                        "updated_at": iso_timestamp(utc_now()),
                    },
                )
        states = {item.state for item in results}
        state = "available" if states <= {"available"} else "degraded" if "failed" not in states else "failed"
        report = BackfillReport(
            started_at=iso_timestamp(started),
            completed_at=iso_timestamp(utc_now()),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            source_results=tuple(results),
            records_written=written,
            duplicates_skipped=duplicates,
            state=state,
            strict_replay_records=strict_records,
        )
        self.store.write_manifest("latest-backfill", report.as_dict())
        return report


def coordinator_from_config(*, config_path: str | Path, data_root: str | Path, user_agent: str) -> HistoricalBackfillCoordinator:
    config = load_config(config_path)
    return HistoricalBackfillCoordinator(
        store=HistoricalStore(data_root),
        sources=build_sources(config, user_agent=user_agent),
    )
