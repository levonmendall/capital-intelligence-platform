from __future__ import annotations

from pathlib import Path


def test_spool_cache_release_does_not_change_governed_memory_policy():
    source = Path("operations/paper_evidence_spool.py").read_text(encoding="utf-8")

    assert "governed_boundary" not in source
    assert "memory_reserve" not in source
    assert "memory.reclaim" not in source
    assert "drop_caches" not in source
