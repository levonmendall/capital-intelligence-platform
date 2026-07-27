"""Record and inspect governed crypto, FX, and global-market approvals."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateAssetClass
from governance import (
    EXPANSION_ASSET_CLASSES,
    AssetClassApproval,
    AssetClassScopeAuthority,
    SQLiteAssetClassApprovalStore,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamps must include a UTC offset")
    return parsed


def _database(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    data_dir = Path(
        os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_ASSET_CLASS_GOVERNANCE_DATABASE",
            str(data_dir / "asset_class_governance.db"),
        )
    ).expanduser()


def _payload(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read approval JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("approval JSON must encode an object")
    return value


def _approval_payload(approval: AssetClassApproval, *, sequence: int) -> dict[str, Any]:
    result = approval.to_dict()
    result["registry_sequence"] = sequence
    result["paper_eligible"] = approval.profile.paper_eligible
    result["missing_paper_capabilities"] = list(
        approval.profile.missing_paper_capabilities
    )
    return result


def _status_payload(
    store: SQLiteAssetClassApprovalStore,
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    authority = AssetClassScopeAuthority(store)
    markets: list[dict[str, Any]] = []
    for asset_class in sorted(EXPANSION_ASSET_CLASSES, key=lambda item: item.value):
        approval = store.active(asset_class, evaluated_at=evaluated_at)
        markets.append(
            {
                "asset_class": asset_class.value,
                "active_approval_identifier": (
                    None if approval is None else approval.identifier
                ),
                "approval_state": (
                    None if approval is None else approval.profile.state.value
                ),
                "paper_eligible": (
                    False if approval is None else approval.profile.paper_eligible
                ),
                "effective_at": (
                    None if approval is None else approval.effective_at.isoformat()
                ),
                "expires_at": (
                    None if approval is None else approval.expires_at.isoformat()
                ),
                "missing_paper_capabilities": (
                    []
                    if approval is None
                    else list(approval.profile.missing_paper_capabilities)
                ),
                "policy_version": authority.policy_version,
            }
        )
    return {
        "evaluated_at": evaluated_at.isoformat(),
        "integrity_verified": store.verify_integrity(),
        "development_open": True,
        "test_ready": False,
        "real_money_authorized": False,
        "markets": markets,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database")
    parser.add_argument(
        "--approval",
        help="Append one immutable AssetClassApproval JSON document.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Inspect active approvals without changing governance state.",
    )
    parser.add_argument(
        "--asset-class",
        choices=tuple(item.value for item in EXPANSION_ASSET_CLASSES),
        help="Filter approval history to one expansion asset class.",
    )
    parser.add_argument("--evaluated-at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if bool(args.approval) == bool(args.status):
        parser.error("choose exactly one of --approval or --status")
    try:
        store = SQLiteAssetClassApprovalStore(_database(args.database))
        evaluated_at = _timestamp(args.evaluated_at)
        if args.status:
            payload = _status_payload(store, evaluated_at=evaluated_at)
            if args.asset_class:
                selected = CandidateAssetClass(args.asset_class)
                payload["markets"] = [
                    item
                    for item in payload["markets"]
                    if item["asset_class"] == selected.value
                ]
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        approval = AssetClassApproval.from_dict(_payload(args.approval))
        if args.asset_class and approval.profile.asset_class.value != args.asset_class:
            raise ValueError(
                "approval asset class does not match --asset-class filter"
            )
        sequence = store.append(approval)
        store.verify_integrity()
        print(
            json.dumps(
                _approval_payload(approval, sequence=sequence),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, indent=2))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
