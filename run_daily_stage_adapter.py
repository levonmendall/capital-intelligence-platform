"""Run one configured canonical daily stage behind the active fencing token."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.validate_bindings:
            print(json.dumps(validate_stage_bindings(args.bindings), sort_keys=True))
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
        print(json.dumps(result.to_dict(), sort_keys=True))
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
