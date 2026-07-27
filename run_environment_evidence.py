"""Publish or inspect certified decision Environment evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from application import (
    CertifiedDecisionEnvironmentSnapshot,
    SQLiteEnvironmentEvidenceStore,
    SubsequentEnvironmentObservation,
)


def _load(path: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read Environment JSON {path!r}") from error
    if not isinstance(payload, Mapping):
        raise ValueError("Environment JSON must encode an object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--snapshot")
    mode.add_argument("--observation")
    mode.add_argument("--latest", action="store_true")
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ENVIRONMENT_DATABASE",
            str(data_dir / "environment_evidence.db"),
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = SQLiteEnvironmentEvidenceStore(args.database)
        if args.snapshot:
            snapshot = CertifiedDecisionEnvironmentSnapshot.from_dict(
                _load(args.snapshot)
            )
            sequence = store.append_snapshot(snapshot)
            payload = {**snapshot.to_dict(), "registry_sequence": sequence}
        elif args.observation:
            observation = SubsequentEnvironmentObservation.from_dict(
                _load(args.observation)
            )
            sequence = store.append_observation(observation)
            payload = {**observation.to_dict(), "registry_sequence": sequence}
        else:
            payload = store.latest_view()
            if payload is None:
                raise ValueError("no certified decision Environment snapshot exists")
        store.verify_integrity()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "decision_time_certified": False,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
