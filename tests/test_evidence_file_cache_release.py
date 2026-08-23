from __future__ import annotations

import json
from pathlib import Path

from operations import evidence_file_cache_release as cache_release


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_completed_operating_evidence_paths_are_current_epoch_only(tmp_path: Path) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    snapshot_id = "snapshot-current"
    quote_digest = "quote-digest"
    company_digest = "company-digest"

    _write_json(
        tmp_path / "capability_operating_evidence" / "latest.json",
        {
            "as_of": "2026-08-23T20:00:00+00:00",
            "snapshot_id": snapshot_id,
        },
    )
    _write_json(
        tmp_path
        / "continuous_evidence_plane"
        / "paper-evidence"
        / "snapshots"
        / f"{snapshot_id}.json",
        {
            "quote_index": {"SPY": quote_digest},
            "company_fact_index": {"SPY": company_digest},
        },
    )

    observed = set(cache_release.completed_operating_evidence_paths(values))
    evidence_root = tmp_path / "continuous_evidence_plane" / "paper-evidence"
    history = tmp_path / "historical_evidence" / "market_history.sqlite3"

    assert tmp_path / "capability_operating_evidence" / "latest.json" in observed
    assert evidence_root / "latest.json" in observed
    assert evidence_root / "by-as-of" / "20260823T200000000000Z.json" in observed
    assert evidence_root / "snapshots" / f"{snapshot_id}.json" in observed
    assert evidence_root / "blobs" / f"{quote_digest}.zlib" in observed
    assert evidence_root / "blobs" / f"{company_digest}.zlib" in observed
    assert history in observed
    assert Path(f"{history}-wal") in observed
    assert Path(f"{history}-shm") in observed
    assert not any("snapshot-old" in str(path) for path in observed)


def test_release_is_fail_soft_and_advises_only_existing_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    state = tmp_path / "capability_operating_evidence" / "latest.json"
    _write_json(state, {})
    history = tmp_path / "historical_evidence" / "market_history.sqlite3"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(b"history")

    advised: list[Path] = []

    def fake_advise(path: Path) -> bool:
        if not path.is_file():
            return False
        advised.append(path)
        return True

    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", fake_advise)

    released = cache_release.release_completed_operating_evidence_file_cache(values)

    assert set(released) == {state, history}
    assert set(advised) == {state, history}


def test_posix_cache_advisory_is_optional_and_fail_soft(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "evidence.sqlite3"
    target.write_bytes(b"evidence")

    monkeypatch.delattr(cache_release.os, "posix_fadvise", raising=False)

    assert cache_release._advise_file_cache_dontneed(target) is False
