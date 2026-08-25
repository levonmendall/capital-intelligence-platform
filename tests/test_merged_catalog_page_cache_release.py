from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from operations import bounded_lane_comprehensive_discovery_worker_v2 as worker
from operations import evidence_file_cache_release as cache_release


def _values(tmp_path: Path, *, release: str = "exact-release-sha") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": release,
    }


def _artifact(
    tmp_path: Path,
    *,
    release: str,
    request: str,
    name: str,
    payload: bytes = b"publication-artifact",
) -> Path:
    path = (
        tmp_path
        / "comprehensive-discovery-spool"
        / cache_release._safe_release(release)
        / "20260825T021616000000Z"
        / request
        / name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _descriptor(path: Path) -> dict[str, object]:
    return {
        "relative_path": path.name,
        "sha256": "a" * 64,
        "byte_count": path.stat().st_size,
    }


def _stage_state(
    directory: Path,
    *,
    stage: str,
    request_id: str,
    asset_class: str,
    blob: dict[str, object] | None = None,
    scheduled: bool | None = None,
    provider_preselection_path: Path | None = None,
) -> Path:
    body: dict[str, object] = {
        "schema_version": cache_release._STAGE_STATE_SCHEMA,
        "stage": stage,
        "request_id": request_id,
        "asset_class": asset_class,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if blob is not None:
        body["blob"] = dict(blob)
    if scheduled is not None:
        body["scheduled"] = scheduled
    if provider_preselection_path is not None:
        body["provider_preselection_path"] = str(provider_preselection_path)
    path = directory / f"{stage}.json"
    path.write_text(
        json.dumps({"body": body, "sha256": cache_release._digest(body)}),
        encoding="utf-8",
    )
    return path


def _set_ordered_mtimes(*paths: Path) -> None:
    now = time.time()
    for offset, path in enumerate(paths):
        stamp = now - (len(paths) - offset)
        os.utime(path, (stamp, stamp))


def test_completed_merged_and_provider_files_are_advised_but_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    raw = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-001-etf.pkl",
        payload=b"raw",
    )
    merged = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="merged-catalog-001-etf.pkl",
        payload=b"merged",
    )
    provider = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="provider-preselection-001-etf.json",
        payload=b"provider",
    )
    catalog = _stage_state(
        raw.parent,
        stage="catalog-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=_descriptor(raw),
    )
    publication = _stage_state(
        raw.parent,
        stage="publication-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=_descriptor(merged),
        scheduled=True,
        provider_preselection_path=provider,
    )
    _set_ordered_mtimes(raw, catalog, merged, provider, publication)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    released = cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert raw in released
    assert not raw.exists()
    assert raw not in advised
    assert merged in advised
    assert provider in advised
    assert merged.read_bytes() == b"merged"
    assert provider.read_bytes() == b"provider"


def test_stale_publication_state_cannot_release_newer_merged_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    raw = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-001-etf.pkl",
    )
    merged = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="merged-catalog-001-etf.pkl",
    )
    catalog = _stage_state(
        raw.parent,
        stage="catalog-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=_descriptor(raw),
    )
    publication = _stage_state(
        raw.parent,
        stage="publication-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=_descriptor(merged),
    )
    _set_ordered_mtimes(raw, catalog, publication, merged)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert merged.exists()
    assert merged not in advised


def test_mismatched_publication_identity_cannot_release_merged_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    raw = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )
    merged = _artifact(
        tmp_path,
        release=release,
        request="request-current",
        name="merged-catalog-004-international_equity.pkl",
    )
    catalog = _stage_state(
        raw.parent,
        stage="catalog-lane-004",
        request_id="request-current",
        asset_class="international_equity",
        blob=_descriptor(raw),
    )
    publication = _stage_state(
        raw.parent,
        stage="publication-lane-004",
        request_id="different-request",
        asset_class="international_equity",
        blob=_descriptor(merged),
    )
    _set_ordered_mtimes(raw, catalog, merged, publication)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert merged.exists()
    assert merged not in advised


def test_publication_cache_release_is_exact_release_scoped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    current_release = "exact-release-sha"
    other_release = "different-release-sha"
    current = _artifact(
        tmp_path,
        release=current_release,
        request="request-current",
        name="merged-catalog-001-etf.pkl",
    )
    other = _artifact(
        tmp_path,
        release=other_release,
        request="request-other",
        name="merged-catalog-001-etf.pkl",
    )

    for release, request, merged in (
        (current_release, "request-current", current),
        (other_release, "request-other", other),
    ):
        raw = _artifact(
            tmp_path,
            release=release,
            request=request,
            name="raw-catalog-001-etf.pkl",
        )
        catalog = _stage_state(
            raw.parent,
            stage="catalog-lane-001",
            request_id=request,
            asset_class="etf",
            blob=_descriptor(raw),
        )
        publication = _stage_state(
            raw.parent,
            stage="publication-lane-001",
            request_id=request,
            asset_class="etf",
            blob=_descriptor(merged),
        )
        _set_ordered_mtimes(raw, catalog, merged, publication)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=current_release)
    )

    assert current in advised
    assert other not in advised
    assert other.exists()


def test_publication_lane_uses_checkpoint_writer_for_merged_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(worker, "_CATALOG_PERSIST_CHECKPOINT_BYTES", 64)
    phases: list[str] = []
    original_hashing_writer = worker._legacy._HashingWriter

    monkeypatch.setattr(
        worker._bounded,
        "_validate_request",
        lambda path, values: (
            {"request_id": "request-current", "decision_epoch": "2026-08-25T00:00:00+00:00"},
            object(),
        ),
    )
    monkeypatch.setattr(
        worker._bounded,
        "_load_stage_state",
        lambda path, name: {
            "request_id": "request-current",
            "asset_class": "international_equity",
            "blob": {"relative_path": "raw.pkl", "sha256": "a" * 64, "byte_count": 1},
        },
    )
    monkeypatch.setattr(worker._legacy, "_load_pickle_blob", lambda *args, **kwargs: [b"raw"])
    monkeypatch.setattr(
        worker._base,
        "_merge_certified_lane",
        lambda *args, **kwargs: [b"international-equity" * 64],
    )
    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: (),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": phases.append(phase) or None,
    )
    monkeypatch.setattr(worker, "_safe_reclaim_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker._bounded, "_peak_rss_bytes", lambda: 1)
    monkeypatch.setattr(worker._bounded, "_write_stage_state", lambda *args, **kwargs: None)

    from operations import comprehensive_market_discovery as facade

    monkeypatch.setattr(facade._core._base, "_DEFAULT_REQUIRED_DISCOVERY_LANES", frozenset())
    monkeypatch.setattr(facade._core._base, "_lane_is_scheduled", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        facade._core,
        "record_manual_cio_diagnostic_progress",
        lambda *args, **kwargs: None,
    )

    worker._publication_lane_stage(
        tmp_path / "request.json",
        {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        asset_class_value="international_equity",
        index=4,
    )

    merged = tmp_path / "merged-catalog-004-international_equity.pkl"
    assert merged.is_file()
    assert "pre_merged_persist" in phases
    assert "during_merged_persist" in phases
    assert "post_merged_persist" in phases
    assert worker._legacy._HashingWriter is original_hashing_writer


def test_post_publication_child_release_requires_matching_durable_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    phases: list[str] = []
    monkeypatch.setattr(
        worker._bounded,
        "_validate_request",
        lambda path, values: ({"request_id": "request-current"}, object()),
    )
    monkeypatch.setattr(
        worker._bounded,
        "_load_stage_state",
        lambda path, name: {
            "request_id": "request-current",
            "asset_class": "international_equity",
        },
    )
    monkeypatch.setattr(
        worker,
        "_release_catalog_lane_reference_cache",
        lambda values, *, phase: phases.append(phase) or (tmp_path / "merged.pkl",),
    )
    monkeypatch.setattr(
        worker,
        "_reclaim_catalog_lane_cgroup_cache",
        lambda values, *, phase="handoff": phases.append(phase) or None,
    )
    monkeypatch.setattr(worker, "_safe_reclaim_log", lambda *args, **kwargs: None)

    worker._release_publication_lane_cache_after_child_exit(
        tmp_path / "request.json",
        {},
        asset_class="international_equity",
        index=4,
    )

    assert phases == ["post_publication_child_exit", "post_publication_child_exit"]

    monkeypatch.setattr(
        worker._bounded,
        "_load_stage_state",
        lambda path, name: {
            "request_id": "different-request",
            "asset_class": "international_equity",
        },
    )
    with pytest.raises(worker._legacy.ComprehensiveDiscoverySpoolError):
        worker._release_publication_lane_cache_after_child_exit(
            tmp_path / "request.json",
            {},
            asset_class="international_equity",
            index=4,
        )
