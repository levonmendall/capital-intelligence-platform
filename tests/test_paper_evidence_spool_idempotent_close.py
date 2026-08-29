from __future__ import annotations

from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


def test_repeated_remove_close_is_idempotent(tmp_path):
    spool = SQLitePaperEvidenceSpool(tmp_path / "idempotent.db")

    spool.close(remove=True)
    spool.close(remove=True)

    assert not spool.path.exists()
