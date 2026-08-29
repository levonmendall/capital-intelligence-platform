"""Fail-closed resource guard for the production-context screening handoff.

This module is deliberately independent from CIO, strategy, evidence, and screening
semantics. It only observes the Linux process/container resource boundary, attempts a
bounded reclaim of already-released file cache, trims already-unreferenced heap memory,
and defers the expensive screening stream when the governed runtime headroom is unsafe.
"""

from __future__ import annotations

import ctypes
import gc
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES = 640 * 1024 * 1024
DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES = 64 * 1024 * 1024
SCREENING_RECLAIM_MARGIN_BYTES = 32 * 1024 * 1024
SCREENING_RECLAIM_MAX_BYTES_PER_ATTEMPT = 256 * 1024 * 1024
SCREENING_RECLAIM_MAX_ATTEMPTS = 3


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
class ScreeningFileCacheReclaimResult:
    attempted: bool
    supported: bool
    attempt_count: int
    requested_bytes: int
    reclaimed_bytes: int
    current_before_bytes: int | None
    current_after_bytes: int | None
    inactive_file_before_bytes: int | None
    inactive_file_after_bytes: int | None
    effective: bool
    error_type: str | None
    snapshot: ScreeningResourceSnapshot


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
    result: dict[str, int] = {}
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            value = int(parts[1])
        except ValueError:
            continue
        if value >= 0:
            result[parts[0]] = value
    return result


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


def _inactive_file_bytes(*, root: Path = Path("/sys/fs/cgroup")) -> int | None:
    stat = _read_key_values(root / "memory.stat")
    if stat:
        return stat.get("inactive_file")
    legacy = _read_key_values(root / "memory" / "memory.stat")
    if legacy:
        return legacy.get("total_inactive_file", legacy.get("inactive_file"))
    return None


def _write_cgroup_reclaim(*, root: Path, requested_bytes: int) -> tuple[bool, str | None]:
    if requested_bytes <= 0:
        return False, None
    path = root / "memory.reclaim"
    if not path.exists():
        return False, "UnsupportedCgroupReclaim"
    try:
        with path.open("w", encoding="ascii") as handle:
            handle.write(str(requested_bytes))
            handle.flush()
    except OSError as error:
        return False, type(error).__name__
    return True, None


def _safe_log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-screening-resource-guard",
                "timestamp": time.time(),
                "credential_safe": True,
                "paper_only": True,
                "real_money_authorized": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


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


def reclaim_released_file_cache_for_screening(
    *,
    values: Mapping[str, str] | None = None,
    root: Path = Path("/sys/fs/cgroup"),
    initial_snapshot: ScreeningResourceSnapshot | None = None,
) -> ScreeningFileCacheReclaimResult:
    """Boundedly reclaim inactive cgroup file cache before terminal screening.

    The reclaim is operational and advisory. It is attempted only when the existing
    governed screening headroom is already below its unchanged minimum and cgroup memory
    accounting reports inactive file cache that can plausibly satisfy the deficit. Each
    request is capped at 256 MiB and at most three synchronous attempts are allowed. The
    caller must still run the normal fail-closed headroom check on the post-reclaim
    snapshot; unsupported, failed, or ineffective reclaim never changes that authority.
    """

    resolved = os.environ if values is None else values
    before = initial_snapshot or screening_resource_snapshot(values=resolved, root=root)
    current = before.container_current_bytes
    limit = before.container_limit_bytes
    inactive_before = _inactive_file_bytes(root=root)
    if current is None or limit is None:
        return ScreeningFileCacheReclaimResult(
            attempted=False,
            supported=False,
            attempt_count=0,
            requested_bytes=0,
            reclaimed_bytes=0,
            current_before_bytes=current,
            current_after_bytes=current,
            inactive_file_before_bytes=inactive_before,
            inactive_file_after_bytes=inactive_before,
            effective=True,
            error_type=None,
            snapshot=before,
        )

    target_current = max(
        0,
        limit
        - before.diagnostic_memory_reserve_bytes
        - before.minimum_governed_headroom_bytes,
    )
    if current <= target_current:
        return ScreeningFileCacheReclaimResult(
            attempted=False,
            supported=(root / "memory.reclaim").exists(),
            attempt_count=0,
            requested_bytes=0,
            reclaimed_bytes=0,
            current_before_bytes=current,
            current_after_bytes=current,
            inactive_file_before_bytes=inactive_before,
            inactive_file_after_bytes=inactive_before,
            effective=True,
            error_type=None,
            snapshot=before,
        )

    total_requested = 0
    attempt_count = 0
    error_type: str | None = None
    snapshot = before
    inactive = inactive_before
    supported = (root / "memory.reclaim").exists()

    while attempt_count < SCREENING_RECLAIM_MAX_ATTEMPTS:
        current = snapshot.container_current_bytes
        if current is None or current <= target_current:
            break
        if inactive is None or inactive <= 0:
            break
        overage = current - target_current
        requested = min(
            SCREENING_RECLAIM_MAX_BYTES_PER_ATTEMPT,
            inactive,
            overage + SCREENING_RECLAIM_MARGIN_BYTES,
        )
        if requested <= 0:
            break

        previous_current = current
        attempted, write_error = _write_cgroup_reclaim(
            root=root,
            requested_bytes=requested,
        )
        supported = supported and attempted if write_error is None else supported
        if not attempted:
            error_type = write_error
            break

        attempt_count += 1
        total_requested += requested
        snapshot = screening_resource_snapshot(values=resolved, root=root)
        inactive = _inactive_file_bytes(root=root)
        _safe_log(
            "screening_file_cache_reclaim_attempted",
            attempt_number=attempt_count,
            requested_bytes=requested,
            total_requested_bytes=total_requested,
            container_current_before_bytes=previous_current,
            container_current_after_bytes=snapshot.container_current_bytes,
            inactive_file_before_bytes=inactive_before,
            inactive_file_after_bytes=inactive,
            governed_headroom_after_bytes=snapshot.governed_headroom_bytes,
            minimum_governed_headroom_bytes=snapshot.minimum_governed_headroom_bytes,
            advisory_only=True,
        )
        after_current = snapshot.container_current_bytes
        if after_current is None or after_current <= target_current:
            break
        if after_current >= previous_current:
            break

    after_current = snapshot.container_current_bytes
    reclaimed = (
        max(0, before.container_current_bytes - after_current)
        if before.container_current_bytes is not None and after_current is not None
        else 0
    )
    effective = (
        snapshot.governed_headroom_bytes is None
        or snapshot.governed_headroom_bytes
        >= snapshot.minimum_governed_headroom_bytes
    )
    result = ScreeningFileCacheReclaimResult(
        attempted=attempt_count > 0,
        supported=supported,
        attempt_count=attempt_count,
        requested_bytes=total_requested,
        reclaimed_bytes=reclaimed,
        current_before_bytes=before.container_current_bytes,
        current_after_bytes=after_current,
        inactive_file_before_bytes=inactive_before,
        inactive_file_after_bytes=inactive,
        effective=effective,
        error_type=error_type,
        snapshot=snapshot,
    )
    _safe_log(
        "screening_file_cache_reclaim_completed",
        attempted=result.attempted,
        supported=result.supported,
        attempt_count=result.attempt_count,
        requested_bytes=result.requested_bytes,
        reclaimed_bytes=result.reclaimed_bytes,
        current_before_bytes=result.current_before_bytes,
        current_after_bytes=result.current_after_bytes,
        inactive_file_before_bytes=result.inactive_file_before_bytes,
        inactive_file_after_bytes=result.inactive_file_after_bytes,
        effective=result.effective,
        error_type=result.error_type,
        advisory_only=True,
    )
    return result


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
    """Reclaim released cache, then fail closed if governed headroom is still unsafe."""

    resolved = os.environ if values is None else values
    snapshot = screening_resource_snapshot(values=resolved, root=root)
    headroom = snapshot.governed_headroom_bytes
    if headroom is not None and headroom < snapshot.minimum_governed_headroom_bytes:
        reclaim = reclaim_released_file_cache_for_screening(
            values=resolved,
            root=root,
            initial_snapshot=snapshot,
        )
        snapshot = reclaim.snapshot
        headroom = snapshot.governed_headroom_bytes
    if headroom is not None and headroom < snapshot.minimum_governed_headroom_bytes:
        raise ScreeningResourceDeferred(snapshot)
    return snapshot


__all__ = [
    "DEFAULT_DIAGNOSTIC_MEMORY_RESERVE_BYTES",
    "DEFAULT_SCREENING_MIN_GOVERNED_HEADROOM_BYTES",
    "SCREENING_RECLAIM_MARGIN_BYTES",
    "SCREENING_RECLAIM_MAX_ATTEMPTS",
    "SCREENING_RECLAIM_MAX_BYTES_PER_ATTEMPT",
    "ScreeningFileCacheReclaimResult",
    "ScreeningResourceDeferred",
    "ScreeningResourceSnapshot",
    "ensure_screening_headroom",
    "reclaim_released_file_cache_for_screening",
    "screening_resource_snapshot",
    "trim_released_heap",
]
