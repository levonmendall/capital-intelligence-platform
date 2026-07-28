"""Validate exact paper-engine availability for every classified asset class."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from operations.all_markets_paper_rehearsal import (
    run_all_markets_paper_rehearsal,
)
from operations.universal_paper_availability import (
    assess_universal_paper_availability,
    load_universal_paper_asset_class_scope,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must be timezone-aware")
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        default="config/universal_paper_asset_classes.json",
    )
    parser.add_argument("--evaluated-at")
    parser.add_argument("--working-directory")
    parser.add_argument("--output")
    parser.add_argument("--require-available", action="store_true")
    args = parser.parse_args(argv)
    try:
        evaluated_at = _timestamp(args.evaluated_at)
        rehearsal = run_all_markets_paper_rehearsal(
            evaluated_at=evaluated_at,
            working_directory=args.working_directory,
        )
        report = assess_universal_paper_availability(
            scope=load_universal_paper_asset_class_scope(args.scope),
            evaluated_at=evaluated_at,
            rehearsed_asset_classes=rehearsal.filled_asset_classes,
        )
        payload = report.to_dict()
        payload["rehearsal"] = rehearsal.to_dict()
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.require_available and not report.available:
            return 3
        return 0 if report.available else 2
    except Exception as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        print(
            json.dumps(
                {
                    "available": false,
                    "status": "failed",
                    "error": str(error),
                    "live_order_routing_authorized": false,
                    "real_money_authorized": false
                },
                sort_keys=True,
            ).replace("false", "false")
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
