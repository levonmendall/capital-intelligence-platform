"""Run a resumable immutable external-provider historical backfill."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Sequence

from operations.provider_backfill import (
    ProviderBackfillError,
    ProviderBackfillRunner,
    load_provider_backfill_plan,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = load_provider_backfill_plan(args.plan)
        report = ProviderBackfillRunner().run(
            plan,
            output_directory=args.output_directory,
            evaluated_at=datetime.now(timezone.utc),
        )
        payload = report.to_dict()
    except (OSError, ProviderBackfillError, TypeError, ValueError) as error:
        payload = {
            "state": "failed",
            "error": str(error),
            "real_money_authorized": False,
        }
        print(json.dumps(payload, sort_keys=True))
        return 4
    print(json.dumps(payload, indent=None if args.compact else 2, sort_keys=True))
    return 0 if report.completed else 3 if report.required_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
