from __future__ import annotations

from operations.paper_evidence_spool import SQLitePaperEvidenceSpool


def test_spool_remains_non_authoritative():
    assert not hasattr(SQLitePaperEvidenceSpool, "candidate_authority")
    assert not hasattr(SQLitePaperEvidenceSpool, "decision_authority")
    assert not hasattr(SQLitePaperEvidenceSpool, "construction_authority")
    assert not hasattr(SQLitePaperEvidenceSpool, "execution_authority")
