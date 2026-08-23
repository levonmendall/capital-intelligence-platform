"""Release clean file-cache pages from completed operating-evidence work.

Capability-scoped production evidence is prepared and validated before the bounded CIO
consumer starts.  The evidence-owner processes may leave clean pages charged to the
service cgroup even after their Python RSS has exited.  This module advises the kernel that
only the files belonging to the already-completed current operating snapshot may be
reclaimed before the CIO child begins.

The advisory is deliberately narrow and fail-soft.  It never drops global caches, deletes
or mutates evidence, changes investment semantics, or weakens the bounded diagnostic's
memory guard.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Mapping


def _data_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    return None if not raw else Path(raw).expanduser()


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


def completed_operating_evidence_paths(values: Mapping[str, str]) -> tuple[Path, ...]:
    """Return only files belonging to the currently qualified operating evidence epoch."""

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

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return tuple(unique)


def _advise_file_cache_dontneed(path: Path) -> bool:
    """Ask Linux to reclaim clean pages for one completed evidence file."""

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or advice is None or not path.is_file():
        return False
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            posix_fadvise(descriptor, 0, 0, advice)
        except OSError:
            return False
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def release_completed_operating_evidence_file_cache(
    values: Mapping[str, str],
) -> tuple[Path, ...]:
    """Release reclaimable pages after evidence validation and before CIO child launch."""

    released: list[Path] = []
    for path in completed_operating_evidence_paths(values):
        if _advise_file_cache_dontneed(path):
            released.append(path)
    return tuple(released)


__all__ = [
    "completed_operating_evidence_paths",
    "release_completed_operating_evidence_file_cache",
]
