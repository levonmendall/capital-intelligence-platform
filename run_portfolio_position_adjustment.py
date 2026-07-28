"""Book one evidenced non-cash share split in the canonical paper portfolio."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from portfolio import PortfolioPositionAdjustmentService, SQLiteCanonicalPortfolioStore


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
    parser.add_argument("--event-identifier", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--instrument-identifier", required=True)
    parser.add_argument("--split-ratio", required=True, type=float)
    parser.add_argument("--source-identifier", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--as-of")
    parser.add_argument(
        "--portfolio-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
            str(data_dir / "canonical_portfolio.db"),
        ),
    )
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
        adjustment = PortfolioPositionAdjustmentService(store).apply_split(
            portfolio=portfolio,
            event_identifier=args.event_identifier,
            symbol=args.symbol,
            instrument_identifier=args.instrument_identifier,
            split_ratio=args.split_ratio,
            as_of=_timestamp(args.as_of),
            source_identifier=args.source_identifier,
            rationale=args.rationale,
        )
        payload = adjustment.to_dict()
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
