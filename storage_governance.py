"""Govern non-authoritative persistent storage used by the production runtime.

This module has no investment, CIO, construction, execution, or real-money authority.
It only protects the persistent filesystem reserve needed to complete governed work.
Canonical portfolio state, append-only decision lineage, backups, and current decision
evidence are never reclaimed here.

The historical market-history database is a rebuildable performance cache. It may be
checkpointed or reset when required to preserve the configured filesystem reserve or
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
_DEFAULT_HISTORICAL_CACHE_MAX_MB = 4096
_DEFAULT_HISTORICAL_WAL_MAX_MB = 64
_HISTORICAL_CACHE_FRACTION_OF_FILESYSTEM = 0.20
_MINIMUM_DYNAMIC_CACHE_MB = 256


class StorageCapacityError(RuntimeError):
    """Raised when governed free-space reserve cannot be established safely."""


@dataclass(frozen=True, slots=True)
class StorageCapacitySnapshot:
    root: Path
    total_bytes: int
    free_bytes: int
    reserve_bytes: int
    historical_cache_bytes: int
    historical_cache_limit_bytes: int
    historical_cache_reset: bool


def _positive_mb(values: Mapping[str, str], key: str, default: int) -> int:
    raw = str(values.get(key, "") or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError as error:
        raise StorageCapacityError(f"{key} must be an integer number of MiB") from error
    if parsed <= 0:
        raise StorageCapacityError(f"{key} must be positive")
    return parsed


def _data_root(values: Mapping[str, str]) -> Path | None:
    raw = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


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


def _reserve_bytes(values: Mapping[str, str]) -> int:
    return _positive_mb(
        values,
        "CAPITAL_INTELLIGENCE_STORAGE_RESERVE_MB",
        _DEFAULT_STORAGE_RESERVE_MB,
    ) * _MIB


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
    """Establish the filesystem reserve before governed CIO work can start.

    Only the rebuildable historical cache may be reclaimed here. If that is not enough,
    startup fails closed instead of allowing a later partial reference/evidence write.
    """

    environment = dict(os.environ if values is None else values)
    root = _data_root(environment)
    if root is None:
        return None
    root.mkdir(parents=True, exist_ok=True)

    reserve = _reserve_bytes(environment)
    usage = shutil.disk_usage(root)
    if reserve >= usage.total:
        raise StorageCapacityError(
            "configured persistent-storage reserve is not smaller than filesystem capacity"
        )

    reset = checkpoint_historical_cache(root, environment)
    cache_limit = _historical_cache_limit_bytes(root, environment)
    cache_bytes = historical_cache_footprint_bytes(root)
    if cache_bytes > cache_limit:
        reset = _reset_historical_cache(root) or reset
        cache_bytes = historical_cache_footprint_bytes(root)

    usage = shutil.disk_usage(root)
    if usage.free < reserve and cache_bytes:
        reset = _reset_historical_cache(root) or reset
        cache_bytes = historical_cache_footprint_bytes(root)
        usage = shutil.disk_usage(root)

    if usage.free < reserve:
        raise StorageCapacityError(
            "persistent storage capacity insufficient after safe reclamation: "
            f"free_bytes={usage.free} reserve_bytes={reserve}"
        )

    return StorageCapacitySnapshot(
        root=root,
        total_bytes=usage.total,
        free_bytes=usage.free,
        reserve_bytes=reserve,
        historical_cache_bytes=cache_bytes,
        historical_cache_limit_bytes=cache_limit,
        historical_cache_reset=reset,
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
    reserve = _reserve_bytes(values)
    cache_limit = _historical_cache_limit_bytes(root, values)
    cache_bytes = historical_cache_footprint_bytes(root)
    if cache_bytes >= cache_limit or usage.free < reserve:
        _reset_historical_cache(root)
        usage = shutil.disk_usage(root)
    if usage.free < reserve:
        raise StorageCapacityError(
            "historical cache write refused to preserve persistent-storage reserve"
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
    if (
        historical_cache_footprint_bytes(root) > cache_limit
        or usage.free < _reserve_bytes(values)
    ):
        # SQLite row deletion does not reliably release filesystem blocks without a
        # VACUUM-sized temporary copy. Resetting this rebuildable cache is the narrow,
        # immediately reclaiming option under disk pressure.
        _reset_historical_cache(root)


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
    "checkpoint_historical_cache",
    "historical_cache_footprint_bytes",
    "install_persistent_history_storage_governance",
    "preflight_storage_capacity",
]
