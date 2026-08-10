"""Run heavyweight Render background work in a single bounded memory lane.

The coordinator intentionally imports only lightweight operational code.  Each CIO
operator, historical-backfill, or encrypted-backup pass runs in a short-lived child process
and is watched with the same container-memory boundary used by the manual CIO diagnostic.
This returns imported modules and allocator arenas to the OS between passes and prevents
several heavyweight jobs from running concurrently on Render's 2 GB service.

This wrapper changes only operational process isolation.  It does not change market scope,
CIO authority, portfolio construction, thresholds, paper-execution controls, or permit real
money.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Mapping, MutableMapping, Sequence

from render_memory_lane import acquire_memory_lane


@dataclass(frozen=True, slots=True)
class WorkerSpec:
    name: str
    script: str
    arguments: tuple[str, ...]
    interval_env: str
    default_interval_seconds: float
    timeout_env: str
    default_timeout_seconds: float
    default_initial_delay_seconds: float


_WORKERS = {
    "cio-paper-operator": WorkerSpec(
        name="cio-paper-operator",
        script="run_autonomous_paper_operator.py",
        arguments=("--once",),
        interval_env="CAPITAL_INTELLIGENCE_SCHEDULER_POLL_SECONDS",
        default_interval_seconds=60.0,
        timeout_env="CAPITAL_INTELLIGENCE_PAPER_OPERATOR_PASS_TIMEOUT_SECONDS",
        default_timeout_seconds=1800.0,
        default_initial_delay_seconds=90.0,
    ),
    "historical-backfill": WorkerSpec(
        name="historical-backfill",
        script="run_historical_backfill.py",
        arguments=(),
        interval_env="CAPITAL_INTELLIGENCE_HISTORICAL_INTERVAL_SECONDS",
        default_interval_seconds=86400.0,
        timeout_env="CAPITAL_INTELLIGENCE_HISTORICAL_PASS_TIMEOUT_SECONDS",
        default_timeout_seconds=3600.0,
        default_initial_delay_seconds=1800.0,
    ),
    "encrypted-backup": WorkerSpec(
        name="encrypted-backup",
        script="run_backup.py",
        arguments=(),
        interval_env="CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_SECONDS",
        default_interval_seconds=86400.0,
        timeout_env="CAPITAL_INTELLIGENCE_BACKUP_PASS_TIMEOUT_SECONDS",
        default_timeout_seconds=1800.0,
        default_initial_delay_seconds=900.0,
    ),
}


def _seconds(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _interval_seconds(spec: WorkerSpec, values: Mapping[str, str]) -> float:
    if spec.name == "encrypted-backup":
        explicit = values.get(spec.interval_env, "").strip()
        if explicit:
            return _seconds(values, spec.interval_env, spec.default_interval_seconds)
        hours_raw = values.get("CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_HOURS", "").strip()
        if hours_raw:
            try:
                hours = float(hours_raw)
            except ValueError as error:
                raise ValueError(
                    "CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_HOURS must be numeric"
                ) from error
            if hours <= 0:
                raise ValueError("CAPITAL_INTELLIGENCE_BACKUP_INTERVAL_HOURS must be positive")
            return hours * 3600.0
    return _seconds(values, spec.interval_env, spec.default_interval_seconds)


def _log(worker: str, event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-bounded-render-worker",
                "worker": worker,
                "timestamp": time.time(),
                "paper_only": True,
                "real_money_authorized": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _run_isolated_once(
    spec: WorkerSpec,
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    lane_wait_seconds: float = 5.0,
    active_process: MutableMapping[str, subprocess.Popen | None] | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    timeout = (
        _seconds(resolved, spec.timeout_env, spec.default_timeout_seconds)
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")
    if lane_wait_seconds < 0:
        raise ValueError("lane_wait_seconds cannot be negative")

    lease = acquire_memory_lane(
        spec.name,
        values=resolved,
        timeout_seconds=lane_wait_seconds,
        poll_seconds=0.10,
    )
    if lease is None:
        _log(
            spec.name,
            "heavy_memory_lane_busy",
            child_started=False,
            retry_deferred=True,
        )
        return 126

    # Reuse the already-hardened cgroup/process watchdog without importing the target's
    # heavyweight provider/CIO/history stack into this long-lived coordinator.
    import run_bounded_manual_cio_diagnostic as memory_watchdog

    script = Path(__file__).resolve().with_name(spec.script)
    process: subprocess.Popen | None = None
    try:
        current_kib, limit_kib, accounting_source = memory_watchdog._container_memory_kib(
            resolved
        )
        boundary_kib = (
            memory_watchdog._effective_memory_boundary_kib(
                limit_kib,
                memory_high_water_fraction=memory_watchdog._memory_high_water_fraction(
                    resolved
                ),
                memory_reserve_kib=memory_watchdog._memory_reserve_kib(resolved),
            )
            if limit_kib is not None
            else None
        )
        _log(
            spec.name,
            "isolated_worker_pass_starting",
            command=[sys.executable, str(script), *spec.arguments],
            container_memory_current_kib=current_kib,
            container_memory_limit_kib=limit_kib,
            container_memory_boundary_kib=boundary_kib,
            memory_accounting_source=accounting_source,
            exclusive_heavy_memory_lane=True,
        )
        process = subprocess.Popen(
            (sys.executable, str(script), *spec.arguments),
            env=resolved,
            cwd=str(script.parent),
            start_new_session=(os.name == "posix"),
        )
        if active_process is not None:
            active_process["process"] = process
        return_code, timed_out, memory_limited, process_peak_kib, container_peak_kib = (
            memory_watchdog._wait_with_resource_bounds(
                process,
                timeout_seconds=timeout,
                memory_high_water_fraction=memory_watchdog._memory_high_water_fraction(
                    resolved
                ),
                values=resolved,
                memory_reserve_kib=memory_watchdog._memory_reserve_kib(resolved),
                poll_seconds=memory_watchdog._memory_poll_seconds(resolved),
            )
        )
        if timed_out:
            return_code = memory_watchdog._terminate(process)
            _log(
                spec.name,
                "isolated_worker_pass_timed_out",
                return_code=return_code,
                process_peak_rss_kib=process_peak_kib,
                container_peak_memory_kib=container_peak_kib,
                service_oom_prevented=True,
            )
            return 124
        if memory_limited:
            return_code = memory_watchdog._terminate(process)
            _log(
                spec.name,
                "isolated_worker_pass_memory_limited",
                return_code=return_code,
                process_peak_rss_kib=process_peak_kib,
                container_peak_memory_kib=container_peak_kib,
                service_oom_prevented=True,
            )
            return 125
        _log(
            spec.name,
            "isolated_worker_pass_finished",
            return_code=return_code,
            process_peak_rss_kib=process_peak_kib,
            container_peak_memory_kib=container_peak_kib,
            heavyweight_modules_retained_in_coordinator=False,
        )
        return int(return_code or 0)
    finally:
        if active_process is not None:
            active_process["process"] = None
        if process is not None and process.poll() is None:
            memory_watchdog._terminate(process)
        lease.release()


def run_loop(
    spec: WorkerSpec,
    *,
    values: Mapping[str, str] | None = None,
    initial_delay_seconds: float | None = None,
    stop_event: Event | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    interval = _interval_seconds(spec, resolved)
    initial_delay = (
        spec.default_initial_delay_seconds
        if initial_delay_seconds is None
        else float(initial_delay_seconds)
    )
    if initial_delay < 0:
        raise ValueError("initial_delay_seconds cannot be negative")

    stopping = stop_event or Event()
    active: dict[str, subprocess.Popen | None] = {"process": None}

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del frame
        _log(spec.name, "shutdown_requested", signal=signum)
        stopping.set()
        process = active.get("process")
        if process is not None and process.poll() is None:
            import run_bounded_manual_cio_diagnostic as memory_watchdog

            memory_watchdog._terminate(process)

    previous_handlers: dict[signal.Signals, object] = {}
    if stop_event is None:
        previous_handlers = {
            signal.SIGTERM: signal.signal(signal.SIGTERM, request_stop),
            signal.SIGINT: signal.signal(signal.SIGINT, request_stop),
        }

    try:
        _log(
            spec.name,
            "bounded_worker_started",
            initial_delay_seconds=initial_delay,
            interval_seconds=interval,
            isolated_children=True,
            exclusive_heavy_memory_lane=True,
        )
        if stopping.wait(initial_delay):
            return 0
        while not stopping.is_set():
            try:
                return_code = _run_isolated_once(
                    spec,
                    values=resolved,
                    active_process=active,
                )
            except (OSError, TypeError, ValueError, RuntimeError) as error:
                _log(
                    spec.name,
                    "isolated_worker_pass_failed",
                    error_type=type(error).__name__,
                    retry_deferred=True,
                )
                return_code = 2

            if return_code in {124, 125}:
                delay = min(interval, 300.0)
            elif return_code == 126:
                delay = min(interval, 30.0)
            else:
                delay = interval
            if stopping.wait(delay):
                break
        return 0
    finally:
        process = active.get("process")
        if process is not None and process.poll() is None:
            import run_bounded_manual_cio_diagnostic as memory_watchdog

            memory_watchdog._terminate(process)
        for handled_signal, previous in previous_handlers.items():
            signal.signal(handled_signal, previous)
        _log(spec.name, "bounded_worker_stopped")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worker", choices=tuple(_WORKERS))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--initial-delay-seconds", type=float)
    parser.add_argument("--timeout-seconds", type=float)
    args = parser.parse_args(argv)
    spec = _WORKERS[args.worker]

    if args.once:
        try:
            return _run_isolated_once(spec, timeout_seconds=args.timeout_seconds)
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            _log(spec.name, "bounded_worker_failed", error_type=type(error).__name__)
            return 2

    try:
        return run_loop(spec, initial_delay_seconds=args.initial_delay_seconds)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        _log(spec.name, "bounded_worker_failed", error_type=type(error).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
