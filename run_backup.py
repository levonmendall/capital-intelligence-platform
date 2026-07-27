"""Create encrypted, verified backups of all active canonical authorities."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Mapping, Sequence

from operations import (
    RETIRED_BACKUP_AUTHORITIES,
    BackupError,
    OperationalSettings,
    SQLiteBackupManager,
    build_canonical_backup_registry,
    configure_logging,
)


def build_manager(
    environ: Mapping[str, str] | None = None,
) -> SQLiteBackupManager:
    values = os.environ if environ is None else environ
    operational = OperationalSettings.from_env(values)
    registry = build_canonical_backup_registry(values)
    return SQLiteBackupManager(
        registry.sources,
        operational.backup_directory,
        encryption_key=operational.backup_encryption_key,
        require_encryption=operational.require_encrypted_backups,
        retention_days=operational.backup_retention_days,
        required_sources=registry.required_logical_names,
        source_metadata=registry.metadata,
        prohibited_sources=tuple(sorted(RETIRED_BACKUP_AUTHORITIES)),
        baseline_identifier=values.get(
            "CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER"
        ),
        process_version=values.get(
            "CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION"
        ),
        code_version=(
            values.get("CAPITAL_INTELLIGENCE_RELEASE")
            or values.get("GITHUB_SHA")
            or "unknown"
        ),
        registry_schema_version=registry.schema_version,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back up every active canonical Capital Intelligence authority."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Run backups continuously.",
    )
    mode.add_argument(
        "--healthcheck",
        action="store_true",
        help=(
            "Verify that the newest backup is recent, encrypted when required, "
            "complete, and valid."
        ),
    )
    mode.add_argument(
        "--validate-sources",
        action="store_true",
        help="Validate the complete active authority set without creating an archive.",
    )
    parser.add_argument("--interval-hours", type=int, default=None)
    parser.add_argument("--maximum-age-hours", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    operational = OperationalSettings.from_env()
    configure_logging(operational)
    logger = logging.getLogger("capital_intelligence.backup")
    try:
        manager = build_manager()
    except (TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "classification": "configuration",
                    "error": str(error),
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 4

    if args.validate_sources:
        report = manager.validate_sources()
        report["real_money_authorized"] = False
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["status"] == "valid" else 3

    if args.healthcheck:
        maximum_age_hours = args.maximum_age_hours or max(
            1,
            operational.backup_interval_hours * 2,
        )
        if maximum_age_hours < 1:
            parser.error("--maximum-age-hours must be positive")
        healthy, detail, archive = manager.latest_backup_health(
            maximum_age_seconds=maximum_age_hours * 3600,
        )
        print(
            json.dumps(
                {
                    "status": "healthy" if healthy else "blocked",
                    "detail": detail,
                    "archive": None if archive is None else str(archive),
                    "maximum_age_hours": maximum_age_hours,
                    "real_money_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if healthy else 1

    interval = args.interval_hours or operational.backup_interval_hours
    if interval < 1:
        parser.error("--interval-hours must be positive")
    while True:
        try:
            result = manager.create_backup()
        except (BackupError, OSError, TypeError, ValueError):
            logger.exception("canonical backup failed")
            if not args.loop:
                print(
                    json.dumps(
                        {
                            "status": "blocked",
                            "classification": "backup",
                            "error": "canonical backup failed; see structured logs",
                            "real_money_authorized": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 1
        else:
            logger.info(
                "canonical backup completed",
                extra={
                    "archive": str(result.archive),
                    "encrypted": result.encrypted,
                    "database_count": len(result.manifest["files"]),
                    "schema_version": result.manifest["schema_version"],
                },
            )
            if not args.loop:
                print(
                    json.dumps(
                        {
                            "status": "completed",
                            "archive": str(result.archive),
                            "encrypted": result.encrypted,
                            "database_count": len(result.manifest["files"]),
                            "schema_version": result.manifest["schema_version"],
                            "required_logical_names": result.manifest.get(
                                "required_logical_names",
                                [],
                            ),
                            "baseline_identifier": result.manifest.get(
                                "baseline_identifier"
                            ),
                            "process_version": result.manifest.get(
                                "process_version"
                            ),
                            "code_version": result.manifest.get("code_version"),
                            "real_money_authorized": False,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
        time.sleep(interval * 3600)


if __name__ == "__main__":
    raise SystemExit(main())
