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
    return SQLiteBackupManager(
        {
            "daily_intelligence": api.snapshot_database,
            "portfolio": api.portfolio_database,
            "investor_memory": api.investor_memory_database,
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
    parser = argparse.ArgumentParser(description="Back up Capital Intelligence data stores.")
    parser.add_argument("--loop", action="store_true", help="Run backups continuously.")
    parser.add_argument("--interval-hours", type=int, default=None)
    args = parser.parse_args()
    operational = OperationalSettings.from_env()
    configure_logging(operational)
    logger = logging.getLogger("capital_intelligence.backup")
    interval = args.interval_hours or operational.backup_interval_hours
    if interval < 1:
        parser.error("--interval-hours must be positive")
    manager = build_manager()
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
