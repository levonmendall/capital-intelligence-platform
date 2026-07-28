"""Evaluate paper-execution cost calibration evidence."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.execution_calibration import (
    ExecutionCalibrationError,
    ExecutionCalibrationEvaluator,
    ExecutionCalibrationPolicy,
    ExecutionCalibrationState,
    load_execution_calibration_input,
)


def _load_policy(path: str | None) -> ExecutionCalibrationPolicy:
    if path is None:
        return ExecutionCalibrationPolicy()
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read calibration policy {source}") from error
    if not isinstance(value, Mapping):
        raise ValueError("calibration policy must encode an object")
    return ExecutionCalibrationPolicy.from_dict(value)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--evaluated-at must be timezone-aware")
    return parsed


def _write(path: str, payload: Mapping[str, object]) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--evaluated-at")
    parser.add_argument("--output")
    parser.add_argument("--require-passed", action="store_true")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        identifier, execution_policy_version, samples = (
            load_execution_calibration_input(args.input)
        )
        report = ExecutionCalibrationEvaluator(_load_policy(args.policy)).evaluate(
            identifier=identifier,
            execution_policy_version=execution_policy_version,
            samples=samples,
            evaluated_at=_timestamp(args.evaluated_at),
        )
        payload = report.to_dict()
        if args.output:
            _write(args.output, payload)
    except (ExecutionCalibrationError, KeyError, OSError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "state": ExecutionCalibrationState.BLOCKED.value,
                    "error": str(error),
                    "paper_test_authorized": False,
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
    if args.require_passed and report.state is not ExecutionCalibrationState.PASSED:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
