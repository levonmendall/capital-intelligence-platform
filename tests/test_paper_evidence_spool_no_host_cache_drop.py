from __future__ import annotations

from pathlib import Path


def test_spool_release_uses_file_advice_not_host_cache_drop():
    source = Path("operations/paper_evidence_spool.py").read_text(encoding="utf-8")

    assert "POSIX_FADV_DONTNEED" in source
    assert "/proc/sys/vm/drop_caches" not in source
