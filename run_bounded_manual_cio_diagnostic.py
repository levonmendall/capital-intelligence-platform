"""Run one manual CIO diagnostic with explicit lifecycle logs and hard resource bounds.

The underlying diagnostic remains the only component that can prepare evidence, invoke the
specialists and CIO, construct a portfolio, or attempt governed paper implementation. This
wrapper adds operational observability, prevents a stalled diagnostic from remaining
silent indefinitely, and protects the hosting service from a diagnostic-driven cgroup OOM.
It never changes market coverage, investment logic, governance, or real-money authority.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import (
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
)


_DEFAULT_TIMEOUT_SECONDS = 1800.0
_DEFAULT_MEMORY_HIGH_WATER_FRACTION = 0.85
_MEMORY_POLL_SECONDS = 0.5


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
    if not 0.5 <= value < 1.0:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_MEMORY_HIGH_WATER_FRACTION must be at least 0.5 and below 1.0"
        )
    return value


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


def _terminate(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            return process.wait(timeout=5)
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
    """Return current RSS and kernel-recorded process high-water RSS on Linux."""

    status = Path(f"/proc/{pid}/status")
    return _read_kib_field(status, "VmRSS"), _read_kib_field(status, "VmHWM")


def _cgroup_memory_kib() -> tuple[int | None, int | None]:
    """Return container memory current/limit without adding a monitoring dependency."""

    current_path = Path("/sys/fs/cgroup/memory.current")
    maximum_path = Path("/sys/fs/cgroup/memory.max")
    try:
        current_raw = current_path.read_text(encoding="utf-8").strip()
        maximum_raw = maximum_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, None
    if maximum_raw == "max":
        return None, None
    try:
        return int(current_raw) // 1024, int(maximum_raw) // 1024
    except ValueError:
        return None, None


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
) -> tuple[int | None, bool, bool, int, int]:
    """Observe a diagnostic until exit, timeout, or memory protection triggers.

    Returns ``(return_code, timed_out, memory_limited, process_peak_kib,
    cgroup_peak_kib)``. The cgroup guard accounts for the web/API processes as well as
    the diagnostic, protecting service availability rather than merely measuring one
    child process.
    """

    deadline = time.monotonic() + timeout_seconds
    process_peak_kib = 0
    cgroup_peak_kib = 0
    while True:
        return_code = process.poll()
        rss_kib, hwm_kib = _process_memory_kib(process.pid)
        process_peak_kib = max(process_peak_kib, rss_kib or 0, hwm_kib or 0)
        cgroup_current_kib, cgroup_limit_kib = _cgroup_memory_kib()
        cgroup_peak_kib = max(cgroup_peak_kib, cgroup_current_kib or 0)
        if return_code is not None:
            return return_code, False, False, process_peak_kib, cgroup_peak_kib
        if (
            cgroup_current_kib is not None
            and cgroup_limit_kib is not None
            and cgroup_limit_kib > 0
            and cgroup_current_kib >= int(cgroup_limit_kib * memory_high_water_fraction)
        ):
            return None, False, True, process_peak_kib, cgroup_peak_kib
        if time.monotonic() >= deadline:
            return None, True, False, process_peak_kib, cgroup_peak_kib
        time.sleep(min(_MEMORY_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


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

    script = Path(__file__).resolve().with_name("run_manual_cio_diagnostic.py")
    cgroup_current_kib, cgroup_limit_kib = _cgroup_memory_kib()
    _log(
        "manual_cio_diagnostic_run_started",
        release=release,
        timeout_seconds=timeout,
        memory_high_water_fraction=memory_high_water_fraction,
        cgroup_memory_current_kib=cgroup_current_kib,
        cgroup_memory_limit_kib=cgroup_limit_kib,
    )
    command = [sys.executable, str(script)]
    if force:
        command.append("--force")
    try:
        process = subprocess.Popen(
            tuple(command),
            env=resolved,
            cwd=str(script.parent),
        )
    except OSError as error:
        _log(
            "manual_cio_diagnostic_start_failed",
            release=release,
            error_type=type(error).__name__,
        )
        return 2

    return_code, timed_out, memory_limited, process_peak_kib, cgroup_peak_kib = (
        _wait_with_resource_bounds(
            process,
            timeout_seconds=timeout,
            memory_high_water_fraction=memory_high_water_fraction,
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
            cgroup_peak_memory_kib=cgroup_peak_kib,
        )
        return 124

    if memory_limited:
        return_code = _terminate(process)
        request_id, request_state = _close_failed_request(
            values=resolved,
            detail=(
                "Manual CIO diagnostic reached the operational cgroup memory high-water "
                f"boundary ({memory_high_water_fraction:.0%}) and was terminated fail-closed "
                "before the hosting kernel could OOM-kill the service"
            ),
        )
        _log(
            "manual_cio_diagnostic_memory_high_water_reached",
            release=release,
            return_code=return_code,
            request_id=request_id,
            request_state=request_state,
            memory_high_water_fraction=memory_high_water_fraction,
            process_peak_rss_kib=process_peak_kib,
            cgroup_peak_memory_kib=cgroup_peak_kib,
            complete_market_coverage_preserved=True,
            service_oom_prevented=True,
        )
        return 125

    _log(
        "manual_cio_diagnostic_process_finished",
        release=release,
        return_code=return_code,
        process_peak_rss_kib=process_peak_kib,
        cgroup_peak_memory_kib=cgroup_peak_kib,
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
