"""Create encrypted, verified backups of Capital Intelligence SQLite stores."""

from __future__ import annotations

import argparse
import logging
import time

from api.config import ApiSettings
from operations import OperationalSettings, SQLiteBackupManager, configure_logging


def build_manager() -> SQLiteBackupManager:
    api = ApiSettings.from_env()
    operations = OperationalSettings.from_env()
    alert_path = api.alert_database or api.snapshot_database.with_name("alerts.db")
    policy_path = api.investor_memory_database.with_name("investment_policy.db")
    analytical_path = api.snapshot_database.with_name("analytical_engines.db")
    return SQLiteBackupManager(
        {
            "daily_intelligence": api.snapshot_database,
            "analytical_engines": analytical_path,
            "canonical_portfolio": api.portfolio_database,
            "investor_memory": api.investor_memory_database,
            "investment_policy": policy_path,
            "identity": api.identity_database,
            "alerts": alert_path,
            "institutional_journal": api.journal_database,
        },
        operations.backup_directory,
        encryption_key=operations.backup_encryption_key,
        require_encryption=operations.require_encrypted_backups,
        retention_days=operations.backup_retention_days,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Back up Capital Intelligence data stores."
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
        help="Verify that the newest backup is recent, encrypted when required, and valid.",
    )
    parser.add_argument("--interval-hours", type=int, default=None)
    parser.add_argument("--maximum-age-hours", type=int, default=None)
    args = parser.parse_args()
    operational = OperationalSettings.from_env()
    configure_logging(operational)
    logger = logging.getLogger("capital_intelligence.backup")
    manager = build_manager()

    if args.healthcheck:
        maximum_age_hours = args.maximum_age_hours or max(
            1,
            operational.backup_interval_hours * 2,
        )
        if maximum_age_hours < 1:
            parser.error("--maximum-age-hours must be positive")
        healthy, detail, _ = manager.latest_backup_health(
            maximum_age_seconds=maximum_age_hours * 3600,
        )
        print(detail)
        return 0 if healthy else 1

    interval = args.interval_hours or operational.backup_interval_hours
    if interval < 1:
        parser.error("--interval-hours must be positive")
    while True:
        try:
            result = manager.create_backup()
        except Exception:
            logger.exception("backup failed")
            if not args.loop:
                return 1
        else:
            logger.info(
                "backup completed",
                extra={
                    "archive": str(result.archive),
                    "encrypted": result.encrypted,
                    "database_count": len(result.manifest["files"]),
                },
            )
            if not args.loop:
                print(result.archive)
                return 0
        time.sleep(interval * 3600)


if __name__ == "__main__":
    raise SystemExit(main())
