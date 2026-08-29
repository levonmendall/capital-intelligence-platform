"""Fail-closed resource guard for the production-context screening handoff.

This module is deliberately independent from CIO, strategy, evidence, and screening
semantics. It only observes the Linux process/container resource boundary, attempts a
best-effort release of already-unreferenced heap memory and file cache, and defers the
expensive screening stream when the governed runtime headroom is unsafe.
"""

from __future__ import annotations

import ctypes
import gc
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES = 640 * 1024 * 1024
DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES = 64 * 1024 * 1024
_SCREENING_RECLAIM_MARGIN_BYTES = 32 * 1024 * 1024
_SCREENING_RECLAIM_MAX_BYTES = 256 * 1024 * 1024
_SCREENING_RECLAIM_MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class ScreeningResourceSnapshot:
    container_current_bytes: int | None
    container_limit_bytes: int | None
    diagnostic_memory_reserve_bytes: int
    governed_headroom_bytes: int | None
    minimum_governed_headroom_bytes: int

    def detail(self) -> str:
        return (
            f"container_current_bytes={self.container_current_bytes}; "
            f"container_limit_bytes={self.container_limit_bytes}; "
            f"diagnostic_memory_reserve_bytes={self.diagnostic_memory_reserve_bytes}; "
            f"governed_headroom_bytes={self.governed_headroom_bytes}; "
            f"minimum_governed_headroom_bytes={self.minimum_governed_headroom_bytes}"
        )


@dataclass(frozen=True, slots=True)
class ScreeningCacheReclaimResult:
    attempted: bool
    supported: bool
    attempt_count: int
    requested_bytes: int
    current_before_bytes: int | None
    current_after_bytes: int | None
    target_current_bytes: int | None
    inactive_file_before_bytes: int | None
    effective: bool
    error_type: str | None


class ScreeningResourceDeferred(RuntimeError):
    """The diagnostic must stop before screening because runtime headroom is unsafe."""

    reason = "insufficient_runtime_memory_for_screening"

    def __init__(self, snapshot: ScreeningResourceSnapshot) -> None:
        self.snapshot = snapshot
        super().__init__(f"{self.reason}: {snapshot.detail()}")


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    raw = str(values.get(name, "")).strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _read_counter(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _read_key_values(path: Path) -> dict[str, int]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parsed: dict[str, int] = {}
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        if value >= 0:
            parsed[parts[0]] = value
    return parsed


def _cgroup_usage(*, root: Path = Path("/sys/fs/cgroup")) -> tuple[int | None, int | None]:
    current = _read_counter(root / "memory.current")
    limit = _read_counter(root / "memory.max")
    if current is not None and limit is not None and limit > 0:
        return current, limit

    legacy = root / "memory"
    current = _read_counter(legacy / "memory.usage_in_bytes")
    limit = _read_counter(legacy / "memory.limit_in_bytes")
    if current is not None and limit is not None and 0 < limit < (1 << 60):
        return current, limit
    return None, None


def screening_resource_snapshot(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
) -> ScreeningResourceSnapshot:
    resolved = os.environ if values is None else values
    reserve = _positive_int(
        resolved,
        "CAPITAL_INTELLIGENCE_DIAGNOSTIC_MEMORY_RESERVE_BYTES",
        DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES,
    )
    minimum = _positive_int(
        resolved,
        "CAPITAL_INTELLIGENCE_SCREENING_MIN_GOVERNED_HEADROOM_BYTES",
        DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES,
    )
    current, limit = _cgroup_usage(root=root)
    governed_headroom = None
    if current is not None and limit is not None:
        governed_headroom = max(0, limit - current - reserve)
    return ScreeningResourceSnapshot(
        container_current_bytes=current,
        container_limit_bytes=limit,
        diagnostic_memory_reserve_bytes=reserve,
        governed_headroom_bytes=governed_headroom,
        minimum_governed_headroom_bytes=minimum,
    )


def trim_released_heap() -> bool:
    """Best-effort GC + glibc heap trim; never changes governed decision semantics."""

    gc.collect()
    try:
        libc = ctypes.CDLL(None)
        malloc_trim = getattr(libc, "malloc_trim", None)
        if malloc_trim is None:
            return False
        malloc_trim.argtypes = [ctypes.c_size_t]
        malloc_trim.restype = ctypes.c_int
        return bool(malloc_trim(0))
    except (AttributeError, OSError, TypeError, ValueError):
        return False


def _request_cgroup_v2_reclaim(root: Path, requested_bytes: int) -> None:
    reclaim_path = root / "memory.reclaim"
    with reclaim_path.open("w", encoding="ascii") as handle:
        handle.write(str(requested_bytes))
        handle.flush()


def reclaim_released_file_cache_for_screening(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
) -> ScreeningCacheReclaimResult:
    """Boundedly reclaim released cgroup-v2 file cache before screening admission.

    This is an operational recovery step only. It never changes the diagnostic reserve,
    minimum screening headroom, or any investment/evidence rule. Reclaim is attempted
    only when raw cgroup usage is above the exact existing admission target and the
    cgroup reports inactive file pages that can plausibly satisfy the request. Failure or
    unsupported reclaim remains fail-soft here because ``ensure_screening_headroom``
    immediately re-measures the unchanged boundary and still fails closed.
    """

    resolved = os.environ if values is None else values
    reserve = _positive_int(
        resolved,
        "CAPITAL_INTELLIGENCE_DIAGNOSTIC_MEMORY_RESERVE_BYTES",
        DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES,
    )
    minimum = _positive_int(
        resolved,
        "CAPITAL_INTELLIGENCE_SCREENING_MIN_GOVERNED_HEADROOM_BYTES",
        DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES,
    )
    current, limit = _cgroup_usage(root=root)
    reclaim_path = root / "memory.reclaim"
    supported = (
        (root / "memory.current").exists()
        and (root / "memory.max").exists()
        and reclaim_path.exists()
    )
    if current is None or limit is None:
        return ScreeningCacheReclaimResult(
            attempted=False,
            supported=supported,
            attempt_count=0,
            requested_bytes=0,
            current_before_bytes=current,
            current_after_bytes=current,
            target_current_bytes=None,
            inactive_file_before_bytes=None,
            effective=False,
            error_type=None,
        )

    target = max(0, limit - reserve - minimum)
    stat = _read_key_values(root / "memory.stat")
    inactive_before = stat.get("inactive_file")
    if current <= target:
        return ScreeningCacheReclaimResult(
            attempted=False,
            supported=supported,
            attempt_count=0,
            requested_bytes=0,
            current_before_bytes=current,
            current_after_bytes=current,
            target_current_bytes=target,
            inactive_file_before_bytes=inactive_before,
            effective=True,
            error_type=None,
        )
    if not supported or not isinstance(inactive_before, int) or inactive_before <= 0:
        return ScreeningCacheReclaimResult(
            attempted=False,
            supported=supported,
            attempt_count=0,
            requested_bytes=0,
            current_before_bytes=current,
            current_after_bytes=current,
            target_current_bytes=target,
            inactive_file_before_bytes=inactive_before,
            effective=False,
            error_type=(None if supported else "UnsupportedCgroupReclaim"),
        )

    before = current
    after = current
    requested_total = 0
    attempts = 0
    error_type: str | None = None
    while after > target and attempts < _SCREENING_RECLAIM_MAX_ATTEMPTS:
        stat = _read_key_values(root / "memory.stat")
        inactive = stat.get("inactive_file", 0)
        if inactive <= 0:
            break
        overage = max(1, after - target)
        requested = min(
            _SCREENING_RECLAIM_MAX_BYTES,
            inactive,
            overage + _SCREENING_RECLAIM_MARGIN_BYTES,
        )
        if requested <= 0:
            break
        attempts += 1
        requested_total += requested
        try:
            _request_cgroup_v2_reclaim(root, requested)
        except OSError as error:
            error_type = type(error).__name__
            break
        measured, _measured_limit = _cgroup_usage(root=root)
        if measured is None:
            break
        after = measured

    return ScreeningCacheReclaimResult(
        attempted=attempts > 0,
        supported=supported,
        attempt_count=attempts,
        requested_bytes=requested_total,
        current_before_bytes=before,
        current_after_bytes=after,
        target_current_bytes=target,
        inactive_file_before_bytes=inactive_before,
        effective=after <= target,
        error_type=error_type,
    )


def ensure_screening_headroom(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
) -> ScreeningResourceSnapshot:
    """Fail closed only when finite cgroup headroom remains unsafe after bounded reclaim."""

    reclaim_released_file_cache_for_screening(values=values, root=root)
    snapshot = screening_resource_snapshot(values=values, root=root)
    headroom = snapshot.governed_headroom_bytes
    if headroom is not None and headroom < snapshot.minimum_governed_headroom_bytes:
        raise ScreeningResourceDeferred(snapshot)
    return snapshot


__all__ = [
    "DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES",
    "DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES",
    "ScreeningCacheReclaimResult",
    "ScreeningResourceDeferred",
    "ScreeningResourceSnapshot",
    "ensure_screening_headroom",
    "reclaim_released_file_cache_for_screening",
    "screening_resource_snapshot",
    "trim_released_heap",
]
