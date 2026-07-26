"""Normalize the latest point-in-time analytical-engine results."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from api.config import ApiSettings
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.normalization import EXPECTED_ENGINE_ORDER, MultiEngineNormalizer
from intelligence.normalization_store import SQLiteNormalizationStore


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--as-of must include a timezone")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Translate the seven analytical engines into comparable dimensions "
            "without applying weights, vetoes, committee judgment, or market stance."
        )
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Decision timestamp in ISO-8601 format. Defaults to now.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Print the bundle without appending it to normalization history.",
    )
    args = parser.parse_args()
    as_of = _parse_as_of(args.as_of)
    settings = ApiSettings.from_env()
    path = settings.snapshot_database.with_name("analytical_engines.db")
    results = ()
    if path.exists():
        engine_store = SQLiteAnalyticalEngineStore(path, read_only=True)
        results = tuple(
            result
            for engine in EXPECTED_ENGINE_ORDER
            if (result := engine_store.latest(engine, at_or_before=as_of)) is not None
        )
    bundle = MultiEngineNormalizer().normalize(results, as_of=as_of)
    print(json.dumps(bundle.to_dict(), indent=2, sort_keys=True))
    if not args.no_persist:
        SQLiteNormalizationStore(path).append(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
