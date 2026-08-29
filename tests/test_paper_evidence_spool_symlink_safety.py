from __future__ import annotations

from pathlib import Path

import operations.paper_evidence_spool as spool_module


def test_cache_release_skips_symlinks(monkeypatch, tmp_path):
    target = tmp_path / "target.db"
    target.write_bytes(b"do-not-touch")
    link = tmp_path / "paper-evidence.db"
    link.symlink_to(target)
    called = []

    monkeypatch.setattr(
        spool_module.os,
        "posix_fadvise",
        lambda *_args: called.append(True),
        raising=False,
    )

    spool_module._release_clean_file_cache(Path(link))

    assert not called
    assert target.read_bytes() == b"do-not-touch"
