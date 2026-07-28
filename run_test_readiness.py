"""Assess and persist controlled paper-product test readiness.

The canonical path assembles evidence from append-only gate certifications,
operational evidence, active multi-asset approvals, and an exact sustained
paper-launch authorization. ``--manual-evidence`` remains an explicit
compatibility mode and is never treated as the canonical authority.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from governance import (
    ProductTestReadiness,
    ProductTestReadinessEvidence,
    ProductTestReadinessEvidenceAssembler,
    ProductTestReadinessEvaluator,
    SQLiteAssetClassApprovalStore,
    SQLitePaperTradingLaunchStore,
    SQLiteProductTestReadinessStore,
    SQLiteReadinessEvidenceStore,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--assessed-at must be timezone-aware")
    return parsed


def _manual_evidence(path: str) -> ProductTestReadinessEvidence:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manual readiness evidence must encode an object")
    return ProductTestReadinessEvidence.from_dict(payload)


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manual-evidence",
        "--evidence",
        dest="manual_evidence",
        help=(
            "Explicit compatibility mode using a caller-supplied evidence JSON. "
            "Omit to assemble from persisted canonical authorities."
        ),
    )
    parser.add_argument("--baseline-identifier")
    parser.add_argument("--process-version")
    parser.add_argument(
        "--code-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_RELEASE"),
    )
    parser.add_argument("--assessed-at")
    parser.add_argument(
        "--readiness-evidence-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_READINESS_EVIDENCE_DATABASE",
            str(data_dir / "product_readiness_evidence.db"),
        ),
    )
    parser.add_argument(
        "--asset-class-governance-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_ASSET_CLASS_GOVERNANCE_DATABASE",
            str(data_dir / "asset_class_governance.db"),
        ),
    )
    parser.add_argument(
        "--paper-launch-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE",
            str(data_dir / "paper_trading_launch.db"),
        ),
    )
    parser.add_argument(
        "--database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_TEST_READINESS_DATABASE",
            str(data_dir / "product_test_readiness.db"),
        ),
    )
    parser.add_argument(
        "--maximum-operational-age-hours",
        type=float,
        default=24.0,
    )
    parser.add_argument(
        "--development-item",
        action="append",
        default=[],
        help="Record an open development item without blocking a valid test baseline.",
    )
    parser.add_argument("--require-ready", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    evidence_source = "manual_compatibility"
    launch_identifier = None
    try:
        if args.manual_evidence:
            evidence = _manual_evidence(args.manual_evidence)
        else:
            evidence_source = "persisted_authorities"
            if not args.code_version:
                raise ValueError(
                    "automatic readiness assembly requires --code-version or "
                    "CAPITAL_INTELLIGENCE_RELEASE"
                )
            if args.maximum_operational_age_hours <= 0:
                raise ValueError(
                    "--maximum-operational-age-hours must be positive"
                )
            assessed_at = _timestamp(args.assessed_at)
            evidence = ProductTestReadinessEvidenceAssembler(
                evidence_store=SQLiteReadinessEvidenceStore(
                    args.readiness_evidence_database
                ),
                asset_class_store=SQLiteAssetClassApprovalStore(
                    args.asset_class_governance_database
                ),
                maximum_operational_snapshot_age=timedelta(
                    hours=args.maximum_operational_age_hours
                ),
            ).assemble(
                assessed_at=assessed_at,
                baseline_identifier=args.baseline_identifier,
                process_version=args.process_version,
                code_version=args.code_version,
                open_development_items=tuple(args.development_item),
            )
            launch = None
            if args.baseline_identifier and args.process_version:
                launch = SQLitePaperTradingLaunchStore(
                    args.paper_launch_database
                ).latest_ready(
                    baseline_identifier=args.baseline_identifier,
                    process_version=args.process_version,
                    code_version=args.code_version,
                    as_of=assessed_at,
                )
            development_items = list(evidence.open_development_items)
            evidence_identifiers = list(evidence.evidence_identifiers)
            if launch is None:
                development_items.append(
                    "paper_launch_ready: active sustained launch authorization unavailable"
                )
            else:
                launch_identifier = launch.identifier
                evidence_identifiers.extend(
                    (
                        launch.identifier,
                        launch.evidence_identifier,
                        *launch.evidence_identifiers,
                    )
                )
            evidence = replace(
                evidence,
                paper_launch_ready=launch is not None,
                evidence_identifiers=tuple(dict.fromkeys(evidence_identifiers)),
                open_development_items=tuple(dict.fromkeys(development_items)),
            )
        report = ProductTestReadinessEvaluator().evaluate(evidence)
        store = SQLiteProductTestReadinessStore(args.database)
        sequence = store.append(report)
        store.verify_integrity()
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "evidence_source": evidence_source,
                    "error": str(error),
                    "real_money_authorized": False,
                },
                sort_keys=True,
            )
        )
        return 4
    output = report.to_dict()
    output["registry_sequence"] = sequence
    output["evidence_source"] = evidence_source
    output["paper_launch_report_identifier"] = launch_identifier
    output["development_remains_open"] = evidence.development_remains_open
    print(json.dumps(output, indent=2, sort_keys=True))
    if (
        args.require_ready
        and report.state is not ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
