"""Run one manual CIO diagnostic with hard container-memory isolation.

The underlying diagnostic remains the only component that can prepare evidence, invoke the
specialists and CIO, construct a portfolio, or attempt governed paper implementation. This
wrapper protects the hosting service from diagnostic-driven OOM failure without changing
market coverage, investment logic, governance, thresholds, or real-money authority.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import (
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
)


_DEFAULT_TIMEOUT_SECONDS = 1800.0
# Keep enough headroom for Streamlit, the read-only API, allocator bursts, and kernel
# accounting lag on Render's 2 GB service. The diagnostic fails closed before service
# availability is endangered; complete market coverage is never silently reduced.
_DEFAULT_MEMORY_HIGH_WATER_FRACTION = 0.70
_DEFAULT_MEMORY_RESERVE_MB = 640.0
_DEFAULT_MEMORY_POLL_SECONDS = 0.10
_RENDER_MEMORY_LIMIT_FALLBACK_MB = 2048.0


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _timeout_seconds(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS",
        "",
    ).strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS must be numeric"
        ) from error
    if value <= 0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS must be positive"
        )
    return value


def _memory_high_water_fraction(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION",
        "",
    ).strip()
    if not raw:
        return _DEFAULT_MEMORY_HIGH_WATER_FRACTION
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION must be numeric"
        ) from error
    if not 0.5 <= value < 0.9:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION must be at least 0.5 and below 0.9"
        )
    return value


def _memory_reserve_kib(values: Mapping[str, str]) -> int:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_RESERVE_MB",
        "",
    ).strip()
    if not raw:
        value = _DEFAULT_MEMORY_RESERVE_MB
    else:
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_RESERVE_MB must be numeric"
            ) from error
    if value < 256.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_RESERVE_MB must be at least 256"
        )
    return int(value * 1024)


def _memory_poll_seconds(values: Mapping[str, str]) -> float:
    raw = values.get(
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_POLL_SECONDS",
        "",
    ).strip()
    if not raw:
        value = _DEFAULT_MEMORY_POLL_SECONDS
    else:
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_POLL_SECONDS must be numeric"
            ) from error
    if not 0.02 <= value <= 1.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_POLL_SECONDS must be between 0.02 and 1.0"
        )
    return value


def _configured_memory_limit_kib(values: Mapping[str, str]) -> int | None:
    raw = values.get("CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB must be numeric"
            ) from error
        if value <= 0:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_CONTAINER_MEMORY_LIMIT_MB must be positive"
            )
        return int(value * 1024)
    # Render's currently configured Standard service is a 2 GB instance. This fallback
    # is used only when neither cgroup-v2 nor cgroup-v1 exposes a usable limit.
    if values.get("RENDER", "").strip().lower() == "true":
        return int(_RENDER_MEMORY_LIMIT_FALLBACK_MB * 1024)
    return None


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-manual-cio-diagnostic-watchdog",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "paper_only": True,
                "real_money_authorized": False,
                "secret_values_disclosed": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _signal_process_group(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    sig: signal.Signals,
) -> None:
    """Signal the diagnostic process group so descendants cannot survive a cutoff."""

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


def _terminate(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    _signal_process_group(process, signal.SIGTERM)
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, signal.SIGKILL)
        try:
            return process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return process.returncode


def _read_kib_field(path: Path, field: str) -> int | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = field + ":"
    for line in content.splitlines():
        if not line.startswith(prefix):
            continue
        parts = line[len(prefix) :].strip().split()
        if not parts:
            return None
        try:
            return int(parts[0])
        except ValueError:
            return None
    return None


def _process_memory_kib(pid: int) -> tuple[int | None, int | None]:
    status = Path(f"/proc/{pid}/status")
    return _read_kib_field(status, "VmRSS"), _read_kib_field(status, "VmHWM")


def _read_byte_counter(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _cgroup_memory_kib() -> tuple[int | None, int | None]:
    """Return container memory current/limit for cgroup v2 or v1."""

    v2_current = _read_byte_counter(Path("/sys/fs/cgroup/memory.current"))
    v2_limit = _read_byte_counter(Path("/sys/fs/cgroup/memory.max"))
    if v2_current is not None and v2_limit is not None and v2_limit > 0:
        return v2_current // 1024, v2_limit // 1024

    v1_current = _read_byte_counter(
        Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    )
    v1_limit = _read_byte_counter(
        Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    )
    # Some cgroup-v1 hosts report an effectively unlimited sentinel near 2^63.
    if (
        v1_current is not None
        and v1_limit is not None
        and 0 < v1_limit < (1 << 60)
    ):
        return v1_current // 1024, v1_limit // 1024
    return None, None


def _proc_total_rss_kib() -> int | None:
    """Conservative container-process RSS fallback when cgroup accounting is hidden."""

    total = 0
    observed = False
    try:
        entries = tuple(Path("/proc").iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        rss = _read_kib_field(entry / "status", "VmRSS")
        if rss is None:
            continue
        observed = True
        total += rss
    return total if observed else None


def _container_memory_kib(
    values: Mapping[str, str],
) -> tuple[int | None, int | None, str]:
    current, limit = _cgroup_memory_kib()
    if current is not None and limit is not None:
        return current, limit, "cgroup"

    configured_limit = _configured_memory_limit_kib(values)
    if configured_limit is None:
        return None, None, "unavailable"
    proc_rss = _proc_total_rss_kib()
    if proc_rss is None:
        return None, configured_limit, "configured_limit_only"
    return proc_rss, configured_limit, "proc_rss_fallback"


def _effective_memory_boundary_kib(
    limit_kib: int,
    *,
    memory_high_water_fraction: float,
    memory_reserve_kib: int,
) -> int:
    fractional = int(limit_kib * memory_high_water_fraction)
    reserve_based = limit_kib - memory_reserve_kib
    if reserve_based <= 0:
        reserve_based = int(limit_kib * 0.5)
    return max(1, min(fractional, reserve_based))


def _close_failed_request(
    *,
    values: Mapping[str, str],
    detail: str,
) -> tuple[str | None, str | None]:
    """Truthfully close only a request that the bounded child had claimed."""

    existing = latest_manual_cio_diagnostic(values=values)
    if existing is None:
        return None, None
    if existing.state != "in_progress":
        return existing.request_id, existing.state
    existing_detail = getattr(existing, "detail", None)
    last_progress = (
        existing_detail
        if existing_detail and existing_detail.startswith("governed_progress=")
        else "governed_progress=unavailable"
    )
    finished = finish_manual_cio_diagnostic(
        existing,
        succeeded=False,
        cycle_key=existing.cycle_key,
        snapshot_identifier=existing.snapshot_identifier,
        detail=f"{detail}; last_{last_progress}.",
        values=values,
    )
    return finished.request_id, finished.state


def _close_timed_out_request(
    *,
    values: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[str | None, str | None]:
    return _close_failed_request(
        values=values,
        detail=(
            "Manual CIO diagnostic exceeded its governed operational deadline of "
            f"{timeout_seconds:g} seconds and was terminated fail-closed"
        ),
    )


def _wait_with_resource_bounds(
    process: subprocess.Popen[bytes] | subprocess.Popen[str],
    *,
    timeout_seconds: float,
    memory_high_water_fraction: float,
    values: Mapping[str, str] | None = None,
    memory_reserve_kib: int | None = None,
    poll_seconds: float | None = None,
) -> tuple[int | None, bool, bool, int, int]:
    """Wait while continuously protecting the container's memory headroom."""

    resolved = {} if values is None else values
    reserve = (
        _memory_reserve_kib(resolved)
        if memory_reserve_kib is None
        else int(memory_reserve_kib)
    )
    poll = _memory_poll_seconds(resolved) if poll_seconds is None else float(poll_seconds)
    if poll <= 0:
        raise ValueError("poll_seconds must be positive")

    sampler_stop = Event()
    memory_limited = Event()
    peaks = {"process": 0, "container": 0}

    def sample_once() -> bool:
        pid = getattr(process, "pid", None)
        if isinstance(pid, int) and pid > 0:
            rss_kib, hwm_kib = _process_memory_kib(pid)
            peaks["process"] = max(peaks["process"], rss_kib or 0, hwm_kib or 0)
        current_kib, limit_kib, _source = _container_memory_kib(resolved)
        peaks["container"] = max(peaks["container"], current_kib or 0)
        if current_kib is None or limit_kib is None or limit_kib <= 0:
            return False
        boundary_kib = _effective_memory_boundary_kib(
            limit_kib,
            memory_high_water_fraction=memory_high_water_fraction,
            memory_reserve_kib=reserve,
        )
        if current_kib < boundary_kib:
            return False
        memory_limited.set()
        _signal_process_group(process, signal.SIGTERM)
        return True

    # Sample synchronously before waiting so a fast import/allocation spike cannot get a
    # full polling interval of unobserved headroom.
    sample_once()

    def sample_memory() -> None:
        while not sampler_stop.is_set() and not memory_limited.is_set():
            if sample_once():
                return
            sampler_stop.wait(poll)

    sampler = Thread(
        target=sample_memory,
        name="manual-cio-diagnostic-memory-sampler",
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

    return (
        return_code,
        timed_out,
        memory_limited.is_set(),
        peaks["process"],
        peaks["container"],
    )


def run_bounded_diagnostic(
    *,
    force: bool = False,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    release = _release(resolved)
    timeout = _timeout_seconds(resolved) if timeout_seconds is None else float(timeout_seconds)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    memory_high_water_fraction = _memory_high_water_fraction(resolved)
    memory_reserve_kib = _memory_reserve_kib(resolved)
    memory_poll_seconds = _memory_poll_seconds(resolved)

    script = Path(__file__).resolve().with_name("run_manual_cio_diagnostic.py")
    current_kib, limit_kib, accounting_source = _container_memory_kib(resolved)
    boundary_kib = (
        _effective_memory_boundary_kib(
            limit_kib,
            memory_high_water_fraction=memory_high_water_fraction,
            memory_reserve_kib=memory_reserve_kib,
        )
        if limit_kib is not None
        else None
    )
    _log(
        "manual_cio_diagnostic_run_started",
        release=release,
        timeout_seconds=timeout,
        memory_high_water_fraction=memory_high_water_fraction,
        memory_reserve_kib=memory_reserve_kib,
        memory_poll_seconds=memory_poll_seconds,
        container_memory_current_kib=current_kib,
        container_memory_limit_kib=limit_kib,
        container_memory_boundary_kib=boundary_kib,
        memory_accounting_source=accounting_source,
    )
    command = [sys.executable, str(script)]
    if force:
        command.append("--force")
    try:
        process = subprocess.Popen(
            tuple(command),
            env=resolved,
            cwd=str(script.parent),
            start_new_session=(os.name == "posix"),
        )
    except OSError as error:
        _log(
            "manual_cio_diagnostic_start_failed",
            release=release,
            error_type=type(error).__name__,
        )
        return 2

    return_code, timed_out, memory_limited, process_peak_kib, container_peak_kib = (
        _wait_with_resource_bounds(
            process,
            timeout_seconds=timeout,
            memory_high_water_fraction=memory_high_water_fraction,
            values=resolved,
            memory_reserve_kib=memory_reserve_kib,
            poll_seconds=memory_poll_seconds,
        )
    )
    if timed_out:
        return_code = _terminate(process)
        request_id, request_state = _close_timed_out_request(
            values=resolved,
            timeout_seconds=timeout,
        )
        _log(
            "manual_cio_diagnostic_timed_out",
            release=release,
            timeout_seconds=timeout,
            return_code=return_code,
            request_id=request_id,
            request_state=request_state,
            process_peak_rss_kib=process_peak_kib,
            container_peak_memory_kib=container_peak_kib,
        )
        return 124

    if memory_limited:
        return_code = _terminate(process)
        request_id, request_state = _close_failed_request(
            values=resolved,
            detail=(
                "Manual CIO diagnostic reached the operational container-memory boundary "
                f"({memory_high_water_fraction:.0%} fractional ceiling with "
                f"{memory_reserve_kib // 1024} MB service reserve) and was terminated "
                "fail-closed before the hosting kernel could OOM-kill the service"
            ),
        )
        _log(
            "manual_cio_diagnostic_memory_high_water_reached",
            release=release,
            return_code=return_code,
            request_id=request_id,
            request_state=request_state,
            memory_high_water_fraction=memory_high_water_fraction,
            memory_reserve_kib=memory_reserve_kib,
            process_peak_rss_kib=process_peak_kib,
            container_peak_memory_kib=container_peak_kib,
            complete_market_coverage_preserved=True,
            service_oom_prevented=True,
        )
        return 125

    _log(
        "manual_cio_diagnostic_process_finished",
        release=release,
        return_code=return_code,
        process_peak_rss_kib=process_peak_kib,
        container_peak_memory_kib=container_peak_kib,
    )
    return int(return_code or 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run a replacement even when this release already has a final result.",
    )
    parser.add_argument("--timeout-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        return run_bounded_diagnostic(
            force=args.force,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        _log(
            "manual_cio_diagnostic_watchdog_failed",
            error_type=type(error).__name__,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
