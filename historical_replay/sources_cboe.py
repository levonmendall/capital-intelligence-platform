"""Official Cboe VIX daily-close history for point-in-time replay coverage."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta

from .http import HttpClient
from .models import HistoricalRecord, SourceResult, utc_now
from .sources import HistoricalSource

CBOE_VIX_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
)
_WARMUP_DAYS = 31


def _date(value: str) -> date:
    text = value.strip()
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError("unsupported Cboe VIX date")


class CboeVixSource(HistoricalSource):
    """Collect official daily VIX closes with conservative next-day availability."""

    name = "cboe"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def collect(
        self,
        start: date,
        end: date,
        *,
        max_records: int,
    ) -> SourceResult:
        if start > end:
            raise ValueError("start must not be after end")
        if max_records < 1:
            raise ValueError("max_records must be positive")

        try:
            response = self.client.get(CBOE_VIX_HISTORY_URL)
            text = response.body.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            if reader.fieldnames is None:
                raise ValueError("Cboe VIX CSV is missing a header")
        except Exception as error:
            return self._degraded((), error)

        lower_bound = start - timedelta(days=_WARMUP_DAYS)
        retrieved = utc_now()
        records: list[HistoricalRecord] = []
        invalid_rows = 0
        for raw in reader:
            row = {str(key).strip().upper(): value for key, value in raw.items()}
            try:
                observed = _date(str(row.get("DATE") or ""))
                close = float(str(row.get("CLOSE") or "").strip())
            except (TypeError, ValueError):
                invalid_rows += 1
                continue
            if observed < lower_bound or observed > end or close <= 0.0:
                continue
            available = observed + timedelta(days=1)
            records.append(
                HistoricalRecord(
                    source=self.name,
                    dataset="series.vixcls",
                    observed_at=observed,
                    available_at=available,
                    retrieved_at=retrieved,
                    strict_replay_eligible=True,
                    payload={
                        "series_id": "VIXCLS",
                        "symbol": "VIX",
                        "value": close,
                        "availability_policy": "conservative_next_calendar_day",
                        "official_daily_close": True,
                    },
                    provenance_url=CBOE_VIX_HISTORY_URL,
                    limitations=(
                        "official_close_has_no_intraday_release_timestamp",
                        "availability_conservatively_normalized_to_next_calendar_day",
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

        if not records:
            return SourceResult(
                self.name,
                "unavailable",
                blockers=("cboe_vix_history_empty",),
            )
        warnings = (
            (f"invalid_row_count:{invalid_rows}",) if invalid_rows else ()
        )
        return SourceResult(
            self.name,
            "available",
            tuple(records),
            warnings=warnings,
        )


__all__ = ["CBOE_VIX_HISTORY_URL", "CboeVixSource"]
