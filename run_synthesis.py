"""Apply the versioned synthesis-weight policy to normalization history."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from api.config import ApiSettings
from intelligence.normalization_store import SQLiteNormalizationStore
from intelligence.synthesis_store import SQLiteSynthesisStore
from intelligence.synthesis_weights import MultiEngineSynthesizer


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
            "Apply fixed versioned weights to normalized engine assessments "
            "without vetoes, committee judgment, market stance, or score activation."
        )
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Latest normalization timestamp to use. Defaults to now.",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Print without appending policy and result history.",
    )
    args = parser.parse_args()
    as_of = _parse_as_of(args.as_of)
    settings = ApiSettings.from_env()
    path = settings.snapshot_database.with_name("analytical_engines.db")
    if not path.exists():
        parser.error("analytical_engines.db does not exist")
    bundle = SQLiteNormalizationStore(path, read_only=True).latest(
        at_or_before=as_of
    )
    if bundle is None:
        parser.error("no normalization bundle is available at or before --as-of")
    synthesizer = MultiEngineSynthesizer()
    result = synthesizer.synthesize(bundle)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    if not args.no_persist:
        store = SQLiteSynthesisStore(path)
        store.append_policy(synthesizer.policy)
        store.append(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
