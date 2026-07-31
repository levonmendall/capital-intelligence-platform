"""Credential-safe comparison of Databento OPRA identifier protocols."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Mapping

import requests

URL = "https://hist.databento.com/v0/timeseries.get_range"


def previous_weekday(value):
    cursor = value - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def json_records(response):
    result = []
    for line in response.text.splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, Mapping) and "detail" not in value:
            result.append(value)
    return result


def header_id(row):
    header = row.get("hd")
    if isinstance(header, Mapping):
        return header.get("instrument_id")
    return row.get("instrument_id")


def post(key, data):
    return requests.post(URL, auth=(key, ""), data=data, timeout=120)


def main() -> int:
    key = (
        os.getenv("CAPITAL_INTELLIGENCE_DATABENTO_API_KEY")
        or os.getenv("DATABENTO_API_KEY")
        or ""
    ).strip()
    if not key:
        raise SystemExit("Databento key is not configured")
    now = datetime.now(timezone.utc)
    session_date = previous_weekday(now.date())
    chart = requests.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/SPY",
        params={"range": "5d", "interval": "1d"},
        headers={"User-Agent": "capital-intelligence-provider-diagnostic/1.0"},
        timeout=20,
    ).json()
    closes = chart["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    price = float(tuple(item for item in closes if item is not None)[-1])
    definition_response = post(
        key,
        {
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
            "limit": "10000",
        },
    )
    definitions = json_records(definition_response)
    eligible = []
    for row in definitions:
        try:
            expiration = datetime.fromisoformat(
                str(row["expiration"]).replace("Z", "+00:00")
            )
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            strike = float(row["strike_price"])
            instrument_class = str(row["instrument_class"]).upper()
            normalized_id = int(header_id(row))
            raw_id = int(row["raw_instrument_id"])
            raw_symbol = str(row["raw_symbol"])
        except (KeyError, TypeError, ValueError):
            continue
        days = (expiration - now).days
        if 30 <= days <= 365 and instrument_class in {"C", "P"} and abs(strike / price - 1.0) <= 0.05:
            eligible.append(
                {
                    "distance": abs(strike / price - 1.0),
                    "normalized_id": normalized_id,
                    "raw_id": raw_id,
                    "raw_symbol": raw_symbol,
                }
            )
    eligible.sort(key=lambda item: item["distance"])
    sample = eligible[:8]
    if not sample:
        raise SystemExit("no near-money definition sample was available")
    protocols = {
        "normalized_instrument_id": (
            "instrument_id",
            ",".join(str(item["normalized_id"]) for item in sample),
        ),
        "raw_instrument_id": (
            "instrument_id",
            ",".join(str(item["raw_id"]) for item in sample),
        ),
        "raw_symbol": (
            "raw_symbol",
            ",".join(str(item["raw_symbol"]) for item in sample),
        ),
    }
    summaries = {}
    for name, (stype_in, symbols) in protocols.items():
        response = post(
            key,
            {
                "dataset": "OPRA.PILLAR",
                "schema": "ohlcv-1d",
                "symbols": symbols,
                "stype_in": stype_in,
                "start": (session_date - timedelta(days=7)).isoformat(),
                "end": (session_date + timedelta(days=1)).isoformat(),
                "encoding": "json",
                "pretty_px": "true",
                "pretty_ts": "true",
                "limit": "1000",
            },
        )
        records = json_records(response)
        summaries[name] = {
            "status_code": response.status_code,
            "record_count": len(records),
            "record_keys": sorted(records[0]) if records else [],
            "header_keys": sorted(records[0].get("hd", {}))
            if records and isinstance(records[0].get("hd"), Mapping)
            else [],
        }
    print(
        json.dumps(
            {
                "definition_status": definition_response.status_code,
                "definition_count": len(definitions),
                "eligible_count": len(eligible),
                "sample_count": len(sample),
                "session_date": session_date.isoformat(),
                "protocols": summaries,
            },
            sort_keys=True,
        )
    )
    if not any(item["record_count"] > 0 for item in summaries.values()):
        raise SystemExit("no identifier protocol returned priced OPRA rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
