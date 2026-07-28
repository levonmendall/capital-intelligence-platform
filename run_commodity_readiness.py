"""Evaluate the mandatory commodity baseline before controlled paper execution."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from governance.commodity_readiness import (
    CommodityReadinessError,
    build_commodity_readiness_report,
    write_commodity_readiness_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scope",
        default="config/commodity_paper_test_scope.json",
        help="Version-controlled commodity scope",
    )
    parser.add_argument(
        "--evidence",
        required=True,
        help="Provider, certification, and eligible-universe evidence JSON",
    )
    parser.add_argument(
        "--as-of",
        help="Optional timezone-aware assessment boundary; defaults to evidence as_of",
    )
    parser.add_argument(
        "--report",
        default="reports/commodity-paper-test-readiness.json",
        help="Credential-free readiness report destination",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        assessed_at = None
        if args.as_of:
            assessed_at = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
            if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
                raise ValueError("--as-of must be timezone-aware")
        report = build_commodity_readiness_report(
            scope_path=args.scope,
            evidence_path=args.evidence,
            assessed_at=assessed_at,
        )
        write_commodity_readiness_report(report, args.report)
    except (CommodityReadinessError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {"status": "error", "error": str(error)},
                sort_keys=True,
            )
        )
        return 4
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
