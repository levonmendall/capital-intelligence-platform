"""Release clean file-cache pages from completed operating-evidence work.

Capability-scoped production evidence is prepared and validated before the bounded CIO
consumer starts. The evidence-owner processes may leave clean pages charged to the
service cgroup even after their Python RSS has exited. This module advises the kernel that
only files belonging to completed, durable current evidence may be reclaimed before the
next heavyweight certification/CIO boundary begins.

The advisory is deliberately narrow and fail-soft. It never drops global caches, deletes
or mutates evidence, changes investment semantics, or weakens the bounded diagnostic's
memory guard.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping


_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")


def _data_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    return None if not raw else Path(raw).expanduser()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _safe_release(value: str) -> str:
    normalized = _SAFE_RELEASE.sub("-", str(value or "").strip()).strip("-.")
    return normalized or "unknown"


def _read_mapping(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _snapshot_stamp(raw: object) -> str | None:
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _current_reference_paths(values: Mapping[str, str], data_root: Path) -> tuple[Path, ...]:
    """Return only current/latest durable reference artifacts used by certification.

    Reference readiness is release-independent at the lane-component level and rebound to
    the exact release through a manifest. The latest-qualified component files are the
    durable authority consumed by a fresh reference stage; old archived attempts and old
    release manifests are intentionally excluded.
    """

    root = data_root / "reference_readiness"
    release = _release(values)
    paths: list[Path] = [
        root / "prequalification-latest.json",
        root / "eodhd_directories-latest-qualified.json",
        root / "futures_contracts-latest-qualified.json",
    ]
    if release and release != "unknown":
        safe = _safe_release(release)
        paths.extend(
            (
                root / f"instrument-master-{safe}.json",
                root / f"progress-{safe}.json",
            )
        )

    assets = root / "assets"
    if assets.is_dir():
        try:
            paths.extend(sorted(assets.glob("*/catalog-latest-qualified.json")))
            registry = assets / "registry.json"
            paths.append(registry)
        except OSError:
            pass
    return tuple(paths)


def _current_comprehensive_discovery_catalog_paths(
    values: Mapping[str, str], data_root: Path
) -> tuple[Path, ...]:
    """Return immutable raw catalog shards belonging only to the exact active release.

    Lane-local comprehensive discovery persists raw catalog shards beneath a release-scoped
    scratch root and later reopens them during provider publication. Completed catalog
    children can therefore leave clean shard pages charged to the service cgroup even after
    the child interpreter exits. Advising these immutable scratch files is safe: no bytes are
    read, deleted, rewritten, or granted any decision authority, and later consumers still
    perform the normal integrity verification before deserializing a shard.
    """

    release = _release(values)
    if not release or release == "unknown":
        return ()
    root = data_root / "comprehensive-discovery-spool" / _safe_release(release)
    if not root.is_dir():
        return ()
    try:
        return tuple(sorted(path for path in root.rglob("raw-catalog-*.pkl") if path.is_file()))
    except OSError:
        return ()


def completed_operating_evidence_paths(values: Mapping[str, str]) -> tuple[Path, ...]:
    """Return files belonging to current qualified operating/all-market evidence."""

    data_root = _data_root(values)
    if data_root is None:
        return ()

    paths: list[Path] = []

    capability_state = data_root / "capability_operating_evidence" / "latest.json"
    paths.append(capability_state)
    state = _read_mapping(capability_state)

    evidence_root = data_root / "continuous_evidence_plane" / "paper-evidence"
    paths.append(evidence_root / "latest.json")

    snapshot_id = str(state.get("snapshot_id") or "").strip()
    stamp = _snapshot_stamp(state.get("as_of"))
    if stamp:
        paths.append(evidence_root / "by-as-of" / f"{stamp}.json")

    if snapshot_id:
        snapshot_path = evidence_root / "snapshots" / f"{snapshot_id}.json"
        paths.append(snapshot_path)
        snapshot = _read_mapping(snapshot_path)
        for index_name in ("quote_index", "company_fact_index"):
            index = snapshot.get(index_name)
            if not isinstance(index, Mapping):
                continue
            for raw_digest in index.values():
                digest = str(raw_digest or "").strip()
                if digest:
                    paths.append(evidence_root / "blobs" / f"{digest}.zlib")

    history_path = data_root / "historical_evidence" / "market_history.sqlite3"
    paths.extend(
        (
            history_path,
            Path(f"{history_path}-wal"),
            Path(f"{history_path}-shm"),
        )
    )
    paths.extend(_current_reference_paths(values, data_root))

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


def _advise_file_cache_dontneed(path: Path) -> bool:
    """Durably flush, then ask Linux to reclaim pages for one completed evidence file.

    ``POSIX_FADV_DONTNEED`` is permitted to leave dirty pages resident. Reference
    components are intentionally immutable once qualified, but some legacy writers use an
    atomic rename without an explicit fsync. Synchronizing the completed file here makes
    those pages eligible for reclaim before the next heavyweight certification lane.

    Both sync and cache advice remain operational-only and fail-soft: any unsupported
    platform/filesystem behavior simply preserves the prior cached state and cannot alter
    evidence bytes, authority, or the resource boundaries themselves.
    """

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    fsync = getattr(os, "fsync", None)
    if (
        posix_fadvise is None
        or advice is None
        or not callable(fsync)
        or not path.is_file()
    ):
        return False
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fsync(descriptor)
            posix_fadvise(descriptor, 0, 0, advice)
        except OSError:
            return False
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def release_current_reference_file_cache(
    values: Mapping[str, str],
) -> tuple[Path, ...]:
    """Release current reference and completed raw-catalog pages at lane handoff."""

    data_root = _data_root(values)
    if data_root is None:
        return ()
    paths = (
        *_current_reference_paths(values, data_root),
        *_current_comprehensive_discovery_catalog_paths(values, data_root),
    )
    released: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if _advise_file_cache_dontneed(path):
            released.append(path)
    return tuple(released)


def release_completed_operating_evidence_file_cache(
    values: Mapping[str, str],
) -> tuple[Path, ...]:
    """Release reclaimable pages after evidence validation and before heavy work."""

    released: list[Path] = []
    for path in completed_operating_evidence_paths(values):
        if _advise_file_cache_dontneed(path):
            released.append(path)
    return tuple(released)


__all__ = [
    "completed_operating_evidence_paths",
    "release_completed_operating_evidence_file_cache",
    "release_current_reference_file_cache",
]
