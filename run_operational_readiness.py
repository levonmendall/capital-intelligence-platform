"""Assemble and persist operational readiness from canonical runtime stores."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from governance import SQLiteReadinessEvidenceStore
from operations import (
    SQLiteCanonicalDailyOperationsStore,
    SQLiteOperationalIncidentStore,
    SQLiteOperationalSLOStore,
    SQLiteResilienceExerciseStore,
)
from operations.readiness import (
    OperationalReadinessAssembler,
    OperationalReadinessAssemblyPolicy,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--assessed-at must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-identifier", required=True)
    parser.add_argument(
        "--process-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION"),
    )
    parser.add_argument(
        "--code-version",
        default=os.getenv("CAPITAL_INTELLIGENCE_RELEASE"),
    )
    parser.add_argument("--assessed-at")
    parser.add_argument(
        "--daily-operations-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_DAILY_OPERATION_DATABASE",
            str(data_dir / "canonical_daily_operations.db"),
        ),
    )
    parser.add_argument(
        "--slo-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_OPERATIONAL_SLO_DATABASE",
            str(data_dir / "operational_slos.db"),
        ),
    )
    parser.add_argument(
        "--resilience-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_RESILIENCE_DATABASE",
            str(data_dir / "resilience_exercises.db"),
        ),
    )
    parser.add_argument(
        "--incident-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_OPERATIONAL_INCIDENT_DATABASE",
            str(data_dir / "operational_incidents.db"),
        ),
    )
    parser.add_argument(
        "--readiness-evidence-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_PRODUCT_READINESS_EVIDENCE_DATABASE",
            str(data_dir / "product_readiness_evidence.db"),
        ),
    )
    parser.add_argument("--maximum-daily-age-hours", type=float, default=24.0)
    parser.add_argument("--maximum-slo-age-hours", type=float, default=24.0)
    parser.add_argument("--maximum-resilience-age-days", type=float, default=30.0)
    parser.add_argument("--require-clean", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.process_version:
            raise ValueError(
                "--process-version or CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION is required"
            )
        if not args.code_version:
            raise ValueError(
                "--code-version or CAPITAL_INTELLIGENCE_RELEASE is required"
            )
        for name in (
            "maximum_daily_age_hours",
            "maximum_slo_age_hours",
            "maximum_resilience_age_days",
        ):
            if getattr(args, name) <= 0:
                raise ValueError(f"--{name.replace('_', '-')} must be positive")
        result = OperationalReadinessAssembler(
            daily_store=SQLiteCanonicalDailyOperationsStore(
                args.daily_operations_database
            ),
            slo_store=SQLiteOperationalSLOStore(args.slo_database),
            resilience_store=SQLiteResilienceExerciseStore(
                args.resilience_database
            ),
            incident_store=SQLiteOperationalIncidentStore(
                args.incident_database
            ),
            readiness_store=SQLiteReadinessEvidenceStore(
                args.readiness_evidence_database
            ),
            policy=OperationalReadinessAssemblyPolicy(
                maximum_daily_operation_age=timedelta(
                    hours=args.maximum_daily_age_hours
                ),
                maximum_slo_age=timedelta(hours=args.maximum_slo_age_hours),
                maximum_resilience_report_age=timedelta(
                    days=args.maximum_resilience_age_days
                ),
            ),
        ).assemble(
            assessed_at=_timestamp(args.assessed_at),
            baseline_identifier=args.baseline_identifier,
            process_version=args.process_version,
            code_version=args.code_version,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, sort_keys=True))
        return 4
    payload = result.to_dict()
    payload["status"] = "clean" if not result.blockers else "blocked"
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.require_clean and result.blockers:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
