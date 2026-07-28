"""Execute one exact user-approved paper implementation.

This is the canonical user-consent bridge. It requires an active approval for the
exact CIO decision and construction payload, then delegates to the existing
multi-asset paper executor, which independently enforces launch, runtime,
portfolio, universe, quote, and reconciliation controls.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance.paper_decision_approval import (
    PaperDecisionApprovalError,
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
    require_user_approved_paper_decision,
)
from run_multi_asset_paper_execution import main as run_multi_asset_paper_execution


def _load_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read canonical construction {path!r}") from error
    if not isinstance(value, dict):
        raise ValueError("canonical construction must encode an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--construction", required=True)
    parser.add_argument("--decision-identifier", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--portfolio-code", default="COMPOUNDING")
    parser.add_argument(
        "--approval-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE",
            str(data_dir / "paper_test_governance.db"),
        ),
    )
    return parser


def _forwarded_arguments(args: argparse.Namespace, remaining: Sequence[str]) -> list[str]:
    return [
        "--construction",
        args.construction,
        "--decision-identifier",
        args.decision_identifier,
        "--as-of",
        args.as_of,
        "--portfolio-code",
        args.portfolio_code,
        *remaining,
        "--require-complete",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    args, remaining = build_parser().parse_known_args(argv)
    try:
        construction: Mapping[str, Any] = _load_object(args.construction)
        construction_identifier = str(construction["request_identifier"]).strip()
        if not construction_identifier:
            raise ValueError("construction request_identifier is unavailable")
        as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("--as-of must be timezone-aware")
        construction_hash = canonical_construction_sha256(construction)
        store = SQLitePaperDecisionApprovalStore(args.approval_database)
        approval = require_user_approved_paper_decision(
            store=store,
            decision_identifier=args.decision_identifier,
            construction_identifier=construction_identifier,
            construction_sha256=construction_hash,
            as_of=as_of,
        )
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "user_approval_required": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4

    result = run_multi_asset_paper_execution(
        _forwarded_arguments(args, remaining)
    )
    if result != 0:
        return result

    execution_identifier = f"multi-asset-execution:{construction_identifier}"
    try:
        store.conclude(
            state=PaperDecisionApprovalState.EXECUTED,
            decision_identifier=approval.decision_identifier,
            construction_identifier=approval.construction_identifier,
            construction_sha256=approval.construction_sha256,
            actor_user_id="system:paper-execution",
            actor_session_id="worker:paper-execution",
            occurred_at=as_of,
            rationale=(
                "The exact approved construction completed through the governed "
                "multi-asset paper executor."
            ),
            execution_identifier=execution_identifier,
        )
    except PaperDecisionApprovalError as error:
        print(
            json.dumps(
                {
                    "status": "completed_with_approval_record_error",
                    "error": str(error),
                    "execution_identifier": execution_identifier,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
