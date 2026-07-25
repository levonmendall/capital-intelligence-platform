"""Verify or restore a Capital Intelligence backup archive."""

from __future__ import annotations

import argparse

from operations import OperationalSettings, SQLiteBackupManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or restore a backup archive.")
    parser.add_argument("archive")
    parser.add_argument("--target", default="restored-database")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    settings = OperationalSettings.from_env()
    manager = SQLiteBackupManager(
        {},
        settings.backup_directory,
        encryption_key=settings.backup_encryption_key,
        require_encryption=settings.require_encrypted_backups,
        retention_days=settings.backup_retention_days,
    )
    if args.verify_only:
        manifest = manager.verify_archive(args.archive)
        print(f"verified {len(manifest['files'])} database files")
        return 0
    restored = manager.restore(args.archive, args.target, overwrite=args.overwrite)
    for path in restored:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
