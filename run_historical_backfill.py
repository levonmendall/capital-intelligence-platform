"""Run a bounded historical backfill from free and public sources."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from historical_replay.backfill import coordinator_from_config, ten_year_window
from historical_replay.runtime import run_loop


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--config", default=os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_CONFIG", "config/historical_replay_free_sources.json"))
    result.add_argument("--data-root", default=os.getenv("CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR", "database/historical_replay"))
    result.add_argument("--start")
    result.add_argument("--end")
    result.add_argument("--max-records-per-source", type=int, default=100000)
    result.add_argument("--report", default="")
    result.add_argument("--loop", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.loop:
        return run_loop()
    default_start, default_end = ten_year_window()
    start = date.fromisoformat(args.start) if args.start else default_start
    end = date.fromisoformat(args.end) if args.end else default_end
    user_agent = os.getenv("SEC_USER_AGENT", "").strip() or "Capital-Intelligence-Platform historical-research contact=repository-owner"
    coordinator = coordinator_from_config(config_path=args.config, data_root=args.data_root, user_agent=user_agent)
    payload = coordinator.run(start=start, end=end, max_records_per_source=args.max_records_per_source).as_dict()
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if payload["state"] in {"available", "degraded"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
