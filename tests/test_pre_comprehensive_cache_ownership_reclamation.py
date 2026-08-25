from __future__ import annotations

from pathlib import Path

from operations import pre_comprehensive_cache_reclamation as reclamation


def _memory(*, raw: int, inactive: int) -> dict[str, int]:
    return {
        "raw_current_kib": raw,
        "file_kib": inactive,
        "inactive_file_kib": inactive,
        "active_file_kib": 0,
        "anon_kib": max(0, raw - inactive),
    }


def test_reclaims_largest_exact_data_root_files_and_reports_relative_ownership(
    monkeypatch, tmp_path: Path
) -> None:
    data_root = tmp_path / "data"
    large = data_root / "other-cache" / "large.bin"
    medium = data_root / "reference_readiness" / "medium.bin"
    small = data_root / "small.bin"
    transient = data_root / "ignored.tmp"
    for path, payload in (
        (large, b"L" * 100),
        (medium, b"M" * 60),
        (small, b"S" * 10),
        (transient, b"T" * 200),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    original_bytes = {path: path.read_bytes() for path in (large, medium, small, transient)}
    advised: list[Path] = []
    snapshots = iter((_memory(raw=2100, inactive=1500), _memory(raw=1300, inactive=720)))
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
        "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_SCAN_MAX_ENTRIES": "1000",
        "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_RECLAIM_MAX_FILES": "2",
        "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_MANIFEST_MAX_FILES": "2",
        "CAPITAL_INTELLIGENCE_MEMORY_LIMIT_MB": "2048",
        "CAPITAL_INTELLIGENCE_MEMORY_RESERVE_MB": "640",
        "CAPITAL_INTELLIGENCE_CGROUP_HARD_CEILING_RATIO": "0.90",
    }
    original_values = dict(values)

    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda received: (medium,) if received == values else (),
    )
    monkeypatch.setattr(reclamation, "_memory_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reclamation,
        "_advise_clean_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(values)

    assert values == original_values
    assert advised == [large, medium]
    assert report["candidate_file_count"] == 3
    assert report["candidate_bytes"] == 170
    assert report["selected_file_count"] == 2
    assert report["selected_bytes"] == 160
    assert report["legacy_released_file_count"] == 1
    assert report["broad_released_file_count"] == 2
    assert report["released_file_count"] == 2
    assert report["released_bytes"] == 160
    assert report["raw_current_reclaimed_kib"] == 800
    assert report["inactive_file_reclaimed_kib"] == 780
    assert report["largest_candidates"] == [
        {
            "path": "other-cache/large.bin",
            "category": "other-cache",
            "bytes": 100,
            "released": True,
        },
        {
            "path": "reference_readiness/medium.bin",
            "category": "reference_readiness",
            "bytes": 60,
            "released": True,
        },
    ]
    assert all(not str(row["path"]).startswith(str(data_root)) for row in report["largest_candidates"])
    assert transient not in advised
    for path, payload in original_bytes.items():
        assert path.exists()
        assert path.read_bytes() == payload


def test_scan_and_manifest_are_bounded(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    for index in range(5):
        (data_root / f"file-{index}.bin").write_bytes(bytes([index]) * (20 + index))

    candidates, scanned_entries, truncated = reclamation._scan_candidates(
        data_root,
        max_entries=2,
    )
    assert scanned_entries == 3
    assert truncated is True
    assert len(candidates) == 2

    snapshots = iter((_memory(raw=1000, inactive=500), _memory(raw=1000, inactive=500)))
    monkeypatch.setattr(reclamation, "_memory_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda _values: (),
    )
    monkeypatch.setattr(reclamation, "_advise_clean_file_cache_dontneed", lambda _path: True)
    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
            "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_RECLAIM_MAX_FILES": "2",
            "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_MANIFEST_MAX_FILES": "1",
        }
    )
    assert report["selected_file_count"] == 2
    assert len(report["largest_candidates"]) == 1
    assert report["manifest_truncated"] is True


def test_failed_cache_advice_is_fail_soft_and_cannot_certify(monkeypatch, tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    candidate = data_root / "other" / "evidence.bin"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"durable-evidence")
    before_bytes = candidate.read_bytes()

    snapshots = iter((_memory(raw=1900, inactive=1300), _memory(raw=1900, inactive=1300)))
    monkeypatch.setattr(reclamation, "_memory_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda _values: (),
    )
    monkeypatch.setattr(reclamation, "_advise_clean_file_cache_dontneed", lambda _path: False)

    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root)}
    )

    assert report["released_file_count"] == 0
    assert report["released_bytes"] == 0
    assert report["raw_current_reclaimed_kib"] == 0
    assert report["inactive_file_reclaimed_kib"] == 0
    assert report["advisory_only"] is True
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False
    assert report["candidate_authority"] is False
    assert report["sizing_authority"] is False
    assert report["construction_authority"] is False
    assert report["execution_authority"] is False
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False
    assert candidate.exists()
    assert candidate.read_bytes() == before_bytes
