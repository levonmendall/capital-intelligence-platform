"""Backfill realized paper P&L from complete canonical historical fills."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from portfolio import (
    PortfolioAccountingMigrationService,
    SQLiteCanonicalPortfolioStore,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portfolio-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
            str(data_dir / "canonical_portfolio.db"),
        ),
    )
    parser.add_argument(
        "--source-identifier",
        default="canonical-average-cost-accounting-migration.v1",
    )
    parser.add_argument("--as-of")
    parser.add_argument("--output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = SQLiteCanonicalPortfolioStore(args.portfolio_database)
        store.verify_integrity()
        portfolio = store.latest()
        if portfolio is None:
            raise ValueError("canonical portfolio is unavailable")
        report = PortfolioAccountingMigrationService(store).enrich(
            portfolio=portfolio,
            as_of=_timestamp(args.as_of),
            source_identifier=args.source_identifier,
        )
        payload = report.to_dict()
        if args.output:
            destination = Path(args.output).expanduser()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
