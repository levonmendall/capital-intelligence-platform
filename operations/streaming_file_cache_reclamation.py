"""Bounded streaming clean-file cache reclamation for raw-only cgroup pressure.

The broad pre-comprehensive reclaimer ranks every candidate before issuing cache advice.
That is useful for ordinary lifecycle cleanup, but production can reach the raw cgroup
ceiling while roughly a gigabyte of clean inactive file cache is still charged. At that
boundary, useful reclamation must begin immediately rather than depend on a full data-root
scan completing first.

This helper therefore walks the configured data root and issues clean-page
``POSIX_FADV_DONTNEED`` advice as each eligible regular file is encountered. Traversal and
file count remain bounded, transient files and symlinks are skipped, bytes are never
modified or deleted, and failures remain advisory. The helper has no evidence, candidate,
portfolio, construction, execution, or real-money authority.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

_SCHEMA_VERSION = "pre-comprehensive-cache-reclamation.v1"
_SCAN_MAX_ENTRIES_ENV = "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_SCAN_MAX_ENTRIES"
_RECLAIM_MAX_FILES_ENV = "CAPITAL_INTELLIGENCE_PRECOMPREHENSIVE_CACHE_RECLAIM_MAX_FILES"
_DEFAULT_SCAN_MAX_ENTRIES = 50_000
_DEFAULT_RECLAIM_MAX_FILES = 16_384
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
    return None if not raw else Path(raw).expanduser()


def _memory_snapshot() -> dict[str, int | None]:
    root = Path("/sys/fs/cgroup")
    result: dict[str, int | None] = {
        "raw_current_kib": None,
        "file_kib": None,
        "inactive_file_kib": None,
        "active_file_kib": None,
        "anon_kib": None,
    }
    try:
        result["raw_current_kib"] = int(
            (root / "memory.current").read_text(encoding="utf-8").strip()
        ) // 1024
    except (OSError, ValueError):
        pass
    try:
        lines = (root / "memory.stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
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
            result[target] = int(raw_value.strip()) // 1024
        except ValueError:
            continue
    return result


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


def release_streaming_clean_file_cache(values: Mapping[str, str]) -> dict[str, object]:
    """Begin bounded clean-page advice during traversal instead of after a full scan."""

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
    before = _memory_snapshot()
    supported = bool(
        data_root is not None
        and data_root.is_dir()
        and getattr(os, "posix_fadvise", None) is not None
        and getattr(os, "POSIX_FADV_DONTNEED", None) is not None
    )

    scan_entries = 0
    candidate_file_count = 0
    candidate_bytes = 0
    attempted_file_count = 0
    attempted_bytes = 0
    released_file_count = 0
    released_bytes = 0
    scan_truncated = False
    reclaim_truncated = False

    if data_root is not None and data_root.is_dir():
        directories = [data_root]
        while directories and not scan_truncated and not reclaim_truncated:
            directory = directories.pop()
            try:
                iterator = os.scandir(directory)
            except OSError:
                continue
            with iterator:
                for entry in iterator:
                    scan_entries += 1
                    if scan_entries > scan_max_entries:
                        scan_truncated = True
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
                        size = max(0, int(entry.stat(follow_symlinks=False).st_size))
                    except OSError:
                        continue

                    candidate_file_count += 1
                    candidate_bytes += size
                    if attempted_file_count >= reclaim_max_files:
                        reclaim_truncated = True
                        break

                    attempted_file_count += 1
                    attempted_bytes += size
                    if _advise_clean_file_cache_dontneed(Path(entry.path)):
                        released_file_count += 1
                        released_bytes += size

    after = _memory_snapshot()
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "completed",
        "streaming_release": True,
        "data_root_configured": data_root is not None,
        "supported": supported,
        "scan_entries": scan_entries,
        "scan_max_entries": scan_max_entries,
        "scan_truncated": scan_truncated,
        "reclaim_truncated": reclaim_truncated,
        "candidate_file_count": candidate_file_count,
        "candidate_bytes": candidate_bytes,
        "selected_file_count": attempted_file_count,
        "selected_bytes": attempted_bytes,
        "released_file_count": released_file_count,
        "released_bytes": released_bytes,
        "reclaim_max_files": reclaim_max_files,
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


__all__ = ["release_streaming_clean_file_cache"]
