"""Manage the optional legacy paper-campaign risk switch."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from governance import (
    PaperTradingControlEvent,
    PaperTradingControlState,
    SQLitePaperTestEntryGovernanceStore,
    SQLitePaperTradingControlStore,
    SQLitePaperTradingLaunchStore,
)
from governance.paper_execution_authority import require_human_paper_test_entry


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--effective-at must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("activate", "halt", "status"))
    parser.add_argument("--baseline-identifier", required=True)
    parser.add_argument("--process-version", required=True)
    parser.add_argument("--code-version", required=True)
    parser.add_argument("--effective-at")
    parser.add_argument("--identifier")
    parser.add_argument("--reason")
    parser.add_argument("--authority-identifier", action="append", default=[])
    parser.add_argument(
        "--entry-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE",
            str(data_dir / "paper_test_governance.db"),
        ),
    )
    parser.add_argument(
        "--launch-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE",
            str(data_dir / "paper_trading_launch.db"),
        ),
    )
    parser.add_argument(
        "--control-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_CONTROL_DATABASE",
            str(data_dir / "paper_trading_control.db"),
        ),
    )
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    human = None
    try:
        effective_at = _timestamp(args.effective_at)
        control_store = SQLitePaperTradingControlStore(args.control_database)
        if args.action == "status":
            event = control_store.active_event(
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                as_of=effective_at,
            )
            payload = {
                "state": (
                    PaperTradingControlState.HALTED.value
                    if event is None
                    else event.state.value
                ),
                "event": None if event is None else event.to_dict(),
                "effective_at": effective_at.isoformat(),
                "real_money_authorized": False,
            }
        else:
            if not args.identifier or not args.reason or not args.authority_identifier:
                raise ValueError(
                    "activate and halt require --identifier, --reason, and at least "
                    "one --authority-identifier"
                )
            launch_report_identifier = None
            state = PaperTradingControlState.HALTED
            if args.action == "activate":
                human = require_human_paper_test_entry(
                    entry_store=SQLitePaperTestEntryGovernanceStore(
                        args.entry_database
                    ),
                    baseline_identifier=args.baseline_identifier,
                    process_version=args.process_version,
                    code_version=args.code_version,
                    as_of=effective_at,
                )
                launch = SQLitePaperTradingLaunchStore(
                    args.launch_database
                ).latest_ready(
                    baseline_identifier=args.baseline_identifier,
                    process_version=args.process_version,
                    code_version=args.code_version,
                    as_of=effective_at,
                )
                if launch is None:
                    raise ValueError(
                        "cannot activate runtime paper execution without a current "
                        "sustained launch certification"
                    )
                state = PaperTradingControlState.ACTIVE
                launch_report_identifier = launch.identifier
            event = PaperTradingControlEvent(
                identifier=args.identifier,
                state=state,
                effective_at=effective_at,
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                reason=args.reason,
                authority_identifiers=tuple(args.authority_identifier),
                launch_report_identifier=launch_report_identifier,
            )
            sequence = control_store.append(event)
            control_store.verify_integrity()
            payload = event.to_dict()
            payload["registry_sequence"] = sequence
            payload["human_entry_decision_identifier"] = (
                None if human is None else human.decision.identifier
            )
            payload["eligibility_package_identifier"] = (
                None if human is None else human.package.identifier
            )
            payload["eligibility_package_fingerprint"] = (
                None if human is None else human.package.fingerprint
            )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "state": PaperTradingControlState.HALTED.value,
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    print(
        json.dumps(
            payload,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
