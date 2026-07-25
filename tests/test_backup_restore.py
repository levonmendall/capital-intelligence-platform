"""Backup, encryption, checksum, and restore contract tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet

from operations import BackupError, SQLiteBackupManager


def _database(path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE values_table (value TEXT NOT NULL)")
        connection.execute("INSERT INTO values_table (value) VALUES (?)", (value,))


def test_encrypted_backup_verifies_and_restores(tmp_path) -> None:
    source = tmp_path / "source.db"
    _database(source, "governed")
    key = Fernet.generate_key()
    manager = SQLiteBackupManager(
        {"identity": source},
        tmp_path / "backups",
        encryption_key=key,
        require_encryption=True,
        clock=lambda: datetime(2026, 7, 25, 12, tzinfo=timezone.utc),
    )

    result = manager.create_backup()
    assert result.encrypted
    assert result.archive.suffix == ".fernet"
    assert manager.verify_archive(result.archive)["schema_version"] == (
        "capital-intelligence-backup.v1"
    )

    restored = manager.restore(result.archive, tmp_path / "restore")
    assert len(restored) == 1
    with sqlite3.connect(restored[0]) as connection:
        assert connection.execute("SELECT value FROM values_table").fetchone()[0] == "governed"


def test_tampered_encrypted_backup_is_rejected(tmp_path) -> None:
    source = tmp_path / "source.db"
    _database(source, "value")
    key = Fernet.generate_key()
    manager = SQLiteBackupManager(
        {"snapshot": source},
        tmp_path / "backups",
        encryption_key=key,
        require_encryption=True,
    )
    result = manager.create_backup()
    payload = bytearray(result.archive.read_bytes())
    payload[-1] ^= 1
    result.archive.write_bytes(payload)

    with pytest.raises(BackupError, match="decryption|authentication"):
        manager.verify_archive(result.archive)


def test_backup_requires_at_least_one_available_database(tmp_path) -> None:
    manager = SQLiteBackupManager(
        {"missing": tmp_path / "missing.db"},
        tmp_path / "backups",
    )
    with pytest.raises(BackupError, match="no SQLite databases"):
        manager.create_backup()
