"""Protect Render workers using reclaimable-aware and hard cgroup memory limits.

Linux cgroup ``memory.current`` includes reclaimable page cache. Treating that raw value as
an immediate worker-kill boundary can terminate a healthy data-intensive job even when the
kernel can reclaim most of the apparent pressure. The production guard therefore uses two
independent limits:

* a conservative working-set boundary based on ``memory.current - inactive_file``; and
* a higher raw-cgroup hard ceiling that still leaves explicit service headroom before the
  platform's absolute memory limit.

Cgroup-v2 accounting is resolved for the current process from ``/proc/self/cgroup`` and
``/proc/self/mountinfo``. This matters on managed runtimes that place the process in a nested
cgroup: reading the cgroup mount root can include memory owned by sibling workloads and can
also make ``memory.reclaim`` appear unavailable even when it exists for the process cgroup.
If process-cgroup resolution is unavailable or malformed, the guard falls back to the
historical root paths and remains fail-closed.

A raw-only hard-ceiling crossing gets a tightly bounded cgroup-v2 reclaim/re-measure sequence
before the child is terminated. The guard remeasures the exact same boundaries after every
attempt and remains fail-closed: working-set pressure, unavailable reclaim, reclaim errors,
or exhaustion of the bounded recovery attempts still cause termination. No threshold is
raised and no investment/evidence authority changes.

If cgroup memory.stat is unavailable the guard falls back to raw accounting, preserving the
previous fail-closed behavior. This module changes only operational resource supervision; it
cannot change evidence scope, CIO authority, investment thresholds, construction, execution,
or paper-only controls.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Event, Thread
from typing import Mapping

_DEFAULT_RENDER_LIMIT_MB = 2048.0
_DEFAULT_HARD_WATER_FRACTION = 0.90
_DEFAULT_HARD_RESERVE_MB = 192.0
_DEFAULT_POLL_SECONDS = 0.10
_RECLAIM_MARGIN_KIB = 32 * 1024
_RECLAIM_MAX_KIB = 256 * 1024
# Keep raw-only recovery synchronous and small: at most three 256 MiB requests, or 768 MiB
# requested in total, before fail-closed termination.
_RAW_RECLAIM_MAX_ATTEMPTS = 3
# Production wrapper uses this only to decide whether an otherwise ineffective raw reclaim
# should fall through to one bounded clean-file advisory pass.
_RAW_RECLAIM_MIN_PROGRESS_KIB = 4 * 1024

_CGROUP_V2_ROOT = Path("/sys/fs/cgroup")
_CGROUP_V2_CURRENT_PATH = _CGROUP_V2_ROOT / "memory.current"
_CGROUP_V2_MAX_PATH = _CGROUP_V2_ROOT / "memory.max"
_CGROUP_V2_EVENTS_PATH = _CGROUP_V2_ROOT / "memory.events"
_CGROUP_V2_STAT_PATH = _CGROUP_V2_ROOT / "memory.stat"
_CGROUP_V2_RECLAIM_PATH = _CGROUP_V2_ROOT / "memory.reclaim"
_PROC_SELF_CGROUP_PATH = Path("/proc/self/cgroup")
_PROC_SELF_MOUNTINFO_PATH = Path("/proc/self/mountinfo")
_MOUNTINFO_ESCAPE = re.compile(r"\\([0-7]{3})")

_HARD_FRACTION_ENV = "CAPITAL_INTELLIGENCE_RENDER_MEMORY_HARD_WATER_FRACTION"
_HARD_RESERVE_ENV = "CAPITAL_INTELLIGENCE_RENDER_MEMORY_HARD_RESERVE_MB"
_CONFIGURED_LIMIT_ENV = "CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB"


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    raw_current_kib: int | None
    limit_kib: int | None
    working_set_kib: int | None
    inactive_file_kib: int | None
    anon_kib: int | None
    file_kib: int | None
    kernel_kib: int | None
    source: str
    memory_events: tuple[tuple[str, int], ...] = ()
    active_file_kib: int | None = None


@dataclass(frozen=True, slots=True)
class MemoryBoundaries:
    working_set_kib: int
    raw_hard_kib: int


@dataclass(frozen=True, slots=True)
class MemoryReclaimResult:
    attempted: bool
    supported: bool
    requested_kib: int
    raw_before_kib: int | None
    raw_after_kib: int | None
    working_set_before_kib: int | None
    working_set_after_kib: int | None
    reclaimed_kib: int
    effective: bool
    error_type: str | None


@dataclass(frozen=True, slots=True)
class _CgroupV2Paths:
    current: Path
    maximum: Path
    events: Path
    stat: Path
    reclaim: Path
    process_scoped: bool


def _read_int(path: Path) -> int | None:
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


def _decode_mountinfo_path(value: str) -> str:
    return _MOUNTINFO_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _process_cgroup_v2_path(path: Path = _PROC_SELF_CGROUP_PATH) -> PurePosixPath | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3 or parts[0] != "0" or parts[1] != "":
            continue
        candidate = PurePosixPath(parts[2] or "/")
        return candidate if candidate.is_absolute() else None
    return None


def _resolve_process_cgroup_v2_directory(
    *,
    cgroup_path: Path = _PROC_SELF_CGROUP_PATH,
    mountinfo_path: Path = _PROC_SELF_MOUNTINFO_PATH,
) -> Path | None:
    """Resolve the current process's unified cgroup-v2 directory.

    A successful resolution is authoritative for this process. Callers must not climb to
    the parent/root cgroup if a process-scoped file is absent, because that could measure or
    reclaim memory belonging to sibling workloads.
    """

    process_path = _process_cgroup_v2_path(cgroup_path)
    if process_path is None:
        return None
    try:
        lines = mountinfo_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None

    for line in lines:
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        post_fields = after.split()
        pre_fields = before.split()
        if len(post_fields) < 1 or post_fields[0] != "cgroup2" or len(pre_fields) < 5:
            continue
        mount_root = PurePosixPath(_decode_mountinfo_path(pre_fields[3]))
        mount_point_text = _decode_mountinfo_path(pre_fields[4])
        mount_point = Path(mount_point_text)
        if not mount_root.is_absolute() or not mount_point.is_absolute():
            continue
        try:
            relative = process_path.relative_to(mount_root)
        except ValueError:
            continue
        parts = tuple(part for part in relative.parts if part not in ("", "."))
        return mount_point.joinpath(*parts)
    return None


def _cgroup_v2_paths() -> _CgroupV2Paths:
    directory = _resolve_process_cgroup_v2_directory()
    if directory is None:
        return _CgroupV2Paths(
            current=_CGROUP_V2_CURRENT_PATH,
            maximum=_CGROUP_V2_MAX_PATH,
            events=_CGROUP_V2_EVENTS_PATH,
            stat=_CGROUP_V2_STAT_PATH,
            reclaim=_CGROUP_V2_RECLAIM_PATH,
            process_scoped=False,
        )
    return _CgroupV2Paths(
        current=directory / "memory.current",
        maximum=directory / "memory.max",
        events=directory / "memory.events",
        stat=directory / "memory.stat",
        reclaim=directory / "memory.reclaim",
        process_scoped=True,
    )


def _reclaim_path() -> Path:
    # Preserve the long-standing test/integration seam that replaces this constant directly.
    if _CGROUP_V2_RECLAIM_PATH != _CGROUP_V2_ROOT / "memory.reclaim":
        return _CGROUP_V2_RECLAIM_PATH
    return _cgroup_v2_paths().reclaim


def _configured_limit_kib(values: Mapping[str, str]) -> int | None:
    raw = str(values.get(_CONFIGURED_LIMIT_ENV) or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(f"{_CONFIGURED_LIMIT_ENV} must be numeric") from error
        if value <= 0:
            raise ValueError(f"{_CONFIGURED_LIMIT_ENV} must be positive")
        return int(value * 1024)
    if str(values.get("RENDER") or "").strip().lower() == "true":
        return int(_DEFAULT_RENDER_LIMIT_MB * 1024)
    return None


def _proc_total_rss_kib() -> int | None:
    total = 0
    observed = False
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            content = (entry / "status").read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            if not line.startswith("VmRSS:"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    total += max(0, int(parts[1]))
                    observed = True
                except ValueError:
                    pass
            break
    return total if observed else None


def _process_memory_kib(pid: int) -> tuple[int | None, int | None]:
    try:
        content = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None, None
    fields: dict[str, int] = {}
    for line in content.splitlines():
        if not (line.startswith("VmRSS:") or line.startswith("VmHWM:")):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                fields[parts[0].rstrip(":")] = max(0, int(parts[1]))
            except ValueError:
                continue
    return fields.get("VmRSS"), fields.get("VmHWM")


def _kib(value_bytes: int | None) -> int | None:
    return None if value_bytes is None else max(0, value_bytes // 1024)


def _working_set_kib(raw_current_kib: int | None, inactive_file_kib: int | None) -> int | None:
    if raw_current_kib is None:
        return None
    if inactive_file_kib is None:
        return raw_current_kib
    return max(0, raw_current_kib - min(raw_current_kib, inactive_file_kib))


def memory_snapshot(values: Mapping[str, str] | None = None) -> MemorySnapshot:
    resolved = dict(os.environ if values is None else values)
    configured_limit = _configured_limit_kib(resolved)

    v2 = _cgroup_v2_paths()
    v2_current_bytes = _read_int(v2.current)
    v2_limit_bytes = _read_int(v2.maximum)
    if v2_current_bytes is not None:
        stat = _read_key_values(v2.stat)
        events = _read_key_values(v2.events)
        raw_current = _kib(v2_current_bytes)
        observed_limit = _kib(v2_limit_bytes)
        if configured_limit is not None and (
            observed_limit is None or configured_limit < observed_limit
        ):
            limit = configured_limit
            source = (
                "cgroup_v2_process_configured_ceiling"
                if v2.process_scoped
                else "cgroup_v2_configured_ceiling"
            )
        else:
            limit = observed_limit
            source = "cgroup_v2_process" if v2.process_scoped else "cgroup_v2"
        inactive = _kib(stat.get("inactive_file"))
        return MemorySnapshot(
            raw_current_kib=raw_current,
            limit_kib=limit,
            working_set_kib=_working_set_kib(raw_current, inactive),
            inactive_file_kib=inactive,
            anon_kib=_kib(stat.get("anon")),
            file_kib=_kib(stat.get("file")),
            kernel_kib=_kib(stat.get("kernel")),
            source=source,
            memory_events=tuple(sorted(events.items())),
            active_file_kib=_kib(stat.get("active_file")),
        )

    v1_current_bytes = _read_int(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes"))
    v1_limit_bytes = _read_int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))
    if v1_current_bytes is not None:
        stat = _read_key_values(Path("/sys/fs/cgroup/memory/memory.stat"))
        raw_current = _kib(v1_current_bytes)
        observed_limit = _kib(v1_limit_bytes)
        if observed_limit is not None and observed_limit >= (1 << 50):
            observed_limit = None
        if configured_limit is not None and (
            observed_limit is None or configured_limit < observed_limit
        ):
            limit = configured_limit
            source = "cgroup_v1_configured_ceiling"
        else:
            limit = observed_limit
            source = "cgroup_v1"
        inactive = _kib(stat.get("total_inactive_file", stat.get("inactive_file")))
        file_bytes = stat.get("total_cache", stat.get("cache"))
        anon_bytes = stat.get("total_rss", stat.get("rss"))
        active_file_bytes = stat.get("total_active_file", stat.get("active_file"))
        failcnt = _read_int(Path("/sys/fs/cgroup/memory/memory.failcnt"))
        return MemorySnapshot(
            raw_current_kib=raw_current,
            limit_kib=limit,
            working_set_kib=_working_set_kib(raw_current, inactive),
            inactive_file_kib=inactive,
            anon_kib=_kib(anon_bytes),
            file_kib=_kib(file_bytes),
            kernel_kib=None,
            source=source,
            memory_events=(() if failcnt is None else (("failcnt", failcnt),)),
            active_file_kib=_kib(active_file_bytes),
        )

    proc_rss = _proc_total_rss_kib()
    return MemorySnapshot(
        raw_current_kib=proc_rss,
        limit_kib=configured_limit,
        working_set_kib=proc_rss,
        inactive_file_kib=None,
        anon_kib=proc_rss,
        file_kib=None,
        kernel_kib=None,
        source="proc_rss_fallback" if proc_rss is not None else "unavailable",
        memory_events=(),
        active_file_kib=None,
    )


def _hard_water_fraction(values: Mapping[str, str]) -> float:
    raw = str(values.get(_HARD_FRACTION_ENV) or "").strip()
    if not raw:
        return _DEFAULT_HARD_WATER_FRACTION
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{_HARD_FRACTION_ENV} must be numeric") from error
    if not 0.80 <= value < 0.99:
        raise ValueError(f"{_HARD_FRACTION_ENV} must be at least 0.80 and below 0.99")
    return value


def _hard_reserve_kib(values: Mapping[str, str]) -> int:
    raw = str(values.get(_HARD_RESERVE_ENV) or "").strip()
    if not raw:
        value = _DEFAULT_HARD_RESERVE_MB
    else:
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(f"{_HARD_RESERVE_ENV} must be numeric") from error
    if value < 64.0:
        raise ValueError(f"{_HARD_RESERVE_ENV} must be at least 64")
    return int(value * 1024)


def memory_boundaries(
    limit_kib: int,
    *,
    working_set_fraction: float,
    working_set_reserve_kib: int,
    values: Mapping[str, str] | None = None,
) -> MemoryBoundaries:
    if limit_kib <= 0:
        raise ValueError("limit_kib must be positive")
    if not 0.5 <= working_set_fraction < 0.9:
        raise ValueError("working_set_fraction must be at least 0.5 and below 0.9")
    if working_set_reserve_kib < 0:
        raise ValueError("working_set_reserve_kib cannot be negative")
    resolved = {} if values is None else values
    fractional_soft = int(limit_kib * working_set_fraction)
    reserve_soft = limit_kib - int(working_set_reserve_kib)
    if reserve_soft <= 0:
        reserve_soft = int(limit_kib * 0.5)
    soft = max(1, min(fractional_soft, reserve_soft))

    hard_fraction = _hard_water_fraction(resolved)
    hard_reserve = _hard_reserve_kib(resolved)
    fractional_hard = int(limit_kib * hard_fraction)
    reserve_hard = limit_kib - hard_reserve
    if reserve_hard <= 0:
        reserve_hard = int(limit_kib * 0.85)
    hard = max(soft, min(fractional_hard, reserve_hard))
    hard = min(max(1, hard), max(1, limit_kib - 1))
    return MemoryBoundaries(working_set_kib=soft, raw_hard_kib=hard)


def limit_reason(snapshot: MemorySnapshot, boundaries: MemoryBoundaries) -> str | None:
    working = snapshot.working_set_kib
    raw = snapshot.raw_current_kib
    if working is not None and working >= boundaries.working_set_kib:
        return "working_set"
    if raw is not None and raw >= boundaries.raw_hard_kib:
        return "raw_hard_ceiling"
    return None


def _raw_reclaim_request_kib(snapshot: MemorySnapshot, boundaries: MemoryBoundaries) -> int:
    """Return one bounded reclaim request sized to raw overage plus a small safety margin."""

    raw = snapshot.raw_current_kib
    inactive = snapshot.inactive_file_kib
    if raw is None or inactive is None or inactive <= 0 or raw < boundaries.raw_hard_kib:
        return 0
    overage = max(1, raw - boundaries.raw_hard_kib)
    target = min(_RECLAIM_MAX_KIB, overage + _RECLAIM_MARGIN_KIB)
    return max(1, min(inactive, target))


def _attempt_cgroup_v2_reclaim(
    snapshot: MemorySnapshot,
    boundaries: MemoryBoundaries,
    *,
    values: Mapping[str, str],
) -> tuple[MemoryReclaimResult, MemorySnapshot]:
    """Request one synchronous process-cgroup-v2 reclaim and immediately remeasure."""

    request_kib = _raw_reclaim_request_kib(snapshot, boundaries)
    reclaim_path = _reclaim_path()
    supported = snapshot.source.startswith("cgroup_v2") and reclaim_path.exists()
    error_type: str | None = None
    if request_kib > 0 and supported:
        try:
            with reclaim_path.open("w", encoding="ascii") as handle:
                handle.write(str(request_kib * 1024))
                handle.flush()
        except OSError as error:
            error_type = type(error).__name__
    elif request_kib > 0 and not supported:
        error_type = "UnsupportedCgroupReclaim"

    after = memory_snapshot(values)
    before_raw = snapshot.raw_current_kib
    after_raw = after.raw_current_kib
    reclaimed = (
        max(0, before_raw - after_raw)
        if before_raw is not None and after_raw is not None
        else 0
    )
    effective = limit_reason(after, boundaries) is None
    return (
        MemoryReclaimResult(
            attempted=request_kib > 0,
            supported=supported,
            requested_kib=request_kib,
            raw_before_kib=before_raw,
            raw_after_kib=after_raw,
            working_set_before_kib=snapshot.working_set_kib,
            working_set_after_kib=after.working_set_kib,
            reclaimed_kib=reclaimed,
            effective=effective,
            error_type=error_type,
        ),
        after,
    )


def _signal_process_group(process: subprocess.Popen, sig: signal.Signals) -> None:
    pid = getattr(process, "pid", None)
    if os.name == "posix" and isinstance(pid, int) and pid > 0:
        try:
            os.killpg(pid, sig)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        if sig == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()
    except (AttributeError, OSError):
        pass


def _safe_log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-reclaimable-memory-guard",
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


def wait_with_reclaimable_resource_bounds(
    process: subprocess.Popen,
    *,
    timeout_seconds: float,
    memory_high_water_fraction: float,
    values: Mapping[str, str] | None = None,
    memory_reserve_kib: int | None = None,
    poll_seconds: float | None = None,
) -> tuple[int | None, bool, bool, int, int]:
    """Wait for a child while distinguishing working-set pressure from page cache."""

    resolved = dict(os.environ if values is None else values)
    reserve = int(640 * 1024 if memory_reserve_kib is None else memory_reserve_kib)
    poll = _DEFAULT_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll <= 0:
        raise ValueError("poll_seconds must be positive")

    sampler_stop = Event()
    memory_limited = Event()
    peaks = {
        "process": 0,
        "raw": 0,
        "working_set": 0,
        "inactive_file": 0,
        "active_file": 0,
        "anon": 0,
        "file": 0,
        "kernel": 0,
    }
    last_snapshot: list[MemorySnapshot | None] = [None]
    trigger_reason: list[str | None] = [None]
    reclaim_attempt_count: list[int] = [0]
    reclaim_report: dict[str, object] = {
        "memory_reclaim_attempted": False,
        "memory_reclaim_supported": False,
        "memory_reclaim_requested_kib": 0,
        "memory_reclaim_raw_before_kib": None,
        "memory_reclaim_raw_after_kib": None,
        "memory_reclaim_working_set_before_kib": None,
        "memory_reclaim_working_set_after_kib": None,
        "memory_reclaim_delta_kib": 0,
        "memory_reclaim_reclaimed_kib": 0,
        "memory_reclaim_effective": False,
        "memory_reclaim_ever_effective": False,
        "memory_reclaim_error_type": None,
        "memory_reclaim_attempt_count": 0,
        "memory_reclaim_success_count": 0,
        "memory_reclaim_max_attempts": _RAW_RECLAIM_MAX_ATTEMPTS,
    }

    def record_snapshot(snapshot: MemorySnapshot) -> None:
        last_snapshot[0] = snapshot
        peaks["raw"] = max(peaks["raw"], snapshot.raw_current_kib or 0)
        peaks["working_set"] = max(peaks["working_set"], snapshot.working_set_kib or 0)
        peaks["inactive_file"] = max(peaks["inactive_file"], snapshot.inactive_file_kib or 0)
        peaks["active_file"] = max(peaks["active_file"], snapshot.active_file_kib or 0)
        peaks["anon"] = max(peaks["anon"], snapshot.anon_kib or 0)
        peaks["file"] = max(peaks["file"], snapshot.file_kib or 0)
        peaks["kernel"] = max(peaks["kernel"], snapshot.kernel_kib or 0)

    def sample_once() -> bool:
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 0:
            rss_kib, hwm_kib = _process_memory_kib(pid)
            peaks["process"] = max(peaks["process"], rss_kib or 0, hwm_kib or 0)

        snapshot = memory_snapshot(resolved)
        record_snapshot(snapshot)
        if snapshot.limit_kib is None:
            return False

        boundaries = memory_boundaries(
            snapshot.limit_kib,
            working_set_fraction=memory_high_water_fraction,
            working_set_reserve_kib=reserve,
            values=resolved,
        )
        reason = limit_reason(snapshot, boundaries)
        if reason is None:
            return False

        while (
            reason == "raw_hard_ceiling"
            and reclaim_attempt_count[0] < _RAW_RECLAIM_MAX_ATTEMPTS
        ):
            before = snapshot
            result, after = _attempt_cgroup_v2_reclaim(
                before,
                boundaries,
                values=resolved,
            )
            reclaim_attempt_count[0] += 1
            record_snapshot(after)
            first_raw = reclaim_report["memory_reclaim_raw_before_kib"]
            first_working = reclaim_report["memory_reclaim_working_set_before_kib"]
            requested_total = int(reclaim_report["memory_reclaim_requested_kib"]) + int(
                result.requested_kib
            )
            raw_before = result.raw_before_kib if first_raw is None else first_raw
            working_before = (
                result.working_set_before_kib if first_working is None else first_working
            )
            net_reclaimed = (
                max(0, int(raw_before) - int(result.raw_after_kib))
                if isinstance(raw_before, int) and isinstance(result.raw_after_kib, int)
                else 0
            )
            reclaim_report.update(
                {
                    "memory_reclaim_attempted": bool(
                        reclaim_report["memory_reclaim_attempted"] or result.attempted
                    ),
                    "memory_reclaim_supported": result.supported,
                    "memory_reclaim_requested_kib": requested_total,
                    "memory_reclaim_raw_before_kib": raw_before,
                    "memory_reclaim_raw_after_kib": result.raw_after_kib,
                    "memory_reclaim_working_set_before_kib": working_before,
                    "memory_reclaim_working_set_after_kib": result.working_set_after_kib,
                    "memory_reclaim_delta_kib": net_reclaimed,
                    "memory_reclaim_reclaimed_kib": net_reclaimed,
                    "memory_reclaim_effective": result.effective,
                    "memory_reclaim_ever_effective": bool(
                        reclaim_report["memory_reclaim_ever_effective"] or result.effective
                    ),
                    "memory_reclaim_error_type": result.error_type,
                    "memory_reclaim_attempt_count": reclaim_attempt_count[0],
                    "memory_reclaim_success_count": int(
                        reclaim_report["memory_reclaim_success_count"]
                    ) + int(result.effective),
                }
            )
            _safe_log(
                "reclaimable_memory_guard_reclaim_attempted",
                **reclaim_report,
                memory_reclaim_attempt_number=reclaim_attempt_count[0],
                memory_reclaim_attempt_requested_kib=result.requested_kib,
                memory_reclaim_attempt_delta_kib=result.reclaimed_kib,
                memory_reclaim_inactive_file_before_kib=before.inactive_file_kib,
                memory_reclaim_active_file_before_kib=before.active_file_kib,
                memory_reclaim_anon_before_kib=before.anon_kib,
                memory_reclaim_file_before_kib=before.file_kib,
                memory_reclaim_kernel_before_kib=before.kernel_kib,
                memory_reclaim_inactive_file_after_kib=after.inactive_file_kib,
                memory_reclaim_active_file_after_kib=after.active_file_kib,
                memory_reclaim_anon_after_kib=after.anon_kib,
                memory_reclaim_file_after_kib=after.file_kib,
                memory_reclaim_kernel_after_kib=after.kernel_kib,
                working_set_boundary_kib=boundaries.working_set_kib,
                raw_hard_boundary_kib=boundaries.raw_hard_kib,
            )
            reason = limit_reason(after, boundaries)
            snapshot = after
            if reason is None:
                return False
            if reason == "working_set":
                break
            if (
                not result.attempted
                or not result.supported
                or result.error_type is not None
            ):
                break

        trigger_reason[0] = reason
        memory_limited.set()
        _safe_log(
            "reclaimable_memory_guard_triggered",
            trigger_reason=reason,
            memory_accounting_source=snapshot.source,
            container_memory_current_kib=snapshot.raw_current_kib,
            container_memory_working_set_kib=snapshot.working_set_kib,
            container_memory_inactive_file_kib=snapshot.inactive_file_kib,
            container_memory_active_file_kib=snapshot.active_file_kib,
            container_memory_anon_kib=snapshot.anon_kib,
            container_memory_file_kib=snapshot.file_kib,
            container_memory_kernel_kib=snapshot.kernel_kib,
            container_memory_limit_kib=snapshot.limit_kib,
            working_set_boundary_kib=boundaries.working_set_kib,
            raw_hard_boundary_kib=boundaries.raw_hard_kib,
            memory_events=dict(snapshot.memory_events),
            service_oom_prevented=True,
            **reclaim_report,
        )
        _signal_process_group(process, signal.SIGTERM)
        return True

    sample_once()

    def sample_memory() -> None:
        while not sampler_stop.is_set() and not memory_limited.is_set():
            if sample_once():
                return
            sampler_stop.wait(poll)

    sampler = Thread(
        target=sample_memory,
        name="reclaimable-memory-guard-sampler",
        daemon=True,
    )
    if not memory_limited.is_set():
        sampler.start()
    try:
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return_code = None
            timed_out = True
        else:
            timed_out = False
    finally:
        sampler_stop.set()
        if sampler.is_alive():
            sampler.join(timeout=1.0)

    snapshot = last_snapshot[0]
    _safe_log(
        "reclaimable_memory_guard_finished",
        memory_limited=memory_limited.is_set(),
        trigger_reason=trigger_reason[0],
        process_peak_rss_kib=peaks["process"],
        container_peak_memory_kib=peaks["raw"],
        container_peak_working_set_kib=peaks["working_set"],
        container_peak_inactive_file_kib=peaks["inactive_file"],
        container_peak_active_file_kib=peaks["active_file"],
        container_peak_anon_kib=peaks["anon"],
        container_peak_file_kib=peaks["file"],
        container_peak_kernel_kib=peaks["kernel"],
        memory_accounting_source=None if snapshot is None else snapshot.source,
        memory_events={} if snapshot is None else dict(snapshot.memory_events),
        **reclaim_report,
    )
    return (
        return_code,
        timed_out,
        memory_limited.is_set(),
        peaks["process"],
        peaks["raw"],
    )


__all__ = [
    "MemoryBoundaries",
    "MemoryReclaimResult",
    "MemorySnapshot",
    "limit_reason",
    "memory_boundaries",
    "memory_snapshot",
    "wait_with_reclaimable_resource_bounds",
]
