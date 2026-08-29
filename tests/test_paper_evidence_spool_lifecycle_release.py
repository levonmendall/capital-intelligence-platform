from __future__ import annotations

import gc
from datetime import datetime, timezone

import operations.paper_evidence_spool as spool_module
from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


def test_lazy_mapping_lifetime_closes_spool_and_releases_cache(monkeypatch, tmp_path):
    spool = SQLitePaperEvidenceSpool(tmp_path / "paper-evidence-lifetime.db")
    spool.append(
        "bars",
        "SPY",
        [{"timestamp": "2026-08-29T00:00:00+00:00", "close": 650.0}],
        recorded_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
    )
    path = spool.path
    advised = []

    monkeypatch.setattr(spool_module.os, "POSIX_FADV_DONTNEED", 4, raising=False)
    monkeypatch.setattr(spool_module.os, "fsync", lambda _fd: None)
    monkeypatch.setattr(
        spool_module.os,
        "posix_fadvise",
        lambda _fd, _offset, _length, _advice: advised.append(True),
        raising=False,
    )

    payload = {"bars": spool.mapping("bars"), "_evidence_spool": spool}
    del spool
    assert path.exists()

    del payload
    gc.collect()

    assert advised
    assert not path.exists()
