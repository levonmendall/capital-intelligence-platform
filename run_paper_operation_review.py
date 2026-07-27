"""Record paper-operation observations and assess governance-review readiness."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from evaluation import (
    PaperOperationEvidenceEvaluator,
    PaperOperationPolicy,
    SQLitePaperOperationEvidenceStore,
    observation_from_payload,
    policy_from_payload,
)


def _timestamp(value: str | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _json(path: str) -> Any:
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def _observations(paths: Sequence[str]) -> tuple[Mapping[str, Any], ...]:
    payloads: list[Mapping[str, Any]] = []
    for path in paths:
        payload = _json(path)
        values = payload if isinstance(payload, list) else [payload]
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("observation files must contain an object or list of objects")
            payloads.append(item)
    return tuple(payloads)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Append immutable paper-operation evidence and assess whether the "
            "sample is blocked, insufficient, or ready for formal human "
            "governance review. This command never authorizes real-money trading."
        )
    )
    parser.add_argument(
        "--database",
        help="Override the append-only paper-operation evidence database.",
    )
    parser.add_argument(
        "--observation",
        action="append",
        default=[],
        help="JSON observation file; may be repeated and may contain a list.",
    )
    parser.add_argument(
        "--policy",
        help="Optional JSON file overriding the versioned assessment policy.",
    )
    parser.add_argument("--evaluated-at", help="ISO-8601 assessment timestamp.")
    parser.add_argument(
        "--record-report",
        action="store_true",
        help="Append the assessment to the tamper-evident report history.",
    )
    parser.add_argument(
        "--require-governance-ready",
        action="store_true",
        help="Exit nonzero unless evidence is ready for formal governance review.",
    )
    args = parser.parse_args(argv)

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    database = (
        Path(args.database).expanduser()
        if args.database is not None
        else data_dir / "paper_operation_evidence.db"
    )
    try:
        policy = PaperOperationPolicy()
        if args.policy is not None:
            payload = _json(args.policy)
            if not isinstance(payload, dict):
                raise ValueError("policy must encode an object")
            policy = policy_from_payload(payload)
        incoming = tuple(observation_from_payload(item) for item in _observations(args.observation))
        evaluated_at = _timestamp(args.evaluated_at, field_name="evaluated_at")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))

    store = SQLitePaperOperationEvidenceStore(
        database,
        initialize=bool(incoming) or args.record_report,
    )
    for observation in incoming:
        store.append_observation(observation)
    store.verify_integrity()
    report = PaperOperationEvidenceEvaluator(policy).evaluate(
        reversed(store.observations()),
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
    )
    if args.record_report:
        store.append_report(report)
    payload = report.to_dict()
    payload["recorded_observation_identifiers"] = [item.identifier for item in incoming]
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report.ready_for_governance_review or not args.require_governance_ready else 3


if __name__ == "__main__":
    raise SystemExit(main())
