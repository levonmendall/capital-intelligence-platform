"""Credential-safe probe of Databento OPRA JSON field names only."""

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
            "schema": "ohlcv-1d",
            "symbols": "SPY.OPT",
            "stype_in": "parent",
            "start": session_date.isoformat(),
            "end": (session_date + timedelta(days=1)).isoformat(),
            "encoding": "json",
            "pretty_px": "true",
            "pretty_ts": "true",
            "map_symbols": "true",
            "limit": "20",
        },
        timeout=90,
    )
    print(json.dumps({"status_code": response.status_code, "session_date": session_date.isoformat()}))
    records = []
    for line in response.text.splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            records.append(value)
    summaries = []
    for value in records[:10]:
        summaries.append(
            {
                "keys": sorted(value),
                "rtype": str(value.get("rtype", "")),
                "has_symbol": "symbol" in value,
                "has_instrument_id": "instrument_id" in value,
                "price_fields": sorted(
                    key_name
                    for key_name in value
                    if key_name in {"open", "high", "low", "close", "pretty_open", "pretty_high", "pretty_low", "pretty_close"}
                ),
            }
        )
    print(json.dumps({"record_count": len(records), "record_shapes": summaries}, sort_keys=True))
    if response.status_code < 200 or response.status_code >= 300:
        raise SystemExit("OPRA schema probe failed")
    if not records:
        raise SystemExit("OPRA schema probe returned no records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
