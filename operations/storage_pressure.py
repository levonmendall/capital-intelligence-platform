"""Conservative recovery for a nearly full persistent state disk.

Canonical databases, research records, portfolio state, lineage, and reports are never
removed by this module. Eligible cleanup is limited to interrupted backup artifacts,
oldest bounded backup archives, and cycle-local paper-evidence spool files that have no
candidate, CIO, construction, execution, or recovery authority.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


_BACKUP_GLOB = "capital-intelligence-*.tar.gz*"
_STALE_TEMP_SUFFIXES = (".tmp", ".partial")
_EVIDENCE_SPOOL_GLOB = "paper-evidence-*.db*"


@dataclass(frozen=True, slots=True)
class StorageRecoveryReport:
    state_root: str
    backup_directory: str
    total_bytes: int
    free_bytes_before: int
    free_bytes_after: int
    reserve_bytes: int
    removed_archives: tuple[str, ...]
    removed_temporary_files: tuple[str, ...]
    removed_evidence_spool_files: tuple[str, ...]
    removed_evidence_spool_bytes: int
    evidence_spool_directories: tuple[str, ...]
    minimum_archives_preserved: int

    @property
    def recovered(self) -> bool:
        return bool(
            self.removed_archives
            or self.removed_temporary_files
            or self.removed_evidence_spool_files
        )

    @property
    def reserve_satisfied(self) -> bool:
        return self.free_bytes_after >= self.reserve_bytes

    def to_dict(self) -> dict[str, object]:
        return {
            "state_root": self.state_root,
            "backup_directory": self.backup_directory,
            "total_bytes": self.total_bytes,
            "free_bytes_before": self.free_bytes_before,
            "free_bytes_after": self.free_bytes_after,
            "reserve_bytes": self.reserve_bytes,
            "removed_archives": list(self.removed_archives),
            "removed_temporary_files": list(self.removed_temporary_files),
            "removed_evidence_spool_files": list(self.removed_evidence_spool_files),
            "removed_evidence_spool_bytes": self.removed_evidence_spool_bytes,
            "evidence_spool_directories": list(self.evidence_spool_directories),
            "minimum_archives_preserved": self.minimum_archives_preserved,
            "recovered": self.recovered,
            "reserve_satisfied": self.reserve_satisfied,
            "canonical_authorities_deleted": False,
            "real_money_authorized": False,
        }


def _positive_integer(
    values: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
) -> int:
    raw = values.get(name)
    resolved = default if raw is None or not raw.strip() else int(raw)
    if resolved < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return resolved


def _remove_disposable_evidence_spools(
    directories: Sequence[str | Path],
) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
    removed: list[str] = []
    removed_bytes = 0
    inspected: list[str] = []
    seen: set[Path] = set()
    for raw_directory in directories:
        directory = Path(raw_directory).expanduser()
        try:
            resolved = directory.resolve(strict=False)
        except OSError:
            resolved = directory
        if resolved in seen:
            continue
        seen.add(resolved)
        inspected.append(str(directory))
        if not directory.exists() or not directory.is_dir() or directory.is_symlink():
            continue
        for candidate in sorted(directory.glob(_EVIDENCE_SPOOL_GLOB)):
            try:
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                size = candidate.stat().st_size
                candidate.unlink()
            except OSError:
                continue
            removed.append(str(candidate))
            removed_bytes += size
        try:
            directory.rmdir()
        except OSError:
            pass
    return tuple(removed), removed_bytes, tuple(inspected)


def reclaim_backup_space(
    *,
    state_root: str | Path,
    backup_directory: str | Path,
    reserve_bytes: int,
    minimum_archives: int = 1,
    disposable_spool_directories: Sequence[str | Path] = (),
) -> StorageRecoveryReport:
    """Remove only disposable spools and bounded backup artifacts to restore reserve."""

    root = Path(state_root).expanduser()
    backup_root = Path(backup_directory).expanduser()
    if reserve_bytes < 1:
        raise ValueError("reserve_bytes must be positive")
    if minimum_archives < 1:
        raise ValueError("minimum_archives must be positive")

    root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    free_before = usage.free
    removed_temporary: list[str] = []
    removed_archives: list[str] = []

    removed_spools, removed_spool_bytes, inspected_spool_directories = (
        _remove_disposable_evidence_spools(disposable_spool_directories)
    )

    # Interrupted archive writes are never valid recovery authorities.
    for candidate in sorted(backup_root.iterdir(), key=lambda item: item.name):
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and candidate.name.endswith(_STALE_TEMP_SUFFIXES)
        ):
            try:
                candidate.unlink()
            except OSError:
                continue
            removed_temporary.append(candidate.name)

    archives = [
        candidate
        for candidate in backup_root.glob(_BACKUP_GLOB)
        if candidate.is_file() and not candidate.is_symlink()
    ]
    archives.sort(key=lambda item: (item.stat().st_mtime_ns, item.name))

    usage = shutil.disk_usage(root)
    while usage.free < reserve_bytes and len(archives) > minimum_archives:
        candidate = archives.pop(0)
        try:
            candidate.unlink()
        except OSError:
            break
        removed_archives.append(candidate.name)
        usage = shutil.disk_usage(root)

    return StorageRecoveryReport(
        state_root=str(root),
        backup_directory=str(backup_root),
        total_bytes=usage.total,
        free_bytes_before=free_before,
        free_bytes_after=usage.free,
        reserve_bytes=reserve_bytes,
        removed_archives=tuple(removed_archives),
        removed_temporary_files=tuple(removed_temporary),
        removed_evidence_spool_files=removed_spools,
        removed_evidence_spool_bytes=removed_spool_bytes,
        evidence_spool_directories=inspected_spool_directories,
        minimum_archives_preserved=minimum_archives,
    )


def reclaim_from_environment(
    values: Mapping[str, str] | None = None,
) -> StorageRecoveryReport:
    """Apply the bounded Render storage policy from environment values."""

    resolved = os.environ if values is None else values
    state_root = Path(
        resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    backup_directory = Path(
        resolved.get(
            "CAPITAL_INTELLIGENCE_BACKUP_DIRECTORY",
            str(state_root / "backups"),
        )
    ).expanduser()
    reserve_mb = _positive_integer(
        resolved,
        "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB",
        default=768,
        minimum=64,
    )
    minimum_archives = _positive_integer(
        resolved,
        "CAPITAL_INTELLIGENCE_BACKUP_MINIMUM_ARCHIVES",
        default=1,
        minimum=1,
    )
    spool_directories: list[Path] = [state_root / "paper_evidence_spool"]
    configured_spool = resolved.get(
        "CAPITAL_INTELLIGENCE_EVIDENCE_SPOOL_DIR", ""
    ).strip()
    if configured_spool:
        spool_directories.append(Path(configured_spool).expanduser())
    return reclaim_backup_space(
        state_root=state_root,
        backup_directory=backup_directory,
        reserve_bytes=reserve_mb * 1024 * 1024,
        minimum_archives=minimum_archives,
        disposable_spool_directories=tuple(spool_directories),
    )


__all__ = [
    "StorageRecoveryReport",
    "reclaim_backup_space",
    "reclaim_from_environment",
]
