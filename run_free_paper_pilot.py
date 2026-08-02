"""Execute an exact user-approved construction through the free paper pilot.

This command is deliberately limited to paper-only operation. It validates
the exact active-universe capability publication, provider sessions and quotes,
cash and turnover limits, and exact user consent before delegating to
the canonical internal paper-fill engine. It never submits an Alpaca order.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

from operations.free_paper_pilot import (
    active_paper_universe_path,
    assess_free_paper_pilot_readiness,
    default_alpaca_client,
    load_execution_paper_universe,
    validate_pilot_construction,
    write_pilot_profiles,
)
from run_approved_paper_execution import main as run_approved_paper_execution


def _load_construction(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load construction {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("construction must encode a JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--construction", required=True)
    parser.add_argument("--decision-identifier", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--portfolio-code", default="COMPOUNDING")
    parser.add_argument(
        "--universe",
        default=str(active_paper_universe_path()),
        help="Exact certified active-paper-universe publication",
    )
    parser.add_argument("--approval-database")
    parser.add_argument("--alert-database")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args, remaining = build_parser().parse_known_args(argv)
    try:
        if args.portfolio_code != "COMPOUNDING":
            raise ValueError("the free paper pilot supports only COMPOUNDING")
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must be timezone-aware")
        construction = _load_construction(args.construction)
        if not construction.get("eligible_universe_publication_identifier"):
            raise ValueError(
                "construction is missing certified eligible-universe lineage; publish the pilot universe before running the CIO cycle"
            )
        universe = load_execution_paper_universe(
            construction,
            active_path=args.universe,
        )
        validate_pilot_construction(construction, universe=universe)
        readiness = assess_free_paper_pilot_readiness(
            universe=universe,
            client=default_alpaca_client(),
            evaluated_at=as_of,
        )
        traded_symbols = {
            str(item.get("symbol", "")).strip().upper()
            for item in construction.get("trades", ())
            if isinstance(item, Mapping)
        }
        listed_trade = any(
            item.symbol in traded_symbols and not item.uses_direct_market_provider
            for item in universe.instruments
        )
        if not readiness.configuration_ready or (
            listed_trade and not readiness.execution_ready_now
        ):
            detail = "; ".join(readiness.blockers) or (
                "the listed-security market is closed"
                if listed_trade
                else "paper capability validation failed"
            )
            raise ValueError(f"free paper pilot is not execution-ready: {detail}")
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "free_paper_pilot": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    with TemporaryDirectory(prefix="capital-intelligence-free-paper-") as directory:
        profiles_path = write_pilot_profiles(
            universe,
            Path(directory) / "profiles.json",
        )
        forwarded = [
            "--construction",
            args.construction,
            "--decision-identifier",
            args.decision_identifier,
            "--as-of",
            args.as_of,
            "--portfolio-code",
            args.portfolio_code,
        ]
        if args.approval_database:
            forwarded.extend(("--approval-database", args.approval_database))
        if args.alert_database:
            forwarded.extend(("--alert-database", args.alert_database))
        forwarded.extend(
            (
                "--profiles",
                str(profiles_path),
                "--session-provider",
                "operations.direct_global_markets:create_combined_paper_session_provider",
                "--quote-provider",
                "operations.direct_global_markets:create_combined_paper_quote_provider",
                *remaining,
            )
        )
        return run_approved_paper_execution(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
