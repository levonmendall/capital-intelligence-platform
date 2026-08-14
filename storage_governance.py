"""Govern non-authoritative persistent storage used by the production runtime.

This module has no investment, CIO, construction, execution, or real-money authority.
It only protects the persistent filesystem capacity needed to complete governed work.
Canonical portfolio state, append-only decision lineage, backups, and current decision
evidence are never reclaimed here.

The historical market-history database is a rebuildable performance cache. It may be
checkpointed or reset when required to preserve the projected all-market working set or
its own bounded footprint. Resetting it never grants data freshness; callers return to
the existing provider/evidence path and remain fail closed.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Type

_MIB = 1024 * 1024
_DEFAULT_STORAGE_RESERVE_MB = 1024
_DEFAULT_REFERENCE_PUBLISH_HEADROOM_MB = 2048
_DEFAULT_RUNTIME_WORKSPACE_HEADROOM_MB = 4096
_DEFAULT_HISTORICAL_CACHE_MAX_MB = 4096
_DEFAULT_HISTORICAL_WAL_MAX_MB = 64
_HISTORICAL_CACHE_FRACTION_OF_FILESYSTEM = 0.20
_MINIMUM_DYNAMIC_CACHE_MB = 256


class StorageCapacityError(RuntimeError):
    """Raised when governed free-space capacity cannot be established safely."""


@dataclass(frozen=True, slots=True)
class StorageRequirement:
    reserve_bytes: int
    reference_publish_headroom_bytes: int
    runtime_workspace_headroom_bytes: int

    @property
    def required_free_bytes(self) -> int:
        return (
            self.reserve_bytes
            + self.reference_publish_headroom_bytes
            + self.runtime_workspace_headroom_bytes
        )


@dataclass(frozen=True, slots=True)
class StorageCapacitySnapshot:
    root: Path
    total_bytes: int
    free_bytes: int
    reserve_bytes: int
    historical_cache_bytes: int
    historical_cache_limit_bytes: int
    historical_cache_reset: bool
    free_before_bytes: int = 0
    reference_publish_headroom_bytes: int = 0
    runtime_workspace_headroom_bytes: int = 0
    required_free_bytes: int = 0
    workspace_root: Path | None = None
    workspace_shared_filesystem: bool | None = None

    @staticmethod
    def _mib(value: int) -> int:
        return int(value // _MIB)

    def telemetry(self) -> dict[str, object]:
        """Return credential-safe scalar capacity telemetry for logs/diagnostics."""

        return {
            "data_root": str(self.root),
            "workspace_root": str(self.workspace_root) if self.workspace_root else None,
            "workspace_shared_filesystem": self.workspace_shared_filesystem,
            "filesystem_total_mb": self._mib(self.total_bytes),
            "filesystem_free_before_mb": self._mib(self.free_before_bytes),
            "filesystem_free_mb": self._mib(self.free_bytes),
            "storage_reserve_mb": self._mib(self.reserve_bytes),
            "reference_publish_headroom_mb": self._mib(
                self.reference_publish_headroom_bytes
            ),
            "runtime_workspace_headroom_mb": self._mib(
                self.runtime_workspace_headroom_bytes
            ),
            "required_free_mb": self._mib(self.required_free_bytes),
            "historical_cache_mb": self._mib(self.historical_cache_bytes),
            "historical_cache_limit_mb": self._mib(
                self.historical_cache_limit_bytes
            ),
            "historical_cache_reset": self.historical_cache_reset,
        }


def _integer_mb(
    values: Mapping[str, str],
    key: str,
    default: int,
    *,
    allow_zero: bool = False,
) -> int:
    raw = str(values.get(key, "") or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as error:
        raise StorageCapacityError(f"{key} must be an integer number of MiB") from error
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise StorageCapacityError(f"{key} must be {qualifier}")
    return parsed


def _positive_mb(values: Mapping[str, str], key: str, default: int) -> int:
    return _integer_mb(values, key, default)


def _nonnegative_mb(values: Mapping[str, str], key: str, default: int) -> int:
    return _integer_mb(values, key, default, allow_zero=True)


def _data_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _workspace_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("TMPDIR", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _same_filesystem(left: Path, right: Path) -> bool:
    return left.stat().st_dev == right.stat().st_dev


def _verify_workspace_filesystem(
    root: Path,
    values: Mapping[str, str],
) -> tuple[Path | None, bool | None]:
    workspace = _workspace_root(values)
    if workspace is None:
        return None, None
    workspace.mkdir(parents=True, exist_ok=True)
    shared = _same_filesystem(root, workspace)
    if not shared:
        root_usage = shutil.disk_usage(root)
        workspace_usage = shutil.disk_usage(workspace)
        raise StorageCapacityError(
            "disposable workspace is not on the governed persistent filesystem: "
            f"data_root={root} workspace={workspace} "
            f"data_root_total_bytes={root_usage.total} "
            f"workspace_total_bytes={workspace_usage.total}"
        )
    return workspace, True


def _historical_database(root: Path) -> Path:
    return root / "historical_evidence" / "market_history.sqlite3"


def _historical_paths(root: Path) -> tuple[Path, Path, Path]:
    database = _historical_database(root)
    return database, Path(f"{database}-wal"), Path(f"{database}-shm")


def historical_cache_footprint_bytes(root: Path) -> int:
    total = 0
    for path in _historical_paths(root):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total


def _historical_cache_limit_bytes(root: Path, values: Mapping[str, str]) -> int:
    configured = _positive_mb(
        values,
        "CAPITAL_INTELLIGENCE_HISTORICAL_CACHE_MAX_MB",
        _DEFAULT_HISTORICAL_CACHE_MAX_MB,
    ) * _MIB
    usage = shutil.disk_usage(root)
    dynamic = max(
        _MINIMUM_DYNAMIC_CACHE_MB * _MIB,
        int(usage.total * _HISTORICAL_CACHE_FRACTION_OF_FILESYSTEM),
    )
    return min(configured, dynamic)


def _storage_requirement(values: Mapping[str, str]) -> StorageRequirement:
    return StorageRequirement(
        reserve_bytes=_positive_mb(
            values,
            "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB",
            _DEFAULT_STORAGE_RESERVE_MB,
        )
        * _MIB,
        reference_publish_headroom_bytes=_nonnegative_mb(
            values,
            "CAPITAL_INTELLIGENCE_REFERENCE_PUBLISH_HEADROOM_MB",
            _DEFAULT_REFERENCE_PUBLISH_HEADROOM_MB,
        )
        * _MIB,
        runtime_workspace_headroom_bytes=_nonnegative_mb(
            values,
            "CAPITAL_INTELLIGENCE_RUNTIME_WORKSPACE_HEADROOM_MB",
            _DEFAULT_RUNTIME_WORKSPACE_HEADROOM_MB,
        )
        * _MIB,
    )


def _reserve_bytes(values: Mapping[str, str]) -> int:
    """Compatibility helper returning the full governed working-set requirement."""

    return _storage_requirement(values).required_free_bytes


def _wal_limit_bytes(values: Mapping[str, str]) -> int:
    return _positive_mb(
        values,
        "CAPITAL_INTELLIGENCE_HISTORICAL_WAL_MAX_MB",
        _DEFAULT_HISTORICAL_WAL_MAX_MB,
    ) * _MIB


def _reset_historical_cache(root: Path) -> bool:
    """Delete only the rebuildable historical cache and SQLite sidecars."""

    changed = False
    database, wal, shm = _historical_paths(root)
    for path in (wal, shm, database):
        if path.is_symlink():
            continue
        try:
            if path.is_file():
                path.unlink()
                changed = True
        except FileNotFoundError:
            continue
    return changed


def checkpoint_historical_cache(root: Path, values: Mapping[str, str]) -> bool:
    """Bound WAL growth without VACUUM or temporary full-database copies.

    A checkpoint is attempted only when the rebuildable database already exists. If an
    interrupted/ENOSPC database cannot be opened, it is reset rather than risking a
    repair that could consume additional temporary disk.
    """

    database = _historical_database(root)
    if not database.is_file() or database.is_symlink():
        return False
    limit = _wal_limit_bytes(values)
    try:
        connection = sqlite3.connect(str(database), timeout=5.0)
        try:
            connection.execute(f"PRAGMA journal_size_limit={limit}")
            connection.execute("PRAGMA wal_autocheckpoint=1000")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return _reset_historical_cache(root)
    return False


def preflight_storage_capacity(
    values: Mapping[str, str] | None = None,
) -> StorageCapacitySnapshot | None:
    """Establish projected all-market working-set capacity before CIO work starts.

    The requirement combines a base reserve, reference-publication headroom, and
    disposable runtime-workspace headroom. Only the rebuildable historical cache may be
    reclaimed here. If that is not enough, startup fails closed before a later partial
    reference/evidence write can occur.
    """

    environment = dict(os.environ if values is None else values)
    root = _data_root(environment)
    if root is None:
        return None
    root.mkdir(parents=True, exist_ok=True)

    workspace, shared_filesystem = _verify_workspace_filesystem(root, environment)
    requirement = _storage_requirement(environment)
    usage_before = shutil.disk_usage(root)
    required = requirement.required_free_bytes
    if required >= usage_before.total:
        raise StorageCapacityError(
            "projected all-market storage requirement is not smaller than filesystem "
            f"capacity: total_bytes={usage_before.total} required_free_bytes={required}"
        )

    reset = checkpoint_historical_cache(root, environment)
    cache_limit = _historical_cache_limit_bytes(root, environment)
    cache_bytes = historical_cache_footprint_bytes(root)
    if cache_bytes > cache_limit:
        reset = _reset_historical_cache(root) or reset
        cache_bytes = historical_cache_footprint_bytes(root)

    usage = shutil.disk_usage(root)
    if usage.free < required and cache_bytes:
        reset = _reset_historical_cache(root) or reset
        cache_bytes = historical_cache_footprint_bytes(root)
        usage = shutil.disk_usage(root)

    if usage.free < required:
        raise StorageCapacityError(
            "persistent storage capacity insufficient for governed all-market cycle "
            "after safe reclamation: "
            f"free_bytes={usage.free} required_free_bytes={required} "
            f"storage_reserve_bytes={requirement.reserve_bytes} "
            f"reference_publish_headroom_bytes="
            f"{requirement.reference_publish_headroom_bytes} "
            f"runtime_workspace_headroom_bytes="
            f"{requirement.runtime_workspace_headroom_bytes}"
        )

    return StorageCapacitySnapshot(
        root=root,
        total_bytes=usage.total,
        free_bytes=usage.free,
        reserve_bytes=requirement.reserve_bytes,
        historical_cache_bytes=cache_bytes,
        historical_cache_limit_bytes=cache_limit,
        historical_cache_reset=reset,
        free_before_bytes=usage_before.free,
        reference_publish_headroom_bytes=requirement.reference_publish_headroom_bytes,
        runtime_workspace_headroom_bytes=requirement.runtime_workspace_headroom_bytes,
        required_free_bytes=required,
        workspace_root=workspace,
        workspace_shared_filesystem=shared_filesystem,
    )


def _prepare_historical_write(store: object) -> None:
    path = getattr(store, "path", None)
    values = dict(getattr(store, "_values", {}) or {})
    if not isinstance(path, Path):
        return
    root = path.parent.parent
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_historical_cache(root, values)
    usage = shutil.disk_usage(root)
    required = _storage_requirement(values).required_free_bytes
    cache_limit = _historical_cache_limit_bytes(root, values)
    cache_bytes = historical_cache_footprint_bytes(root)
    if cache_bytes >= cache_limit or usage.free < required:
        _reset_historical_cache(root)
        usage = shutil.disk_usage(root)
    if usage.free < required:
        raise StorageCapacityError(
            "historical cache write refused to preserve projected all-market "
            f"working-set capacity: free_bytes={usage.free} "
            f"required_free_bytes={required}"
        )


def _finish_historical_write(store: object) -> None:
    path = getattr(store, "path", None)
    values = dict(getattr(store, "_values", {}) or {})
    if not isinstance(path, Path):
        return
    root = path.parent.parent
    checkpoint_historical_cache(root, values)
    cache_limit = _historical_cache_limit_bytes(root, values)
    usage = shutil.disk_usage(root)
    required = _storage_requirement(values).required_free_bytes
    if historical_cache_footprint_bytes(root) > cache_limit or usage.free < required:
        # SQLite row deletion does not reliably release filesystem blocks without a
        # VACUUM-sized temporary copy. Resetting this rebuildable cache is the narrow,
        # immediately reclaiming option under disk pressure.
        _reset_historical_cache(root)
        usage = shutil.disk_usage(root)
    if usage.free < required:
        raise StorageCapacityError(
            "historical cache completion could not preserve projected all-market "
            f"working-set capacity: free_bytes={usage.free} "
            f"required_free_bytes={required}"
        )


def install_persistent_history_storage_governance(
    store_type: Type[object] | None = None,
) -> None:
    """Install idempotent WAL/footprint governance around the history cache."""

    if store_type is None:
        from operations.persistent_historical_evidence import (  # local import by design
            PersistentHistoricalEvidenceStore,
        )

        store_type = PersistentHistoricalEvidenceStore

    current_connect = getattr(store_type, "_connect")
    if not bool(getattr(current_connect, "storage_governance", False)):

        def governed_connect(self):
            connection = current_connect(self)
            values = dict(getattr(self, "_values", {}) or {})
            limit = _wal_limit_bytes(values)
            connection.execute(f"PRAGMA journal_size_limit={limit}")
            connection.execute("PRAGMA wal_autocheckpoint=1000")
            return connection

        governed_connect.storage_governance = True  # type: ignore[attr-defined]
        setattr(store_type, "_connect", governed_connect)

    current_merge = getattr(store_type, "merge")
    if bool(getattr(current_merge, "storage_governance", False)):
        return

    def governed_merge(self, *args, **kwargs):
        _prepare_historical_write(self)
        result = current_merge(self, *args, **kwargs)
        _finish_historical_write(self)
        return result

    governed_merge.storage_governance = True  # type: ignore[attr-defined]
    setattr(store_type, "merge", governed_merge)


__all__ = [
    "StorageCapacityError",
    "StorageCapacitySnapshot",
    "StorageRequirement",
    "checkpoint_historical_cache",
    "historical_cache_footprint_bytes",
    "install_persistent_history_storage_governance",
    "preflight_storage_capacity",
]
