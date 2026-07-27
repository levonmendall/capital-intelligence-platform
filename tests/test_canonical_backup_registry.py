"""Canonical active-authority backup and disaster-recovery tests."""

from __future__ import annotations

import json
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from operations import (
    CANONICAL_BACKUP_AUTHORITIES,
    RETIRED_BACKUP_AUTHORITIES,
    BackupError,
    SQLiteBackupManager,
    build_canonical_backup_registry,
)
from run_backup import build_manager


NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def _database(path: Path, logical_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE authority_state (logical_name TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO authority_state (logical_name, value) VALUES (?, ?)",
            (logical_name, f"state:{logical_name}"),
        )


def _environment(tmp_path: Path, key: bytes) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database"),
        "CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY": str(tmp_path / "backups"),
        "CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY": key.decode("ascii"),
        "CAPITAL_INTELLIGENCE_REQUIRE_ENCRYPTED_BACKUPS": "true",
        "CAPITAL_INTELLIGENCE_BACKUP_RETENTION_DAYS": "30",
        "CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION": "process:test-v1",
        "CAPITAL_INTELLIGENCE_RELEASE": "commit:test",
        "CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER": "baseline:test-1",
    }


def _populate_registry(environ: dict[str, str]) -> None:
    registry = build_canonical_backup_registry(environ)
    for logical_name, path in registry.paths:
        _database(path, logical_name)


def test_registry_covers_active_authorities_and_excludes_retired_names(
    tmp_path: Path,
) -> None:
    registry = build_canonical_backup_registry(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database")}
    )
    logical_names = tuple(item.logical_name for item in CANONICAL_BACKUP_AUTHORITIES)

    assert tuple(registry.sources) == logical_names
    assert set(logical_names).isdisjoint(RETIRED_BACKUP_AUTHORITIES)
    assert {
        "security_master",
        "eligible_universe",
        "full_universe_screening",
        "production_context",
        "institutional_journal",
        "canonical_portfolio",
        "multi_asset_paper_execution",
        "asset_class_governance",
        "asset_specific_evidence",
        "multi_asset_evaluation",
        "canonical_daily_operations",
        "operational_slos",
        "operational_incidents",
        "resilience_exercises",
        "product_readiness_evidence",
        "product_test_readiness",
    }.issubset(logical_names)
    assert registry.to_dict()["retired_authorities_present"] == []


def test_canonical_backup_blocks_when_any_required_authority_is_missing(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    environ = _environment(tmp_path, key)
    registry = build_canonical_backup_registry(environ)
    for logical_name, path in registry.paths[1:]:
        _database(path, logical_name)
    manager = build_manager(environ)

    validation = manager.validate_sources()
    assert validation["status"] == "blocked"
    assert "security_master" in validation["missing_required"]
    with pytest.raises(BackupError, match="required canonical backup authorities"):
        manager.create_backup()


def test_complete_canonical_backup_verifies_and_restores_every_authority(
    tmp_path: Path,
) -> None:
    key = Fernet.generate_key()
    environ = _environment(tmp_path, key)
    _populate_registry(environ)
    manager = build_manager(environ)

    result = manager.create_backup()
    manifest = manager.verify_archive(result.archive)

    assert result.encrypted is True
    assert manifest["schema_version"] == "capital-intelligence-backup.v2"
    assert manifest["baseline_identifier"] == "baseline:test-1"
    assert manifest["process_version"] == "process:test-v1"
    assert manifest["code_version"] == "commit:test"
    assert manifest["registry_schema_version"] == "canonical-backup-registry.v1"
    logical_names = {entry["logical_name"] for entry in manifest["files"]}
    assert logical_names == set(manager.required_sources)
    assert logical_names.isdisjoint(RETIRED_BACKUP_AUTHORITIES)
    assert set(manifest["required_logical_names"]) == logical_names

    restored = manager.restore(result.archive, tmp_path / "restored")
    assert len(restored) == len(logical_names)
    for path in restored:
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT logical_name, value FROM authority_state"
            ).fetchone()
        assert row is not None
        assert row[1] == f"state:{row[0]}"


def test_production_manager_never_accepts_retired_authorities(tmp_path: Path) -> None:
    source = tmp_path / "legacy.db"
    _database(source, "investor_memory")
    with pytest.raises(ValueError, match="prohibited legacy authorities"):
        SQLiteBackupManager(
            {"investor_memory": source},
            tmp_path / "backups",
            required_sources=("investor_memory",),
            prohibited_sources=tuple(RETIRED_BACKUP_AUTHORITIES),
        )


def test_version_two_manifest_rejects_missing_required_entry(tmp_path: Path) -> None:
    key = Fernet.generate_key()
    environ = _environment(tmp_path, key)
    _populate_registry(environ)
    manager = build_manager(environ)
    result = manager.create_backup()

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        plain = root / "archive.tar.gz"
        plain.write_bytes(Fernet(key).decrypt(result.archive.read_bytes()))
        extracted = root / "extracted"
        with tarfile.open(plain, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        manifest_path = extracted / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        removed = manifest["files"].pop()
        manifest["authority_set_sha256"] = "invalid"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        tampered_plain = root / "tampered.tar.gz"
        with tarfile.open(tampered_plain, "w:gz") as archive:
            archive.add(manifest_path, arcname="manifest.json")
            for entry in manifest["files"]:
                archive.add(extracted / entry["filename"], arcname=entry["filename"])
        tampered = root / "tampered.tar.gz.fernet"
        tampered.write_bytes(Fernet(key).encrypt(tampered_plain.read_bytes()))

        with pytest.raises(BackupError, match="missing required canonical authorities"):
            manager.verify_archive(tampered)
        assert removed["logical_name"] in manifest["required_logical_names"]


def test_registry_environment_override_preserves_logical_identity(tmp_path: Path) -> None:
    custom = tmp_path / "custom" / "screening.sqlite"
    registry = build_canonical_backup_registry(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path / "database"),
            "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE": str(custom),
        }
    )

    assert registry.sources["full_universe_screening"] == custom
    assert registry.metadata["full_universe_screening"][
        "environment_variable"
    ] == "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
