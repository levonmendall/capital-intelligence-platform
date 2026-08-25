"""Release clean file-cache pages from completed operating-evidence work.

Capability-scoped production evidence is prepared and validated before the bounded CIO
consumer starts. The evidence-owner processes may leave clean pages charged to the
service cgroup even after their Python RSS has exited. This module advises the kernel that
only files belonging to completed, durable current evidence may be reclaimed before the
next heavyweight certification/CIO boundary begins.

Release-scoped comprehensive-discovery raw catalog shards are scratch transport rather
than evidence authority. Once a matching, integrity-valid publication-lane state proves
that the same request has durably consumed a raw shard, this module may retire that closed
scratch file before a later heavyweight catalog lane begins. It never deletes qualified
reference/history evidence, changes investment semantics, or weakens the bounded
diagnostic's memory guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Mapping


_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")
_STAGE_STATE_SCHEMA = "bounded-comprehensive-discovery-stage.v1"
_CATALOG_STAGE_NAME = re.compile(r"catalog-lane-(\d{3})\.json")


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


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validated_stage_body(path: Path, *, expected_stage: str) -> Mapping[str, object]:
    """Read one bounded-discovery stage only when integrity and authority are intact."""

    payload = _read_mapping(path)
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
        return {}
    if body.get("schema_version") != _STAGE_STATE_SCHEMA or body.get("stage") != expected_stage:
        return {}
    if body.get("paper_only") is not True or body.get("real_money_authorized") is not False:
        return {}
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if body.get(authority) is not False:
            return {}
    return body


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
    """Return immutable raw catalog shards belonging only to the exact active release."""

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


def _published_comprehensive_discovery_catalog_paths(
    values: Mapping[str, str], data_root: Path
) -> tuple[Path, ...]:
    """Return raw shards durably consumed by a matching publication-lane child.

    A release root may contain state from an earlier retry. Publication therefore does not
    qualify a raw shard for retirement unless the catalog and publication state share the
    same request/asset identity and the publication state is at least as new as both the
    catalog state and raw file. The catalog descriptor must also name the exact lane-local
    raw shard expected for that index and asset class.
    """

    release = _release(values)
    if not release or release == "unknown":
        return ()
    root = data_root / "comprehensive-discovery-spool" / _safe_release(release)
    if not root.is_dir():
        return ()

    paths: list[Path] = []
    try:
        catalog_states = sorted(root.rglob("catalog-lane-*.json"))
    except OSError:
        return ()
    for catalog_state_path in catalog_states:
        match = _CATALOG_STAGE_NAME.fullmatch(catalog_state_path.name)
        if match is None:
            continue
        index = int(match.group(1))
        catalog_stage = f"catalog-lane-{index:03d}"
        publication_stage = f"publication-lane-{index:03d}"
        publication_state_path = catalog_state_path.with_name(f"{publication_stage}.json")
        catalog = _validated_stage_body(catalog_state_path, expected_stage=catalog_stage)
        publication = _validated_stage_body(
            publication_state_path, expected_stage=publication_stage
        )
        if not catalog or not publication:
            continue

        request_id = str(catalog.get("request_id") or "").strip()
        asset_class = str(catalog.get("asset_class") or "").strip()
        if (
            not request_id
            or not asset_class
            or str(publication.get("request_id") or "").strip() != request_id
            or str(publication.get("asset_class") or "").strip() != asset_class
        ):
            continue

        blob = catalog.get("blob")
        if not isinstance(blob, Mapping):
            continue
        relative_path = str(blob.get("relative_path") or "").strip()
        expected_name = f"raw-catalog-{index:03d}-{_safe_release(asset_class)}.pkl"
        if relative_path != expected_name:
            continue
        sha256 = str(blob.get("sha256") or "").strip().lower()
        try:
            byte_count = int(blob.get("byte_count", -1))
        except (TypeError, ValueError):
            continue
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None or byte_count < 0:
            continue

        raw_path = catalog_state_path.parent / relative_path
        try:
            catalog_mtime = catalog_state_path.stat().st_mtime_ns
            publication_mtime = publication_state_path.stat().st_mtime_ns
            raw_mtime = raw_path.stat().st_mtime_ns
        except OSError:
            continue
        if publication_mtime < catalog_mtime or publication_mtime < raw_mtime:
            continue
        if raw_path.is_symlink() or not raw_path.is_file():
            continue
        paths.append(raw_path)
    return tuple(paths)


def _retire_published_comprehensive_discovery_catalogs(
    values: Mapping[str, str], data_root: Path
) -> tuple[Path, ...]:
    """Unlink only closed raw scratch shards already replaced by durable publication state."""

    retired: list[Path] = []
    for path in _published_comprehensive_discovery_catalog_paths(values, data_root):
        try:
            path.unlink()
        except (FileNotFoundError, OSError):
            continue
        retired.append(path)
    return tuple(retired)


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
    """Retire consumed raw scratch shards, then release remaining current file cache."""

    data_root = _data_root(values)
    if data_root is None:
        return ()
    retired = list(_retire_published_comprehensive_discovery_catalogs(values, data_root))
    paths = (
        *_current_reference_paths(values, data_root),
        *_current_comprehensive_discovery_catalog_paths(values, data_root),
    )
    released: list[Path] = list(retired)
    seen: set[Path] = set(retired)
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
