"""Restore and verify a canonical encrypted backup in an isolated drill."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from operations import SQLiteBackupManager, build_canonical_backup_registry
from operations.backup_registry import RETIRED_BACKUP_AUTHORITIES
from operations.recovery_drill import (
    CanonicalRecoveryDrill,
    RecoveryDrillExpectation,
    SQLiteRecoveryDrillStore,
)


def _load(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read recovery expectation {path!r}") from error
    if not isinstance(value, Mapping):
        raise ValueError("recovery expectation must encode an object")
    return value


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--executed-at must be timezone-aware")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--expectation", required=True)
    parser.add_argument("--executed-at")
    parser.add_argument(
        "--report-database",
        default=os.getenv(
            "CAPITAL_INTELLIGENCE_RECOVERY_DRILL_DATABASE",
            "database/recovery_drills.db",
        ),
    )
    parser.add_argument(
        "--backup-directory",
        default=os.getenv("CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY", "backups"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expectation = RecoveryDrillExpectation.from_dict(_load(args.expectation))
        registry = build_canonical_backup_registry()
        key = os.getenv("CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY")
        if not key:
            raise ValueError("encrypted recovery drill requires backup encryption key")
        manager = SQLiteBackupManager(
            registry.sources,
            args.backup_directory,
            encryption_key=key,
            require_encryption=True,
            required_sources=registry.required_logical_names,
            source_metadata=registry.metadata,
            prohibited_sources=tuple(RETIRED_BACKUP_AUTHORITIES),
            baseline_identifier=expectation.baseline_identifier,
            process_version=expectation.process_version,
            code_version=expectation.code_version,
            registry_schema_version=registry.schema_version,
        )
        report = CanonicalRecoveryDrill(manager).run(
            archive=args.archive,
            expectation=expectation,
            executed_at=_timestamp(args.executed_at),
        )
        store = SQLiteRecoveryDrillStore(args.report_database)
        store.append(report)
        store.verify_integrity()
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0 if report.status.value == "passed" else 3
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error": str(error),
                    "production_mutation_count": 0,
                    "paper_test_authorized": False,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
