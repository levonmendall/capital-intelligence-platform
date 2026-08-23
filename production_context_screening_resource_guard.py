"""Fail-closed resource guard for the production-context screening handoff.

This module is deliberately independent from CIO, strategy, evidence, and screening
semantics. It only observes the Linux process/container resource boundary, attempts a
best-effort release of already-unreferenced heap memory, and defers the expensive
screening stream when the governed runtime headroom is unsafe.

The serving watchdog distinguishes reclaimable Linux page cache from the active working
set while retaining an independent raw-current hard ceiling. Screening must use the same
accounting model: treating all of ``memory.current`` as irrecoverable can reject a safe
handoff before screening even starts. The limits themselves are not relaxed here.
"""

from __future__ import annotations

import ctypes
import gc
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from operations.reclaimable_memory_guard import memory_boundaries

DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES = 640 * 1024 * 1024
DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES = 64 * 1024 * 1024
_DEFAULT_MEMORY_HIGH_WATER_FRACTION = 0.70
_MEMORY_HIGH_WATER_FRACTION_ENV = (
    "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION"
)


@dataclass(frozen=True, slots=True)
class ScreeningResourceSnapshot:
    container_current_bytes: int | None
    container_limit_bytes: int | None
    diagnostic_memory_reserve_bytes: int
    governed_headroom_bytes: int | None
    minimum_governed_headroom_bytes: int
    inactive_file_bytes: int | None = None
    working_set_bytes: int | None = None
    working_set_boundary_bytes: int | None = None
    raw_hard_boundary_bytes: int | None = None
    raw_hard_headroom_bytes: int | None = None
    memory_accounting_source: str = "unavailable"

    @property
    def working_set_boundary_reached(self) -> bool:
        return bool(
            self.working_set_bytes is not None
            and self.working_set_boundary_bytes is not None
            and self.working_set_bytes >= self.working_set_boundary_bytes
        )

    @property
    def raw_hard_boundary_reached(self) -> bool:
        return bool(
            self.container_current_bytes is not None
            and self.raw_hard_boundary_bytes is not None
            and self.container_current_bytes >= self.raw_hard_boundary_bytes
        )

    def detail(self) -> str:
        return (
            f"container_current_bytes={self.container_current_bytes}; "
            f"container_limit_bytes={self.container_limit_bytes}; "
            f"inactive_file_bytes={self.inactive_file_bytes}; "
            f"working_set_bytes={self.working_set_bytes}; "
            f"working_set_boundary_bytes={self.working_set_boundary_bytes}; "
            f"raw_hard_boundary_bytes={self.raw_hard_boundary_bytes}; "
            f"raw_hard_headroom_bytes={self.raw_hard_headroom_bytes}; "
            f"diagnostic_memory_reserve_bytes={self.diagnostic_memory_reserve_bytes}; "
            f"governed_headroom_bytes={self.governed_headroom_bytes}; "
            f"minimum_governed_headroom_bytes={self.minimum_governed_headroom_bytes}; "
            f"memory_accounting_source={self.memory_accounting_source}"
        )


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


def _memory_high_water_fraction(values: Mapping[str, str]) -> float:
    raw = str(values.get(_MEMORY_HIGH_WATER_FRACTION_ENV, "")).strip()
    if not raw:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    try:
        parsed = float(raw)
    except ValueError:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    if not 0.5 <= parsed < 0.9:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    return parsed


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


def _cgroup_usage(
    *, root: Path = Path("/sys/fs/cgroup")
) -> tuple[int | None, int | None, int | None, str]:
    current = _read_counter(root / "memory.current")
    limit = _read_counter(root / "memory.max")
    if current is not None and limit is not None and limit > 0:
        stat = _read_key_values(root / "memory.stat")
        inactive_file = stat.get("inactive_file")
        return current, limit, inactive_file, "cgroup_v2"

    legacy = root / "memory"
    current = _read_counter(legacy / "memory.usage_in_bytes")
    limit = _read_counter(legacy / "memory.limit_in_bytes")
    if current is not None and limit is not None and 0 < limit < (1 << 60):
        stat = _read_key_values(legacy / "memory.stat")
        inactive_file = stat.get("total_inactive_file", stat.get("inactive_file"))
        return current, limit, inactive_file, "cgroup_v1"
    return None, None, None, "unavailable"


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
    current, limit, inactive_file, source = _cgroup_usage(root=root)

    governed_headroom = None
    working_set = None
    working_set_boundary = None
    raw_hard_boundary = None
    raw_hard_headroom = None
    if current is not None and limit is not None:
        # A missing memory.stat cannot manufacture reclaimable headroom. Falling back to
        # raw current is deliberately conservative and preserves fail-closed behavior.
        reclaimable = 0 if inactive_file is None else min(current, inactive_file)
        working_set = max(0, current - reclaimable)
        boundaries = memory_boundaries(
            max(1, limit // 1024),
            working_set_fraction=_memory_high_water_fraction(resolved),
            working_set_reserve_kib=max(0, reserve // 1024),
            values=resolved,
        )
        working_set_boundary = boundaries.working_set_kib * 1024
        raw_hard_boundary = boundaries.raw_hard_kib * 1024
        governed_headroom = max(0, working_set_boundary - working_set)
        raw_hard_headroom = max(0, raw_hard_boundary - current)

    return ScreeningResourceSnapshot(
        container_current_bytes=current,
        container_limit_bytes=limit,
        diagnostic_memory_reserve_bytes=reserve,
        governed_headroom_bytes=governed_headroom,
        minimum_governed_headroom_bytes=minimum,
        inactive_file_bytes=inactive_file,
        working_set_bytes=working_set,
        working_set_boundary_bytes=working_set_boundary,
        raw_hard_boundary_bytes=raw_hard_boundary,
        raw_hard_headroom_bytes=raw_hard_headroom,
        memory_accounting_source=source,
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


def ensure_screening_headroom(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
) -> ScreeningResourceSnapshot:
    """Fail closed against the same dual memory boundaries as the Render watchdog."""

    snapshot = screening_resource_snapshot(values=values, root=root)
    if snapshot.raw_hard_boundary_reached or snapshot.working_set_boundary_reached:
        raise ScreeningResourceDeferred(snapshot)
    headroom = snapshot.governed_headroom_bytes
    if headroom is not None and headroom < snapshot.minimum_governed_headroom_bytes:
        raise ScreeningResourceDeferred(snapshot)
    return snapshot


__all__ = [
    "DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES",
    "DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES",
    "ScreeningResourceDeferred",
    "ScreeningResourceSnapshot",
    "ensure_screening_headroom",
    "screening_resource_snapshot",
    "trim_released_heap",
]
