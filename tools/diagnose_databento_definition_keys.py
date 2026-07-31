"""Credential-safe probe of Databento OPRA definition field names."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import requests

URL = "https://hist.databento.com/v0/timeseries.get_range"


def previous_weekday(value):
    cursor = value - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def main() -> int:
    key = (
        os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
        or os.getenv("DATABENTO_API_KEY")
        or ""
    ).strip()
    if not key:
        raise SystemExit("Databento key is not configured")
    session_date = previous_weekday(datetime.now(timezone.utc).date())
    response = requests.post(
        URL,
        auth=(key, ""),
        data={
            "dataset": "OPRA.PILLAR",
            "schema": "definition",
            "symbols": "SPY.OPT",
            "stype_in": "parent",
            "start": session_date.isoformat(),
            "end": (session_date + timedelta(days=1)).isoformat(),
            "encoding": "json",
            "pretty_px": "true",
            "pretty_ts": "true",
            "map_symbols": "true",
            "limit": "5",
        },
        timeout=90,
    )
    records = []
    for line in response.text.splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            records.append(value)
    print(
        json.dumps(
            {
                "status_code": response.status_code,
                "record_count": len(records),
                "record_keys": [sorted(value) for value in records[:5]],
                "instrument_id_types": [
                    type(value.get("instrument_id")).__name__
                    for value in records[:5]
                ],
            },
            sort_keys=True,
        )
    )
    if response.status_code < 200 or response.status_code >= 300 or not records:
        raise SystemExit("definition key probe failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
