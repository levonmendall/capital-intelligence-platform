"""Regression coverage for transient compressed paper-evidence spools."""

from __future__ import annotations

import errno
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from operations import paper_evidence_spool
from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


AS_OF = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)


def test_default_spool_location_is_transient(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", raising=False)
    monkeypatch.setattr(paper_evidence_spool.tempfile, "gettempdir", lambda: str(tmp_path))

    spool = SQLitePaperEvidenceSpool.create(
        universe_identifier="universe:test",
        as_of=AS_OF,
    )

    assert spool.path.parent == tmp_path / "capital-intelligence" / "paper_evidence_spool"
    assert "database" not in spool.path.parts
    spool.close(remove=True)


def test_spool_payload_is_compressed_and_round_trips(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_RESERVE_MB", "64")
    payload = tuple(
        {"symbol": "AAA", "description": "repetitive-governed-evidence" * 100}
        for _ in range(500)
    )
    spool = SQLitePaperEvidenceSpool(tmp_path / "compressed.db")
    spool.append("bars", "AAA", payload, recorded_at=AS_OF)

    with sqlite3.connect(spool.path) as connection:
        compressed_bytes, uncompressed_bytes, encoding = connection.execute(
            "SELECT length(payload_blob), uncompressed_bytes, payload_encoding "
            "FROM evidence_entries"
        ).fetchone()

    assert compressed_bytes < uncompressed_bytes
    assert encoding == "zlib-json-v1"
    assert spool.read("bars", "AAA") == list(payload)
    spool.close(remove=True)


def test_spool_fails_closed_before_free_space_reserve_is_exhausted(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_RESERVE_MB", "128")
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_MAX_MB", "256")
    monkeypatch.setattr(
        paper_evidence_spool.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=256 * 1024 * 1024,
            used=200 * 1024 * 1024,
            free=56 * 1024 * 1024,
        ),
    )
    spool = SQLitePaperEvidenceSpool(tmp_path / "bounded.db")

    with pytest.raises(OSError) as captured:
        spool.append("bars", "AAA", ({"value": "x" * 1000},), recorded_at=AS_OF)

    assert captured.value.errno == errno.ENOSPC
    assert "free-space reserve" in str(captured.value)
    spool.close(remove=True)
