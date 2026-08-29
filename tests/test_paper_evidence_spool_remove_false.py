from __future__ import annotations

from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


def test_close_without_remove_preserves_spool(tmp_path):
    spool = SQLitePaperEvidenceSpool(tmp_path / "preserved.db")
    path = spool.path

    spool.close(remove=False)

    assert path.exists()
    spool.close(remove=True)
    assert not path.exists()
