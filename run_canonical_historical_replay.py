"""Run research-only historical decisions through the production CanonicalCIOCycle."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from historical_replay.backfill import ten_year_window
from historical_replay.canonical import HistoricalCanonicalContextBuilder
from historical_replay.canonical_runtime_v5 import (
    MacroCompleteCanonicalHistoricalReplayEngine,
)
from historical_replay.store import HistoricalStore


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--data-root",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
            "database/historical_replay",
        ),
    )
    result.add_argument("--start")
    result.add_argument("--end")
    result.add_argument(
        "--cadence",
        choices=("weekly", "monthly"),
        default="monthly",
    )
    result.add_argument("--strict-only", action="store_true")
    result.add_argument("--minimum-observations", type=int, default=63)
    result.add_argument("--maximum-candidates", type=int, default=25)
    result.add_argument(
        "--initial-portfolio-value",
        type=float,
        default=250_000.0,
    )
    result.add_argument("--report", default="")
    return result


def main() -> int:
    args = parser().parse_args()
    default_start, default_end = ten_year_window()
    start = date.fromisoformat(args.start) if args.start else default_start
    end = date.fromisoformat(args.end) if args.end else default_end
    if start > end:
        raise ValueError("start must not be after end")
    engine = MacroCompleteCanonicalHistoricalReplayEngine(
        HistoricalStore(args.data_root),
        builder=HistoricalCanonicalContextBuilder(
            minimum_observations=args.minimum_observations,
            maximum_candidates=args.maximum_candidates,
        ),
    )
    payload = engine.run(
        start=start,
        end=end,
        cadence=args.cadence,
        strict_only=args.strict_only,
        initial_portfolio_value=args.initial_portfolio_value,
    )
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload.get("certification_ready") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
