"""Run the point-in-time Market Breadth engine."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from api.config import ApiSettings
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.market_breadth import build_configured_market_breadth_engine


def _parse_as_of(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "as-of must be an ISO-8601 datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("as-of must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and persist the configured Market Breadth engine."
    )
    parser.add_argument(
        "--as-of",
        type=_parse_as_of,
        default=None,
        help="Point-in-time decision timestamp. Defaults to now in UTC.",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=None,
        help=(
            "Immutable market-breadth-input.v1 provider export. Defaults to "
            "CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE."
        ),
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Render the result without appending it to engine history.",
    )
    args = parser.parse_args()
    as_of = args.as_of or datetime.now(timezone.utc)
    result = build_configured_market_breadth_engine(
        data_file=args.data_file,
        clock=lambda: as_of,
    ).run(as_of=as_of).result
    if not args.no_persist:
        settings = ApiSettings.from_env()
        SQLiteAnalyticalEngineStore(
            settings.snapshot_database.with_name("analytical_engines.db")
        ).append(result)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
