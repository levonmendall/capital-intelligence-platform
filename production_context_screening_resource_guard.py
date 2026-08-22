"""Fail-closed resource guard for the production-context screening handoff.

This module is deliberately independent from CIO, strategy, evidence, and screening
semantics. It only observes the Linux process/container resource boundary, attempts a
best-effort release of already-unreferenced heap memory, and defers the expensive
screening stream when the governed runtime headroom is unsafe.
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


def ensure_screening_headroom(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
) -> ScreeningResourceSnapshot:
    """Fail closed only when a finite cgroup limit proves governed headroom unsafe."""

    snapshot = screening_resource_snapshot(values=values, root=root)
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
