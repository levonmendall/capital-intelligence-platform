from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from operations import evidence_file_cache_release as cache_release


def _values(tmp_path: Path, *, release: str = "exact-release-sha") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "RENDER_GIT_COMMIT": release,
    }


def _raw_catalog(
    tmp_path: Path,
    *,
    release: str,
    request: str,
    name: str,
) -> Path:
    path = (
        tmp_path
        / "comprehensive-discovery-spool"
        / cache_release._safe_release(release)
        / "20260825T003321000000Z"
        / request
        / name
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"immutable-catalog-shard")
    return path


def _stage_state(
    raw_path: Path,
    *,
    stage: str,
    request_id: str,
    asset_class: str,
    blob: dict[str, object] | None = None,
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
    path = raw_path.parent / f"{stage}.json"
    path.write_text(
        json.dumps({"body": body, "sha256": cache_release._digest(body)}),
        encoding="utf-8",
    )
    return path


def _raw_descriptor(path: Path) -> dict[str, object]:
    return {
        "relative_path": path.name,
        "sha256": "a" * 64,
        "byte_count": path.stat().st_size,
    }


def _set_ordered_mtimes(*paths: Path) -> None:
    now = time.time()
    for offset, path in enumerate(paths):
        stamp = now - (len(paths) - offset)
        os.utime(path, (stamp, stamp))


def test_lane_handoff_releases_all_exact_release_raw_catalog_shards(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    first = _raw_catalog(
        tmp_path,
        release=release,
        request="request-a",
        name="raw-catalog-000-us_equity.pkl",
    )
    fifth = _raw_catalog(
        tmp_path,
        release=release,
        request="request-a",
        name="raw-catalog-004-international_equity.pkl",
    )
    merged = _raw_catalog(
        tmp_path,
        release=release,
        request="request-a",
        name="merged-catalog-004-international_equity.pkl",
    )
    other_release = _raw_catalog(
        tmp_path,
        release="different-release-sha",
        request="request-b",
        name="raw-catalog-000-us_equity.pkl",
    )

    advised: list[Path] = []

    def fake_advise(path: Path) -> bool:
        if not path.is_file():
            return False
        advised.append(path)
        return True

    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", fake_advise)

    released = cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert first in released
    assert fifth in released
    assert first in advised
    assert fifth in advised
    assert merged not in advised
    assert other_release not in advised


def test_catalog_release_covers_multiple_requests_for_same_exact_release(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    earlier = _raw_catalog(
        tmp_path,
        release=release,
        request="request-earlier",
        name="raw-catalog-001-etf.pkl",
    )
    current = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )

    advised: list[Path] = []

    def fake_advise(path: Path) -> bool:
        if not path.is_file():
            return False
        advised.append(path)
        return True

    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", fake_advise)

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert advised == sorted((earlier, current))


def test_catalog_cache_release_never_reads_or_mutates_unpublished_shard_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )
    before = shard.read_bytes()
    advised: list[Path] = []

    def fake_advise(path: Path) -> bool:
        if path == shard:
            advised.append(path)
            return True
        return False

    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", fake_advise)

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert advised == [shard]
    assert shard.read_bytes() == before


def test_published_raw_catalog_is_retired_before_later_lane_advice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-001-etf.pkl",
    )
    descriptor = _raw_descriptor(shard)
    catalog = _stage_state(
        shard,
        stage="catalog-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=descriptor,
    )
    publication = _stage_state(
        shard,
        stage="publication-lane-001",
        request_id="request-current",
        asset_class="etf",
    )
    _set_ordered_mtimes(shard, catalog, publication)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    released = cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert shard in released
    assert not shard.exists()
    assert shard not in advised


def test_stale_publication_state_cannot_retire_newer_retry_shard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-001-etf.pkl",
    )
    descriptor = _raw_descriptor(shard)
    publication = _stage_state(
        shard,
        stage="publication-lane-001",
        request_id="request-current",
        asset_class="etf",
    )
    catalog = _stage_state(
        shard,
        stage="catalog-lane-001",
        request_id="request-current",
        asset_class="etf",
        blob=descriptor,
    )
    _set_ordered_mtimes(publication, shard, catalog)

    advised: list[Path] = []
    monkeypatch.setattr(
        cache_release,
        "_advise_file_cache_dontneed",
        lambda path: advised.append(path) or True,
    )

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert shard.exists()
    assert shard in advised


def test_mismatched_publication_identity_cannot_retire_raw_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )
    catalog = _stage_state(
        shard,
        stage="catalog-lane-004",
        request_id="request-current",
        asset_class="international_equity",
        blob=_raw_descriptor(shard),
    )
    publication = _stage_state(
        shard,
        stage="publication-lane-004",
        request_id="different-request",
        asset_class="international_equity",
    )
    _set_ordered_mtimes(shard, catalog, publication)
    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", lambda _path: True)

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert shard.exists()


def test_tampered_publication_state_cannot_retire_raw_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )
    catalog = _stage_state(
        shard,
        stage="catalog-lane-004",
        request_id="request-current",
        asset_class="international_equity",
        blob=_raw_descriptor(shard),
    )
    publication = _stage_state(
        shard,
        stage="publication-lane-004",
        request_id="request-current",
        asset_class="international_equity",
    )
    payload = json.loads(publication.read_text(encoding="utf-8"))
    payload["body"]["asset_class"] = "future"
    publication.write_text(json.dumps(payload), encoding="utf-8")
    _set_ordered_mtimes(shard, catalog, publication)
    monkeypatch.setattr(cache_release, "_advise_file_cache_dontneed", lambda _path: True)

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert shard.exists()


def test_catalog_cache_advice_failure_remains_fail_soft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = "exact-release-sha"
    shard = _raw_catalog(
        tmp_path,
        release=release,
        request="request-current",
        name="raw-catalog-004-international_equity.pkl",
    )

    if not hasattr(cache_release.os, "posix_fadvise"):
        pytest.skip("POSIX_FADV_DONTNEED is unavailable on this platform")

    monkeypatch.setattr(cache_release.os, "fsync", lambda _descriptor: None)

    def fail_advise(*_args: object) -> None:
        raise OSError("advisory reclaim unavailable")

    monkeypatch.setattr(cache_release.os, "posix_fadvise", fail_advise)

    assert cache_release._advise_file_cache_dontneed(shard) is False
    assert shard.read_bytes() == b"immutable-catalog-shard"
