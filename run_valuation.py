"""Run the point-in-time Valuation intelligence engine."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from api.config import ApiSettings
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.valuation import (
    JSONValuationProvider,
    ValuationEngine,
    build_configured_valuation_engine,
)


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--as-of must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the point-in-time equity-market valuation engine."
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=None,
        help="Immutable valuation-input.v1 provider export.",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Decision timestamp in ISO-8601 format. Defaults to now.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Print the result without appending it to analytical history.",
    )
    args = parser.parse_args()
    as_of = _parse_as_of(args.as_of)
    if args.data_file is not None:
        engine = ValuationEngine(JSONValuationProvider(args.data_file))
    else:
        engine = build_configured_valuation_engine()
    run = engine.run(as_of=as_of)
    print(json.dumps(run.result.to_dict(), indent=2, sort_keys=True))
    if not args.no_persist:
        settings = ApiSettings.from_env()
        store = SQLiteAnalyticalEngineStore(
            settings.snapshot_database.with_name("analytical_engines.db")
        )
        store.append(run.result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
