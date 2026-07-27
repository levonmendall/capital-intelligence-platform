"""Encrypted backup restore and decision-lineage reconstruction tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from operations import SQLiteBackupManager
from operations.recovery_drill import (
    CanonicalRecoveryDrill,
    RecoveryDrillExpectation,
    RecoveryDrillStatus,
    RecoveryLineageProbe,
    SQLiteRecoveryDrillStore,
)

UTC = timezone.utc
BACKUP_TIME = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _database(path: Path, table: str, column: str, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            f'CREATE TABLE "{table}" ("{column}" TEXT NOT NULL)'
        )
        connection.execute(
            f'INSERT INTO "{table}" ("{column}") VALUES (?)',
            (value,),
        )


def _manager(tmp_path: Path):
    journal = tmp_path / "journal.db"
    portfolio = tmp_path / "portfolio.db"
    execution = tmp_path / "execution.db"
    _database(journal, "decision_events", "decision_identifier", "decision:1")
    _database(portfolio, "portfolio_events", "snapshot_identifier", "portfolio:1")
    _database(execution, "execution_events", "decision_identifier", "decision:1")
    key = Fernet.generate_key()
    manager = SQLiteBackupManager(
        {
            "institutional_journal": journal,
            "canonical_portfolio": portfolio,
            "multi_asset_paper_execution": execution,
        },
        tmp_path / "backups",
        encryption_key=key,
        require_encryption=True,
        required_sources=(
            "institutional_journal",
            "canonical_portfolio",
            "multi_asset_paper_execution",
        ),
        source_metadata={
            "institutional_journal": {"category": "decision"},
            "canonical_portfolio": {"category": "portfolio"},
            "multi_asset_paper_execution": {"category": "execution"},
        },
        prohibited_sources=("investor_memory", "weighted_committee"),
        baseline_identifier="paper-baseline:alpha-1",
        process_version="process:alpha-1",
        code_version="commit:alpha-1",
        registry_schema_version="canonical-backup-registry.v1",
        clock=lambda: BACKUP_TIME,
    )
    return manager


def _expectation(*, bad_probe: bool = False) -> RecoveryDrillExpectation:
    return RecoveryDrillExpectation(
        identifier="recovery-expectation:alpha-1",
        baseline_identifier="paper-baseline:alpha-1",
        process_version="process:alpha-1",
        code_version="commit:alpha-1",
        required_authorities=(
            "institutional_journal",
            "canonical_portfolio",
            "multi_asset_paper_execution",
        ),
        lineage_probes=(
            RecoveryLineageProbe(
                "institutional_journal",
                "decision_events",
                "decision_identifier",
                "decision:missing" if bad_probe else "decision:1",
            ),
            RecoveryLineageProbe(
                "canonical_portfolio",
                "portfolio_events",
                "snapshot_identifier",
                "portfolio:1",
            ),
            RecoveryLineageProbe(
                "multi_asset_paper_execution",
                "execution_events",
                "decision_identifier",
                "decision:1",
            ),
        ),
        maximum_recovery_seconds=30,
        maximum_data_loss_seconds=60,
    )


def test_encrypted_recovery_restores_and_reconstructs_lineage(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    backup = manager.create_backup()

    report = CanonicalRecoveryDrill(manager).run(
        archive=backup.archive,
        expectation=_expectation(),
        executed_at=BACKUP_TIME + timedelta(seconds=30),
    )

    assert backup.encrypted is True
    assert report.status is RecoveryDrillStatus.PASSED
    assert set(report.restored_authorities) == {
        "institutional_journal",
        "canonical_portfolio",
        "multi_asset_paper_execution",
    }
    assert report.integrity_verified_authorities == report.restored_authorities
    assert len(report.passed_probe_identifiers) == 3
    assert report.failed_probe_identifiers == ()
    assert report.production_mutation_count == 0
    assert report.paper_test_authorized is False
    assert report.to_dict()["real_money_authorized"] is False


def test_missing_lineage_or_manifest_mismatch_fails_closed(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    backup = manager.create_backup()

    missing = CanonicalRecoveryDrill(manager).run(
        archive=backup.archive,
        expectation=_expectation(bad_probe=True),
        executed_at=BACKUP_TIME + timedelta(seconds=30),
    )
    assert missing.status is RecoveryDrillStatus.FAILED
    assert len(missing.failed_probe_identifiers) == 1
    assert any("lineage probes" in item for item in missing.blockers)

    mismatched = RecoveryDrillExpectation.from_dict(
        {
            **_expectation().to_dict(),
            "identifier": "recovery-expectation:mismatched",
            "code_version": "commit:changed",
        }
    )
    result = CanonicalRecoveryDrill(manager).run(
        archive=backup.archive,
        expectation=mismatched,
        executed_at=BACKUP_TIME + timedelta(seconds=30),
    )
    assert result.status is RecoveryDrillStatus.FAILED
    assert any("code_version" in item for item in result.blockers)


def test_recovery_objectives_are_enforced(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    backup = manager.create_backup()
    expectation = RecoveryDrillExpectation.from_dict(
        {
            **_expectation().to_dict(),
            "identifier": "recovery-expectation:rpo-zero",
            "maximum_data_loss_seconds": 0,
        }
    )

    report = CanonicalRecoveryDrill(manager).run(
        archive=backup.archive,
        expectation=expectation,
        executed_at=BACKUP_TIME + timedelta(seconds=1),
    )

    assert report.status is RecoveryDrillStatus.FAILED
    assert report.data_loss_seconds == 1
    assert any("recovery-point" in item for item in report.blockers)


def test_recovery_reports_are_append_only(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    backup = manager.create_backup()
    report = CanonicalRecoveryDrill(manager).run(
        archive=backup.archive,
        expectation=_expectation(),
        executed_at=BACKUP_TIME + timedelta(seconds=30),
    )
    store = SQLiteRecoveryDrillStore(tmp_path / "recovery-reports.db")

    assert store.append(report) == 1
    assert store.append(report) == 1
    assert store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM canonical_recovery_drill_reports")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE canonical_recovery_drill_reports SET payload_json='{}'"
            )
