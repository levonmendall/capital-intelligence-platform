from __future__ import annotations

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


def test_catalog_cache_release_never_reads_or_mutates_shard_bytes(
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
    monkeypatch.setattr(
        cache_release,
        "_read_mapping",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("catalog cache release must not parse shard contents")
        ),
    )

    cache_release.release_current_reference_file_cache(
        _values(tmp_path, release=release)
    )

    assert advised == [shard]
    assert shard.read_bytes() == before


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
