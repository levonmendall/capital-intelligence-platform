"""Evaluate the latest weighted synthesis under evidence-governance policy."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from api.config import ApiSettings
from intelligence.governance import MultiEngineGovernor
from intelligence.governance_store import SQLiteGovernanceStore
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.synthesis_store import SQLiteSynthesisStore


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
            "Apply versioned missing-data, conflict, confidence-ceiling, and veto "
            "governance without committee submission or portfolio authority."
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
        help="Print the governance result without appending it to history.",
    )
    args = parser.parse_args()
    as_of = _parse_as_of(args.as_of)
    settings = ApiSettings.from_env()
    path = settings.snapshot_database.with_name("analytical_engines.db")
    if not path.exists():
        parser.error("analytical engine history is not available")
    bundle = SQLiteNormalizationStore(path, read_only=True).latest(
        at_or_before=as_of
    )
    synthesis = SQLiteSynthesisStore(path, read_only=True).latest(
        at_or_before=as_of
    )
    if bundle is None or synthesis is None:
        parser.error("normalization and weighted synthesis are required")
    governor = MultiEngineGovernor()
    result = governor.evaluate(bundle, synthesis)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if not args.no_persist:
        store = SQLiteGovernanceStore(path)
        store.append_policy(governor.policy)
        store.append(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
