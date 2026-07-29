"""Generate research-only walk-forward shadow decisions from stored evidence."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from historical_replay.backfill import ten_year_window
from historical_replay.replay import ShadowReplayEngine
from historical_replay.store import HistoricalStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default="database/historical_replay")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--cadence", choices=("weekly", "monthly"), default="monthly")
    parser.add_argument("--include-nonstrict", action="store_true")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    default_start, default_end = ten_year_window()
    report = ShadowReplayEngine(HistoricalStore(args.data_root)).run(
        start=date.fromisoformat(args.start) if args.start else default_start,
        end=date.fromisoformat(args.end) if args.end else default_end,
        cadence=args.cadence,
        strict_only=not args.include_nonstrict,
    )
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
