"""Run one configured canonical daily stage behind the active fencing token."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Sequence

from governance.stage_binding_approval import require_approved_stage_bindings
from operations import CanonicalDailyStage
from operations.stage_bindings import (
    StageBindingError,
    StageBindingTimeout,
    execute_stage_binding,
    load_stage_bindings,
    validate_stage_bindings,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=tuple(item.value for item in CanonicalDailyStage))
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--validate-bindings", action="store_true")
    parser.add_argument("--operation-identifier")
    parser.add_argument("--operation-idempotency-key")
    parser.add_argument("--stage-idempotency-key")
    parser.add_argument("--attempt")
    parser.add_argument("--scheduled-for")
    parser.add_argument("--decision-timestamp")
    parser.add_argument("--knowledge-cutoff")
    parser.add_argument("--portfolio-code")
    parser.add_argument("--process-version")
    parser.add_argument("--code-version")
    parser.add_argument("--input-identifiers-json")
    return parser


def _require_governed_bindings(
    path: str,
    *,
    process_version: str | None,
    code_version: str | None,
) -> dict[str, object] | None:
    database = os.getenv("CAPITAL_INTELLIGENCE_STAGE_BINDING_APPROVAL_DATABASE")
    if not database:
        return None
    baseline = os.getenv("CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER")
    resolved_process = process_version or os.getenv(
        "CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION"
    )
    resolved_code = code_version or os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
    missing = tuple(
        name
        for name, value in (
            ("CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER", baseline),
            ("CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION", resolved_process),
            ("CAPITAL_INTELLIGENCE_RELEASE", resolved_code),
        )
        if not value
    )
    if missing:
        raise StageBindingError(
            "stage-binding governance is configured but deployment identity is missing: "
            + ", ".join(missing)
        )
    approval = require_approved_stage_bindings(
        path,
        approval_database=database,
        baseline_identifier=str(baseline),
        process_version=str(resolved_process),
        code_version=str(resolved_code),
        evaluated_at=datetime.now(timezone.utc),
        environ=os.environ,
    )
    return {
        "approval_identifier": approval.identifier,
        "binding_sha256": approval.binding_sha256,
        "baseline_identifier": approval.baseline_identifier,
        "process_version": approval.process_version,
        "code_version": approval.code_version,
        "real_money_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        approval = _require_governed_bindings(
            args.bindings,
            process_version=args.process_version,
            code_version=args.code_version,
        )
        if args.validate_bindings:
            result = validate_stage_bindings(args.bindings)
            result["governance"] = approval or {
                "status": "not_configured",
                "real_money_authorized": False,
            }
            print(json.dumps(result, sort_keys=True))
            return 0
        required = (
            "stage",
            "operation_identifier",
            "operation_idempotency_key",
            "stage_idempotency_key",
            "attempt",
            "scheduled_for",
            "decision_timestamp",
            "knowledge_cutoff",
            "portfolio_code",
            "process_version",
            "code_version",
            "input_identifiers_json",
        )
        missing = tuple(name for name in required if not getattr(args, name))
        if missing:
            parser.error(f"stage execution is missing required arguments: {missing}")
        stage = CanonicalDailyStage(args.stage)
        bindings = load_stage_bindings(args.bindings)
        replacements = {
            "stage": stage.value,
            "operation_identifier": args.operation_identifier,
            "operation_idempotency_key": args.operation_idempotency_key,
            "stage_idempotency_key": args.stage_idempotency_key,
            "attempt": args.attempt,
            "scheduled_for": args.scheduled_for,
            "decision_timestamp": args.decision_timestamp,
            "knowledge_cutoff": args.knowledge_cutoff,
            "portfolio_code": args.portfolio_code,
            "process_version": args.process_version,
            "code_version": args.code_version,
            "input_identifiers_json": args.input_identifiers_json,
        }
        result = execute_stage_binding(bindings[stage], replacements=replacements)
        payload = result.to_dict()
        if approval is not None:
            payload["binding_approval"] = approval
        print(json.dumps(payload, sort_keys=True))
        return 0
    except StageBindingTimeout as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "classification": "timeout",
                    "retryable": True,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 75
    except (OSError, TypeError, ValueError, StageBindingError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "classification": "stage_binding",
                    "retryable": False,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
