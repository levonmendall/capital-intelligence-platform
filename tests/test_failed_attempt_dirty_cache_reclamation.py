from __future__ import annotations

from datetime import datetime, timezone

from operations import pre_comprehensive_cache_reclamation as reclamation
from operations import stage_isolated_evidence_pipeline as pipeline


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-dirty-cache-test",
        "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_MAX_AGE_SECONDS": "900",
    }


def _memory_snapshots():
    snapshots = iter(
        (
            {
                "raw_current_kib": 1_900_000,
                "file_kib": 900_000,
                "inactive_file_kib": 850_000,
                "active_file_kib": 0,
                "anon_kib": 1_000_000,
            },
            {
                "raw_current_kib": 1_500_000,
                "file_kib": 500_000,
                "inactive_file_kib": 450_000,
                "active_file_kib": 0,
                "anon_kib": 1_000_000,
            },
        )
    )
    return lambda: next(snapshots)


def test_normal_active_pipeline_keeps_clean_page_only_reclamation(tmp_path, monkeypatch) -> None:
    values = _values(tmp_path)
    pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )
    candidate = tmp_path / "cache" / "candidate.bin"
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(b"x" * 128)

    clean_advice: list[object] = []

    def forbidden_flush(path):  # pragma: no cover - assertion helper
        raise AssertionError(f"normal active pipeline must not fsync broad cache owner {path}")

    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda _values: (),
    )
    monkeypatch.setattr(
        reclamation,
        "_scan_candidates",
        lambda *_args, **_kwargs: ([(128, "cache", "cache/candidate.bin", candidate)], 1, False),
    )
    monkeypatch.setattr(reclamation, "_memory_snapshot", _memory_snapshots())
    monkeypatch.setattr(reclamation, "_flush_then_advise_file_cache_dontneed", forbidden_flush)
    monkeypatch.setattr(
        reclamation,
        "_advise_clean_file_cache_dontneed",
        lambda path: clean_advice.append(path) or True,
    )

    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(values)

    assert report["failed_attempt_supersession_detected"] is False
    assert report["flush_attempted_file_count"] == 0
    assert report["flushed_file_count"] == 0
    assert clean_advice == [candidate]
    assert report["released_file_count"] == 1
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False
    assert report["real_money_authorized"] is False


def test_archived_failed_attempt_flushes_largest_closed_files_before_retry(
    tmp_path, monkeypatch
) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_FILES": "2",
        "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_BYTES": str(1024 * 1024),
    }
    state = pipeline.ensure_stage_isolated_evidence_pipeline(
        values,
        requested_at=datetime.now(timezone.utc),
    )
    pipeline.begin_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
    )
    failed = pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticResourceFailure",
        error_detail="raw hard ceiling",
    )

    failed_bytes = failed.path.read_bytes()
    archive_dir = failed.path.parent / "attempts"
    archive_dir.mkdir(parents=True)
    (archive_dir / f"{failed.pipeline_id}.json").write_bytes(failed_bytes)
    failed.path.unlink()

    first = tmp_path / "cache" / "first.bin"
    second = tmp_path / "cache" / "second.bin"
    third = tmp_path / "cache" / "third.bin"
    first.parent.mkdir(parents=True)
    for path, size in ((first, 500), (second, 300), (third, 100)):
        path.write_bytes(b"x" * size)

    flushed: list[object] = []
    clean_advice: list[object] = []
    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda _values: (),
    )
    monkeypatch.setattr(
        reclamation,
        "_scan_candidates",
        lambda *_args, **_kwargs: (
            [
                (500, "cache", "cache/first.bin", first),
                (300, "cache", "cache/second.bin", second),
                (100, "cache", "cache/third.bin", third),
            ],
            3,
            False,
        ),
    )
    monkeypatch.setattr(reclamation, "_memory_snapshot", _memory_snapshots())
    monkeypatch.setattr(
        reclamation,
        "_flush_then_advise_file_cache_dontneed",
        lambda path: (flushed.append(path) or True, True),
    )
    monkeypatch.setattr(
        reclamation,
        "_advise_clean_file_cache_dontneed",
        lambda path: clean_advice.append(path) or True,
    )

    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(values)

    assert report["failed_attempt_supersession_detected"] is True
    assert flushed == [first, second]
    assert clean_advice == [third]
    assert report["flush_attempted_file_count"] == 2
    assert report["flush_attempted_bytes"] == 800
    assert report["flushed_file_count"] == 2
    assert report["flushed_bytes"] == 800
    assert report["released_file_count"] == 3
    assert report["raw_current_reclaimed_kib"] == 400_000
    assert report["inactive_file_reclaimed_kib"] == 400_000
    assert report["advisory_only"] is True
    assert report["evidence_certified"] is False
    assert report["construction_authority"] is False
    assert report["execution_authority"] is False
    assert report["paper_only"] is True
    assert report["real_money_authorized"] is False


def test_failed_attempt_flush_byte_budget_is_bounded(tmp_path, monkeypatch) -> None:
    values = {
        **_values(tmp_path),
        "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_FILES": "64",
        "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_BYTES": str(16 * 1024 * 1024),
    }
    state = pipeline.ensure_stage_isolated_evidence_pipeline(values)
    failed = pipeline.fail_evidence_stage(
        values,
        pipeline_id=state.pipeline_id,
        stage="reference",
        error_type="SyntheticResourceFailure",
        error_detail="raw hard ceiling",
    )
    archive_dir = failed.path.parent / "attempts"
    archive_dir.mkdir(parents=True)
    (archive_dir / f"{failed.pipeline_id}.json").write_bytes(failed.path.read_bytes())
    failed.path.unlink()

    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    sixteen_mib = 16 * 1024 * 1024

    flushed: list[object] = []
    clean_advice: list[object] = []
    monkeypatch.setattr(
        reclamation,
        "release_completed_operating_evidence_file_cache",
        lambda _values: (),
    )
    monkeypatch.setattr(
        reclamation,
        "_scan_candidates",
        lambda *_args, **_kwargs: (
            [
                (sixteen_mib, "_root", "first.bin", first),
                (sixteen_mib, "_root", "second.bin", second),
            ],
            2,
            False,
        ),
    )
    monkeypatch.setattr(reclamation, "_memory_snapshot", _memory_snapshots())
    monkeypatch.setattr(
        reclamation,
        "_flush_then_advise_file_cache_dontneed",
        lambda path: (flushed.append(path) or True, True),
    )
    monkeypatch.setattr(
        reclamation,
        "_advise_clean_file_cache_dontneed",
        lambda path: clean_advice.append(path) or True,
    )

    report = reclamation.release_pre_comprehensive_completed_stage_file_cache(values)

    assert flushed == [first]
    assert clean_advice == [second]
    assert report["flush_attempted_file_count"] == 1
    assert report["flush_attempted_bytes"] == sixteen_mib
