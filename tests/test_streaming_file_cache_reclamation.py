from __future__ import annotations

from operations import streaming_file_cache_reclamation as reclamation


def _memory(raw: int, inactive: int) -> dict[str, int]:
    return {
        "raw_current_kib": raw,
        "file_kib": inactive,
        "inactive_file_kib": inactive,
        "active_file_kib": 0,
        "anon_kib": max(0, raw - inactive),
    }


def test_streaming_reclaimer_advises_during_bounded_walk(monkeypatch, tmp_path) -> None:
    data = tmp_path / "data"
    (data / "a").mkdir(parents=True)
    (data / "b").mkdir(parents=True)
    files = [
        data / "one.bin",
        data / "a" / "two.bin",
        data / "b" / "three.bin",
    ]
    for index, path in enumerate(files, start=1):
        path.write_bytes(b"x" * (index * 10))
    transient = data / "ignored.tmp"
    transient.write_bytes(b"y" * 99)

    snapshots = iter((_memory(1_980_000, 970_000), _memory(1_850_000, 840_000)))
    monkeypatch.setattr(reclamation, "_memory_snapshot", lambda: next(snapshots))
    advised: list[str] = []
    monkeypatch.setattr(
        reclamation,
        "_advise_clean_file_cache_dontneed",
        lambda path: advised.append(path.name) or True,
    )

    report = reclamation.release_streaming_clean_file_cache(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(data),
            "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_RECLAIM_MAX_FILES": "2",
        }
    )

    assert len(advised) == 2
    assert report["streaming_release"] is True
    assert report["selected_file_count"] == 2
    assert report["released_file_count"] == 2
    assert report["reclaim_truncated"] is True
    assert report["raw_current_reclaimed_kib"] == 130_000
    assert transient.exists()
    assert all(path.exists() for path in files)
    assert report["advisory_only"] is True
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False
    assert report["execution_authority"] is False
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False


def test_streaming_reclaimer_is_fail_soft_without_data_root(monkeypatch) -> None:
    snapshots = iter((_memory(1_980_000, 970_000), _memory(1_980_000, 970_000)))
    monkeypatch.setattr(reclamation, "_memory_snapshot", lambda: next(snapshots))

    report = reclamation.release_streaming_clean_file_cache({})

    assert report["data_root_configured"] is False
    assert report["candidate_file_count"] == 0
    assert report["released_file_count"] == 0
    assert report["raw_current_reclaimed_kib"] == 0
    assert report["evidence_certified"] is False
