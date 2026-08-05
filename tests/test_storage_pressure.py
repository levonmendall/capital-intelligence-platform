from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from operations import storage_pressure


def _archive(path: Path, *, age: int) -> Path:
    path.write_bytes(b"backup")
    os.utime(path, ns=(age, age))
    return path


def test_pressure_recovery_removes_only_oldest_backups(monkeypatch, tmp_path) -> None:
    state_root = tmp_path / "state"
    backup_root = state_root / "backups"
    backup_root.mkdir(parents=True)
    canonical = state_root / "portfolio.db"
    canonical.write_bytes(b"canonical")
    temporary = backup_root / "capital-intelligence-interrupted.tmp"
    temporary.write_bytes(b"partial")
    oldest = _archive(
        backup_root / "capital-intelligence-20260801T000000Z.tar.gz.fernet",
        age=1,
    )
    middle = _archive(
        backup_root / "capital-intelligence-20260802T000000Z.tar.gz.fernet",
        age=2,
    )
    newest = _archive(
        backup_root / "capital-intelligence-20260803T000000Z.tar.gz.fernet",
        age=3,
    )

    def disk_usage(_path):
        archive_count = sum(
            1 for _ in backup_root.glob("capital-intelligence-*.tar.gz*")
        )
        free = 100 + (3 - archive_count) * 500
        return SimpleNamespace(total=5_000, used=5_000 - free, free=free)

    monkeypatch.setattr(storage_pressure.shutil, "disk_usage", disk_usage)

    report = storage_pressure.reclaim_backup_space(
        state_root=state_root,
        backup_directory=backup_root,
        reserve_bytes=1_000,
        minimum_archives=1,
    )

    assert report.reserve_satisfied is True
    assert report.removed_archives == (oldest.name, middle.name)
    assert report.removed_temporary_files == (temporary.name,)
    assert newest.exists()
    assert canonical.read_bytes() == b"canonical"
    assert report.to_dict()["canonical_authorities_deleted"] is False


def test_pressure_recovery_preserves_all_backups_when_reserve_exists(
    monkeypatch,
    tmp_path,
) -> None:
    state_root = tmp_path / "state"
    backup_root = state_root / "backups"
    backup_root.mkdir(parents=True)
    archive = _archive(
        backup_root / "capital-intelligence-20260803T000000Z.tar.gz.fernet",
        age=3,
    )
    monkeypatch.setattr(
        storage_pressure.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=5_000, used=3_000, free=2_000),
    )

    report = storage_pressure.reclaim_backup_space(
        state_root=state_root,
        backup_directory=backup_root,
        reserve_bytes=1_000,
    )

    assert report.recovered is False
    assert archive.exists()
    assert report.free_bytes_before == 2_000
    assert report.free_bytes_after == 2_000


def test_recovery_removes_only_cycle_local_spool_files(monkeypatch, tmp_path) -> None:
    state_root = tmp_path / "state"
    backup_root = state_root / "backups"
    spool_root = state_root / "paper_evidence_spool"
    backup_root.mkdir(parents=True)
    spool_root.mkdir(parents=True)
    disposable = spool_root / "paper-evidence-cycle.db"
    disposable_journal = spool_root / "paper-evidence-cycle.db-journal"
    protected = spool_root / "portfolio.db"
    disposable.write_bytes(b"temporary-evidence")
    disposable_journal.write_bytes(b"temporary-journal")
    protected.write_bytes(b"canonical")
    monkeypatch.setattr(
        storage_pressure.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10_000, used=5_000, free=5_000),
    )

    report = storage_pressure.reclaim_backup_space(
        state_root=state_root,
        backup_directory=backup_root,
        reserve_bytes=1_000,
        disposable_spool_directories=(spool_root,),
    )

    assert not disposable.exists()
    assert not disposable_journal.exists()
    assert protected.read_bytes() == b"canonical"
    assert report.removed_evidence_spool_bytes == len(b"temporary-evidence") + len(
        b"temporary-journal"
    )
    assert set(report.removed_evidence_spool_files) == {
        str(disposable),
        str(disposable_journal),
    }
    assert report.to_dict()["canonical_authorities_deleted"] is False


def test_environment_policy_uses_configured_reserve(monkeypatch, tmp_path) -> None:
    captured = {}

    def reclaim(**kwargs):
        captured.update(kwargs)
        return "report"

    monkeypatch.setattr(storage_pressure, "reclaim_backup_space", reclaim)
    configured_spool = tmp_path / "transient-spool"
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY": str(tmp_path / "archives"),
        "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB": "1024",
        "CAPITAL_INTELLIGENCE_BACKUP_MINIMUM_ARCHIVES": "1",
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR": str(configured_spool),
    }

    assert storage_pressure.reclaim_from_environment(values) == "report"
    assert captured == {
        "state_root": tmp_path,
        "backup_directory": tmp_path / "archives",
        "reserve_bytes": 1024 * 1024 * 1024,
        "minimum_archives": 1,
        "disposable_spool_directories": (
            tmp_path / "paper_evidence_spool",
            configured_spool,
        ),
    }
