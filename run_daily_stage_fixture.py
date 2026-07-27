"""Deterministic non-production stage fixture for container acceptance tests."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from typing import Sequence

from operations import CanonicalDailyStage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=tuple(item.value for item in CanonicalDailyStage))
    parser.add_argument("--operation-identifier", required=True)
    parser.add_argument("--stage-idempotency-key", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--knowledge-cutoff", required=True)
    parser.add_argument("--input-identifiers-json", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cutoff = datetime.fromisoformat(args.knowledge_cutoff.replace("Z", "+00:00"))
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("knowledge cutoff must be timezone-aware")
    inputs = json.loads(args.input_identifiers_json)
    if not isinstance(inputs, list) or not inputs or not all(
        isinstance(item, str) and item.strip() for item in inputs
    ):
        raise ValueError("fixture requires non-empty canonical input identifiers")
    digest = hashlib.sha256(
        "|".join(
            (
                args.operation_identifier,
                args.stage,
                args.stage_idempotency_key,
                str(args.attempt),
                cutoff.isoformat(),
                *inputs,
            )
        ).encode("utf-8")
    ).hexdigest()[:20]
    print(
        json.dumps(
            {
                "identifier": (
                    f"validation-authority:{args.operation_identifier}:"
                    f"{args.stage}:{digest}"
                ),
                "stage": args.stage,
                "knowledge_cutoff": cutoff.isoformat(),
                "inputs": inputs,
                "fixture_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
