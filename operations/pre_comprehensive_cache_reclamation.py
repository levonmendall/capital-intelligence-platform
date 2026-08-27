"""Bound and report file-cache reclamation at completed evidence boundaries.

Normal post-stage reclamation advises only already-clean regular-file pages below the
configured Capital Intelligence data root. A failed stage-isolated attempt is different:
the failed coordinator is durably archived and its latest pointer is removed before this
helper runs, so no failed-attempt child remains active, but recently written closed files
may still have dirty file-backed pages charged to the service cgroup. At that exact
supersession boundary, this module boundedly flushes only the largest closed regular files
before advising their pages reclaimable.

The scan, failed-attempt flush set, and manifest are bounded. Cache advice is fail-soft and
never changes file bytes, evidence authority, resource limits, or investment decisions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from operations.evidence_file_cache_release import (
    release_completed_operating_evidence_file_cache,
)
from operations.stage_isolated_evidence_pipeline import (
    _path as _stage_isolated_state_path,
    load_stage_isolated_evidence_state,
)


_SCHEMA_VERSION = "pre-comprehensive-cache-reclamation.v1"
_SCAN_MAX_ENTRIES_ENV = "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_SCAN_MAX_ENTRIES"
_RECLAIM_MAX_FILES_ENV = "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_RECLAIM_MAX_FILES"
_MANIFEST_MAX_FILES_ENV = "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_MANIFEST_MAX_FILES"
_FAILED_ATTEMPT_FLUSH_MAX_FILES_ENV = (
    "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_FILES"
)
_FAILED_ATTEMPT_FLUSH_MAX_BYTES_ENV = (
    "CAPITAL_INTELLIGENCE_FAILED_ATTEMPT_CACHE_FLUSH_MAX_BYTES"
)
_DEFAULT_SCAN_MAX_ENTRIES = 50_000
_DEFAULT_RECLAIM_MAX_FILES = 16_384
_DEFAULT_MANIFEST_MAX_FILES = 32
_DEFAULT_FAILED_ATTEMPT_FLUSH_MAX_FILES = 64
_DEFAULT_FAILED_ATTEMPT_FLUSH_MAX_BYTES = 512 * 1024 * 1024
_TRANSIENT_SUFFIXES = (".lock", ".part", ".partial", ".tmp")


def _bounded_int(
    values: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(str(values.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _data_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _memory_snapshot() -> dict[str, int | None]:
    root = Path("/sys/fs/cgroup")
    snapshot: dict[str, int | None] = {
        "raw_current_kib": None,
        "file_kib": None,
        "inactive_file_kib": None,
        "active_file_kib": None,
        "anon_kib": None,
    }
    try:
        snapshot["raw_current_kib"] = int(
            (root / "memory.current").read_text(encoding="utf-8").strip()
        ) // 1024
    except (OSError, ValueError):
        pass

    try:
        lines = (root / "memory.stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return snapshot

    wanted = {
        "file": "file_kib",
        "inactive_file": "inactive_file_kib",
        "active_file": "active_file_kib",
        "anon": "anon_kib",
    }
    for line in lines:
        name, _, raw_value = line.partition(" ")
        target = wanted.get(name)
        if target is None:
            continue
        try:
            snapshot[target] = int(raw_value.strip()) // 1024
        except ValueError:
            continue
    return snapshot


def _reclaimed_kib(
    before: Mapping[str, int | None],
    after: Mapping[str, int | None],
    key: str,
) -> int | None:
    before_value = before.get(key)
    after_value = after.get(key)
    if not isinstance(before_value, int) or not isinstance(after_value, int):
        return None
    return max(0, before_value - after_value)


def _advise_clean_file_cache_dontneed(path: Path) -> bool:
    """Advise only clean pages reclaimable without forcing broad fsync I/O."""

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or advice is None:
        return False
    try:
        if path.is_symlink() or not path.is_file():
            return False
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            posix_fadvise(descriptor, 0, 0, advice)
        except (OSError, TypeError, ValueError):
            return False
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _flush_then_advise_file_cache_dontneed(path: Path) -> tuple[bool, bool]:
    """Flush one closed file, then advise its now-clean pages reclaimable.

    This is reserved for the failed-attempt supersession boundary. The file is opened
    read-only and never modified. A failed fsync does not prevent advisory release of any
    pages that were already clean.
    """

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    if posix_fadvise is None or advice is None:
        return False, False
    try:
        if path.is_symlink() or not path.is_file():
            return False, False
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False, False

    flushed = False
    released = False
    try:
        try:
            os.fsync(descriptor)
            flushed = True
        except OSError:
            pass
        try:
            posix_fadvise(descriptor, 0, 0, advice)
            released = True
        except (OSError, TypeError, ValueError):
            pass
        return flushed, released
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _scan_candidates(
    data_root: Path,
    *,
    max_entries: int,
) -> tuple[list[tuple[int, str, str, Path]], int, bool]:
    """Return bounded regular-file candidates as size/category/relative/path tuples."""

    candidates: list[tuple[int, str, str, Path]] = []
    scanned_entries = 0
    truncated = False
    if not data_root.is_dir():
        return candidates, scanned_entries, truncated

    directories = [data_root]
    while directories and not truncated:
        directory = directories.pop()
        try:
            iterator = os.scandir(directory)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                scanned_entries += 1
                if scanned_entries > max_entries:
                    truncated = True
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if entry.name.lower().endswith(_TRANSIENT_SUFFIXES):
                        continue
                    size = int(entry.stat(follow_symlinks=False).st_size)
                except OSError:
                    continue
                path = Path(entry.path)
                try:
                    relative = path.relative_to(data_root).as_posix()
                except ValueError:
                    continue
                if not relative:
                    continue
                category = relative.split("/", 1)[0] if "/" in relative else "_root"
                candidates.append((size, category, relative, path))

    candidates.sort(key=lambda item: (-item[0], item[2]))
    return candidates, scanned_entries, truncated


def _failed_attempt_supersession(values: Mapping[str, str]) -> bool:
    """Return true only after a failed stage journal was archived and unlinked.

    ``run_stage_isolated_evidence_pipeline`` archives the validated failed latest journal,
    removes that exact latest pointer, and invokes this reclaimer before creating the
    replacement attempt. Normal comprehensive/post-lane reclamation retains a current
    stage journal and therefore stays on clean-page-only advice.
    """

    try:
        current = load_stage_isolated_evidence_state(values)
        state_path = _stage_isolated_state_path(values)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if current is not None or state_path.exists():
        return False

    archive_dir = state_path.parent / "attempts"
    try:
        return archive_dir.is_dir() and any(
            path.is_file() for path in archive_dir.glob("*.json")
        )
    except OSError:
        return False


def release_pre_comprehensive_completed_stage_file_cache(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Reclaim bounded data-root cache and return exact ownership telemetry."""

    data_root = _data_root(values)
    scan_max_entries = _bounded_int(
        values,
        _SCAN_MAX_ENTRIES_ENV,
        _DEFAULT_SCAN_MAX_ENTRIES,
        minimum=1_000,
        maximum=100_000,
    )
    reclaim_max_files = _bounded_int(
        values,
        _RECLAIM_MAX_FILES_ENV,
        _DEFAULT_RECLAIM_MAX_FILES,
        minimum=1,
        maximum=16_384,
    )
    manifest_max_files = _bounded_int(
        values,
        _MANIFEST_MAX_FILES_ENV,
        _DEFAULT_MANIFEST_MAX_FILES,
        minimum=1,
        maximum=64,
    )
    flush_max_files = _bounded_int(
        values,
        _FAILED_ATTEMPT_FLUSH_MAX_FILES_ENV,
        _DEFAULT_FAILED_ATTEMPT_FLUSH_MAX_FILES,
        minimum=1,
        maximum=256,
    )
    flush_max_bytes = _bounded_int(
        values,
        _FAILED_ATTEMPT_FLUSH_MAX_BYTES_ENV,
        _DEFAULT_FAILED_ATTEMPT_FLUSH_MAX_BYTES,
        minimum=16 * 1024 * 1024,
        maximum=2 * 1024 * 1024 * 1024,
    )
    failed_attempt_supersession = _failed_attempt_supersession(values)

    before = _memory_snapshot()
    legacy_released = tuple(release_completed_operating_evidence_file_cache(values))

    candidates: list[tuple[int, str, str, Path]] = []
    scanned_entries = 0
    scan_truncated = False
    if data_root is not None:
        candidates, scanned_entries, scan_truncated = _scan_candidates(
            data_root,
            max_entries=scan_max_entries,
        )

    selected = candidates[:reclaim_max_files]
    released_paths = set(legacy_released)
    broad_released_paths: set[Path] = set()
    flushed_paths: set[Path] = set()
    flush_attempted_file_count = 0
    flush_attempted_bytes = 0

    for size, _category, _relative, path in selected:
        released = False
        should_flush = (
            failed_attempt_supersession
            and flush_attempted_file_count < flush_max_files
            and flush_attempted_bytes < flush_max_bytes
        )
        if should_flush:
            flush_attempted_file_count += 1
            flush_attempted_bytes += size
            flushed, released = _flush_then_advise_file_cache_dontneed(path)
            if flushed:
                flushed_paths.add(path)
        else:
            released = _advise_clean_file_cache_dontneed(path)
        if released:
            broad_released_paths.add(path)
            released_paths.add(path)

    after = _memory_snapshot()
    candidate_paths = {path for _size, _category, _relative, path in candidates}
    released_candidate_paths = released_paths & candidate_paths
    selected_paths = {path for _size, _category, _relative, path in selected}

    category_rows: dict[str, dict[str, object]] = {}
    for size, category, _relative, path in candidates:
        row = category_rows.setdefault(
            category,
            {
                "category": category,
                "candidate_file_count": 0,
                "candidate_bytes": 0,
                "selected_file_count": 0,
                "selected_bytes": 0,
                "released_file_count": 0,
                "released_bytes": 0,
            },
        )
        row["candidate_file_count"] = int(row["candidate_file_count"]) + 1
        row["candidate_bytes"] = int(row["candidate_bytes"]) + size
        if path in selected_paths:
            row["selected_file_count"] = int(row["selected_file_count"]) + 1
            row["selected_bytes"] = int(row["selected_bytes"]) + size
        if path in released_candidate_paths:
            row["released_file_count"] = int(row["released_file_count"]) + 1
            row["released_bytes"] = int(row["released_bytes"]) + size

    categories = sorted(
        category_rows.values(),
        key=lambda row: (-int(row["candidate_bytes"]), str(row["category"])),
    )

    manifest: list[dict[str, object]] = []
    for size, category, relative, path in selected[:manifest_max_files]:
        row: dict[str, object] = {
            "path": relative[:320],
            "category": category[:96],
            "bytes": size,
            "released": path in released_paths,
        }
        if failed_attempt_supersession:
            row["flushed"] = path in flushed_paths
        manifest.append(row)

    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "completed",
        "data_root_configured": data_root is not None,
        "failed_attempt_supersession_detected": failed_attempt_supersession,
        "scan_entries": scanned_entries,
        "scan_max_entries": scan_max_entries,
        "scan_truncated": scan_truncated,
        "candidate_file_count": len(candidates),
        "candidate_bytes": sum(size for size, _category, _relative, _path in candidates),
        "selected_file_count": len(selected),
        "selected_bytes": sum(
            size for size, _category, _relative, _path in selected
        ),
        "reclaim_max_files": reclaim_max_files,
        "legacy_released_file_count": len(legacy_released),
        "broad_released_file_count": len(broad_released_paths),
        "released_file_count": len(released_candidate_paths),
        "released_bytes": sum(
            size
            for size, _category, _relative, path in candidates
            if path in released_candidate_paths
        ),
        "flush_max_files": flush_max_files,
        "flush_max_bytes": flush_max_bytes,
        "flush_attempted_file_count": flush_attempted_file_count,
        "flush_attempted_bytes": flush_attempted_bytes,
        "flushed_file_count": len(flushed_paths),
        "flushed_bytes": sum(
            size for size, _category, _relative, path in candidates if path in flushed_paths
        ),
        "manifest_max_files": manifest_max_files,
        "manifest_truncated": len(selected) > manifest_max_files,
        "largest_candidates": manifest,
        "categories": categories,
        "memory_before": before,
        "memory_after": after,
        "raw_current_reclaimed_kib": _reclaimed_kib(before, after, "raw_current_kib"),
        "inactive_file_reclaimed_kib": _reclaimed_kib(
            before, after, "inactive_file_kib"
        ),
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


__all__ = ["release_pre_comprehensive_completed_stage_file_cache"]
