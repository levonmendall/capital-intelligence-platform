from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import operations.paper_evidence_spool as spool_module
from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


def _spool(tmp_path: Path) -> SQLitePaperEvidenceSpool:
    spool = SQLitePaperEvidenceSpool(tmp_path / "paper-evidence.db")
    spool.append(
        "bars",
        "SPY",
        [{"timestamp": "2026-08-29T00:00:00+00:00", "close": 650.0}],
        recorded_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )
    return spool


def test_close_releases_exact_spool_cache_before_unlink(monkeypatch, tmp_path):
    spool = _spool(tmp_path)
    path = spool.path
    advised_paths: list[Path] = []

    monkeypatch.setattr(spool_module.os, "POSIX_FADV_DONTNEED", 4, raising=False)

    def fake_fsync(fd: int) -> None:
        assert path.exists()

    def fake_fadvise(fd: int, offset: int, length: int, advice: int) -> None:
        assert offset == 0
        assert length == 0
        assert advice == 4
        resolved = Path(os.readlink(f"/proc/self/fd/{fd}"))
        advised_paths.append(resolved)
        assert path.exists()

    monkeypatch.setattr(spool_module.os, "fsync", fake_fsync)
    monkeypatch.setattr(spool_module.os, "posix_fadvise", fake_fadvise, raising=False)

    spool.close(remove=True)

    assert advised_paths == [path]
    assert not path.exists()


def test_close_remains_fail_soft_when_cache_advice_fails(monkeypatch, tmp_path):
    spool = _spool(tmp_path)
    path = spool.path

    monkeypatch.setattr(spool_module.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    monkeypatch.setattr(spool_module.os, "fsync", lambda _fd: None)

    def fail_fadvise(_fd: int, _offset: int, _length: int, _advice: int) -> None:
        raise OSError("cache advice unavailable")

    monkeypatch.setattr(spool_module.os, "posix_fadvise", fail_fadvise, raising=False)

    spool.close(remove=True)

    assert not path.exists()


def test_close_reclaims_sidecars_before_removal(monkeypatch, tmp_path):
    spool = _spool(tmp_path)
    wal = Path(str(spool.path) + "-wal")
    shm = Path(str(spool.path) + "-shm")
    wal.write_bytes(b"wal-cache")
    shm.write_bytes(b"shm-cache")
    advised: list[Path] = []

    monkeypatch.setattr(spool_module.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    monkeypatch.setattr(spool_module.os, "fsync", lambda _fd: None)

    def fake_fadvise(fd: int, _offset: int, _length: int, _advice: int) -> None:
        advised.append(Path(os.readlink(f"/proc/self/fd/{fd}")))

    monkeypatch.setattr(spool_module.os, "posix_fadvise", fake_fadvise, raising=False)

    spool.close(remove=True)

    assert spool.path in advised
    assert wal in advised
    assert shm in advised
    assert not spool.path.exists()
    assert not wal.exists()
    assert not shm.exists()
