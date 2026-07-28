"""Freeze a test process, assemble eligibility, and record human entry decisions."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from governance.paper_test_entry import (
    ControlledPaperTestEligibilityPackage,
    ControlledPaperTestEntryDecision,
    InvestmentProcessFreeze,
    PaperTestEntryGovernanceError,
    PaperTestEntryPackageAssembler,
    SQLitePaperTestEntryGovernanceStore,
)
from governance.product_readiness import (
    ProductTestReadiness,
    ProductTestReadinessReport,
)
from governance.stage_binding_approval import SQLiteStageBindingApprovalStore
from operations.paper_test_campaign import SQLitePaperTestCampaignStore
from operations.recovery_drill import (
    RecoveryDrillReport,
    RecoveryDrillStatus,
    SQLiteRecoveryDrillStore,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return result


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read governance JSON {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("governance JSON must encode an object")
    return value


def _latest_readiness(
    path: str | Path,
    *,
    baseline_identifier: str,
) -> ProductTestReadinessReport | None:
    database = Path(path).expanduser()
    if not database.is_file():
        return None
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT payload_json FROM product_test_readiness_reports "
            "ORDER BY sequence DESC"
        ).fetchone()
    if row is None:
        return None
    value = json.loads(str(row[0]))
    report = ProductTestReadinessReport(
        identifier=str(value["identifier"]),
        assessed_at=datetime.fromisoformat(str(value["assessed_at"])),
        state=ProductTestReadiness(str(value["state"])),
        baseline_identifier=(
            None
            if value.get("baseline_identifier") is None
            else str(value["baseline_identifier"])
        ),
        process_version=(
            None
            if value.get("process_version") is None
            else str(value["process_version"])
        ),
        blockers=tuple(str(item) for item in value.get("blockers", ())),
        development_items=tuple(
            str(item) for item in value.get("development_items", ())
        ),
        evidence_identifiers=tuple(
            str(item) for item in value.get("evidence_identifiers", ())
        ),
        real_money_authorized=bool(value.get("real_money_authorized", False)),
        performance_claims_permitted=bool(
            value.get("performance_claims_permitted", False)
        ),
    )
    return report if report.baseline_identifier == baseline_identifier else None


def _latest_recovery(
    store: SQLiteRecoveryDrillStore,
    *,
    baseline_identifier: str,
) -> RecoveryDrillReport | None:
    store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT payload_json FROM canonical_recovery_drill_reports "
            "ORDER BY sequence DESC"
        ).fetchone()
    if row is None:
        return None
    value = json.loads(str(row[0]))
    report = RecoveryDrillReport(
        identifier=str(value["identifier"]),
        expectation_identifier=str(value["expectation_identifier"]),
        archive_identifier=str(value["archive_identifier"]),
        executed_at=datetime.fromisoformat(str(value["executed_at"])),
        status=RecoveryDrillStatus(str(value["status"])),
        baseline_identifier=str(value["baseline_identifier"]),
        process_version=str(value["process_version"]),
        code_version=str(value["code_version"]),
        restored_authorities=tuple(
            str(item) for item in value.get("restored_authorities", ())
        ),
        integrity_verified_authorities=tuple(
            str(item)
            for item in value.get("integrity_verified_authorities", ())
        ),
        passed_probe_identifiers=tuple(
            str(item) for item in value.get("passed_probe_identifiers", ())
        ),
        failed_probe_identifiers=tuple(
            str(item) for item in value.get("failed_probe_identifiers", ())
        ),
        recovery_seconds=int(value["recovery_seconds"]),
        data_loss_seconds=int(value["data_loss_seconds"]),
        production_mutation_count=int(value["production_mutation_count"]),
        blockers=tuple(str(item) for item in value.get("blockers", ())),
        evidence_identifiers=tuple(
            str(item) for item in value.get("evidence_identifiers", ())
        ),
        schema_version=str(
            value.get("schema_version", "canonical-recovery-drill-report.v1")
        ),
    )
    return report if report.baseline_identifier == baseline_identifier else None


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--record-freeze")
    action.add_argument("--assemble-package", action="store_true")
    action.add_argument("--record-decision")
    action.add_argument("--status", action="store_true")
    parser.add_argument("--baseline-identifier")
    parser.add_argument("--as-of")
    parser.add_argument(
        "--governance-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE",
            str(data_dir / "paper_test_governance.db"),
        ),
    )
    parser.add_argument(
        "--readiness-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_TEST_READINESS_DATABASE",
            str(data_dir / "product_test_readiness.db"),
        ),
    )
    parser.add_argument(
        "--campaign-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PAPER_TEST_CAMPAIGN_DATABASE",
            str(data_dir / "paper_test_campaign.db"),
        ),
    )
    parser.add_argument(
        "--recovery-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_RECOVERY_DRILL_DATABASE",
            str(data_dir / "recovery_drills.db"),
        ),
    )
    parser.add_argument(
        "--stage-binding-approval-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_STAGE_BINDING_APPROVAL_DATABASE",
            str(data_dir / "stage_binding_approvals.db"),
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SQLitePaperTestEntryGovernanceStore(args.governance_database)
    try:
        if args.record_freeze:
            value = InvestmentProcessFreeze.from_dict(_load(args.record_freeze))
            sequence = store.append_freeze(value)
            print(
                json.dumps(
                    {"sequence": sequence, "process_freeze": value.to_dict()},
                    sort_keys=True,
                )
            )
            return 0

        baseline_identifier = args.baseline_identifier
        if not baseline_identifier:
            parser.error("--baseline-identifier is required for this action")
        timestamp = _timestamp(args.as_of)

        if args.assemble_package:
            freezes = store.freezes(baseline_identifier)
            if not freezes:
                raise PaperTestEntryGovernanceError(
                    "investment-process freeze is unavailable"
                )
            freeze = freezes[-1]
            readiness = _latest_readiness(
                args.readiness_database,
                baseline_identifier=baseline_identifier,
            )
            if readiness is None:
                raise PaperTestEntryGovernanceError(
                    "matching product-test readiness report is unavailable"
                )
            campaign_store = SQLitePaperTestCampaignStore(args.campaign_database)
            campaign_store.verify_integrity()
            baseline = campaign_store.baseline(baseline_identifier)
            reports = campaign_store.reports(baseline_identifier)
            if baseline is None or not reports:
                raise PaperTestEntryGovernanceError(
                    "matching paper-test campaign evidence is unavailable"
                )
            recovery = _latest_recovery(
                SQLiteRecoveryDrillStore(args.recovery_database),
                baseline_identifier=baseline_identifier,
            )
            if recovery is None:
                raise PaperTestEntryGovernanceError(
                    "matching recovery-drill report is unavailable"
                )
            binding_store = SQLiteStageBindingApprovalStore(
                args.stage_binding_approval_database
            )
            binding_store.verify_integrity()
            binding = binding_store.active(
                freeze.stage_bindings_sha256,
                evaluated_at=timestamp,
            )
            if binding is None:
                raise PaperTestEntryGovernanceError(
                    "active matching stage-binding approval is unavailable"
                )
            package = PaperTestEntryPackageAssembler().assemble(
                freeze=freeze,
                readiness=readiness,
                baseline=baseline,
                campaign=reports[-1],
                recovery=recovery,
                stage_binding_approval=binding,
                assembled_at=timestamp,
            )
            sequence = store.append_package(package)
            print(
                json.dumps(
                    {"sequence": sequence, "eligibility_package": package.to_dict()},
                    sort_keys=True,
                )
            )
            return 0 if not package.blockers else 3

        if args.record_decision:
            decision = ControlledPaperTestEntryDecision.from_dict(
                _load(args.record_decision)
            )
            packages = store.packages(baseline_identifier)
            package = next(
                (
                    item
                    for item in reversed(packages)
                    if item.identifier == decision.package_identifier
                ),
                None,
            )
            if package is None:
                raise PaperTestEntryGovernanceError(
                    "referenced eligibility package is unavailable"
                )
            sequence = store.append_decision(decision, package=package)
            print(
                json.dumps(
                    {"sequence": sequence, "entry_decision": decision.to_dict()},
                    sort_keys=True,
                )
            )
            return 0

        freezes = store.freezes(baseline_identifier)
        packages = store.packages(baseline_identifier)
        decisions = store.decisions(baseline_identifier)
        active_decision = (
            decisions[-1]
            if decisions and decisions[-1].active_at(timestamp)
            else None
        )
        print(
            json.dumps(
                {
                    "baseline_identifier": baseline_identifier,
                    "process_freeze": None if not freezes else freezes[-1].to_dict(),
                    "eligibility_package": (
                        None if not packages else packages[-1].to_dict()
                    ),
                    "latest_entry_decision": (
                        None if not decisions else decisions[-1].to_dict()
                    ),
                    "active_controlled_paper_test_decision": (
                        None if active_decision is None else active_decision.to_dict()
                    ),
                    "development_open": True,
                    "real_money_authorized": False,
                    "performance_claims_permitted": False,
                },
                sort_keys=True,
            )
        )
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
        PaperTestEntryGovernanceError,
    ) as error:
        print(
            json.dumps(
                {"status": "blocked", "error": str(error)},
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
