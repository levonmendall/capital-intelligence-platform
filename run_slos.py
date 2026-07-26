"""Assess and record production operational service-level objectives."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from api.config import ApiSettings
from operations import (
    FullUniverseCycleRecord,
    FullUniverseCycleStatus,
    OperationalSettings,
    SQLiteOperationalSLOStore,
    build_operational_slo_service,
    operational_slo_policy_from_settings,
)


def _timestamp(value: str | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _path(value: str | None, *, default: Path) -> Path:
    return default if value is None else Path(value).expanduser()


def _record_cycle(
    args: argparse.Namespace,
    store: SQLiteOperationalSLOStore,
) -> FullUniverseCycleRecord | None:
    if args.cycle_status is None:
        return None
    required = {
        "--cycle-id": args.cycle_id,
        "--scheduled-for": args.scheduled_for,
        "--started-at": args.started_at,
        "--completed-at": args.completed_at,
    }
    missing = tuple(flag for flag, value in required.items() if value is None)
    if missing:
        raise ValueError(
            "recording a cycle requires " + ", ".join(missing)
        )
    status = FullUniverseCycleStatus(args.cycle_status)
    if status is FullUniverseCycleStatus.COMPLETED:
        completed_required = {
            "--catalog-id": args.catalog_id,
            "--universe-snapshot-id": args.universe_snapshot_id,
        }
        missing = tuple(
            flag for flag, value in completed_required.items() if value is None
        )
        if missing:
            raise ValueError(
                "a completed cycle requires " + ", ".join(missing)
            )
    record = FullUniverseCycleRecord(
        identifier=args.cycle_id,
        scheduled_for=_timestamp(
            args.scheduled_for,
            field_name="scheduled_for",
        ),
        started_at=_timestamp(args.started_at, field_name="started_at"),
        completed_at=_timestamp(args.completed_at, field_name="completed_at"),
        status=status,
        security_master_catalog_identifier=args.catalog_id,
        universe_snapshot_identifier=args.universe_snapshot_id,
        eligible_instrument_count=args.eligible_count,
        screened_instrument_count=args.screened_count,
        qualified_candidate_count=args.qualified_count,
        error=args.error,
        recorded_at=_timestamp(args.recorded_at, field_name="recorded_at"),
    )
    store.append_cycle(record)
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Assess provider freshness, full-universe completion, thesis review, "
            "and point-in-time evaluation SLOs. The command never creates an "
            "investment recommendation or upgrades incomplete data."
        )
    )
    parser.add_argument("--database", help="Override the operational SLO database.")
    parser.add_argument(
        "--security-master-database",
        help="Override the security-master operations database.",
    )
    parser.add_argument(
        "--journal-database",
        help="Override the canonical CIO journal database.",
    )
    parser.add_argument(
        "--evaluated-at",
        help="Point-in-time assessment timestamp in ISO-8601 form.",
    )
    parser.add_argument(
        "--record-assessment",
        action="store_true",
        help="Append the assessment to the tamper-evident SLO history.",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit nonzero when any required SLO is blocked or breached.",
    )
    parser.add_argument(
        "--cycle-status",
        choices=[item.value for item in FullUniverseCycleStatus],
        help="Append one terminal full-universe cycle record before assessment.",
    )
    parser.add_argument("--cycle-id")
    parser.add_argument("--scheduled-for")
    parser.add_argument("--started-at")
    parser.add_argument("--completed-at")
    parser.add_argument("--recorded-at")
    parser.add_argument("--catalog-id")
    parser.add_argument("--universe-snapshot-id")
    parser.add_argument("--eligible-count", type=int, default=0)
    parser.add_argument("--screened-count", type=int, default=0)
    parser.add_argument("--qualified-count", type=int, default=0)
    parser.add_argument("--error")
    args = parser.parse_args(argv)

    api_settings = ApiSettings.from_env()
    operational = OperationalSettings.from_env()
    slo_path = _path(args.database, default=operational.operational_slo_database)
    security_master_path = _path(
        args.security_master_database,
        default=operational.security_master_database,
    )
    journal_path = _path(
        args.journal_database,
        default=api_settings.journal_database,
    )
    needs_write = args.record_assessment or args.cycle_status is not None
    service = build_operational_slo_service(
        security_master_database=security_master_path,
        journal_database=journal_path,
        slo_database=slo_path,
        policy=operational_slo_policy_from_settings(operational),
        initialize_store=needs_write,
    )
    try:
        cycle = _record_cycle(args, service.store)
        evaluated_at = _timestamp(args.evaluated_at, field_name="evaluated_at")
    except ValueError as error:
        parser.error(str(error))
    snapshot = service.assess(
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        record=args.record_assessment,
    )
    payload = snapshot.to_dict()
    if cycle is not None:
        payload["recorded_cycle"] = cycle.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    enforce = args.require_ready or operational.require_operational_slos
    return 0 if snapshot.ready or not enforce else 3


if __name__ == "__main__":
    raise SystemExit(main())
