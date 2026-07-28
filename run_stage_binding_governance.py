"""Record, inspect, and validate exact production stage-binding approvals."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance.stage_binding_approval import (
    SQLiteStageBindingApprovalStore,
    StageBindingApproval,
    require_approved_stage_bindings,
    stage_binding_sha256,
)


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read approval JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("approval JSON must encode an object")
    return value


def _database(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_STAGE_BINDING_APPROVAL_DATABASE",
            str(data_dir / "stage_binding_approvals.db"),
        )
    ).expanduser()


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record-approval")
    group.add_argument("--validate-bindings")
    group.add_argument("--inspect-bindings")
    parser.add_argument("--baseline-identifier")
    parser.add_argument("--process-version")
    parser.add_argument("--code-version")
    parser.add_argument("--evaluated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        database = _database(args.database)
        store = SQLiteStageBindingApprovalStore(database)
        if args.record_approval:
            approval = StageBindingApproval.from_dict(_load(args.record_approval))
            sequence = store.append(approval)
            payload = {**approval.to_dict(), "registry_sequence": sequence}
        elif args.inspect_bindings:
            digest = stage_binding_sha256(args.inspect_bindings)
            approvals = store.approvals(digest)
            payload = {
                "binding_sha256": digest,
                "approvals": [item.to_dict() for item in approvals],
                "integrity_verified": store.verify_integrity(),
                "real_money_authorized": False,
            }
        else:
            required = {
                "baseline_identifier": args.baseline_identifier,
                "process_version": args.process_version,
                "code_version": args.code_version,
            }
            missing = tuple(name for name, value in required.items() if not value)
            if missing:
                raise ValueError(
                    "binding validation requires exact deployment values: "
                    + ", ".join(missing)
                )
            approval = require_approved_stage_bindings(
                args.validate_bindings,
                approval_database=database,
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                evaluated_at=_timestamp(args.evaluated_at),
                environ=os.environ,
            )
            payload = {
                "status": "approved",
                "binding_sha256": stage_binding_sha256(args.validate_bindings),
                "approval": approval.to_dict(),
                "real_money_authorized": False,
            }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
