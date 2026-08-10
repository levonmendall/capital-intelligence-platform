"""Refresh live-provider readiness without blocking Render web startup.

The long-lived coordinator stays lightweight. Each heavyweight provider-validation pass
runs in a short-lived child process so imported provider/data modules and allocator arenas
are returned to the OS when the pass finishes. A quiet memory window is required after any
manual CIO diagnostic before provider validation may start, preventing the diagnostic,
normal supervisor startup, and provider stack from racing for the same constrained Render
memory budget.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from threading import Event
from types import FrameType
from typing import TYPE_CHECKING, Mapping, Sequence

from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic

if TYPE_CHECKING:
    from operations.provider_validation import ProviderValidationReport

_DEFAULT_INTERVAL_SECONDS = 3600.0
_DEFAULT_INITIAL_DELAY_SECONDS = 5.0
_DEFAULT_DIAGNOSTIC_POLL_SECONDS = 5.0
_DEFAULT_POST_LANE_QUIET_SECONDS = 60.0
_DEFAULT_VALIDATION_TIMEOUT_SECONDS = 900.0
_ACTIVE_DIAGNOSTIC_STATES = frozenset({"pending", "in_progress"})


def _seconds(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-provider-validation",
                "timestamp": time.time(),
                "real_money_authorized": False,
                "secret_values_disclosed": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _diagnostic_active() -> bool:
    """Fail memory-safe when diagnostic coordination cannot be read."""

    try:
        request = latest_manual_cio_diagnostic()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        _log(
            "provider_validation_diagnostic_gate_unavailable",
            error_type=type(error).__name__,
            provider_validation_deferred=True,
        )
        return True
    return request is not None and request.state in _ACTIVE_DIAGNOSTIC_STATES


def _wait_for_diagnostic_memory_lane(
    stopping: Event,
    *,
    poll_seconds: float | None = None,
) -> bool:
    """Wait until no governed diagnostic owns the heavy-memory lane."""

    poll = (
        _seconds(
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_DIAGNOSTIC_POLL_SECONDS",
            _DEFAULT_DIAGNOSTIC_POLL_SECONDS,
        )
        if poll_seconds is None
        else float(poll_seconds)
    )
    if poll <= 0:
        raise ValueError("diagnostic poll seconds must be positive")
    deferred_logged = False
    while _diagnostic_active():
        if not deferred_logged:
            _log(
                "provider_validation_deferred_for_cio_diagnostic",
                complete_market_coverage_preserved=True,
                heavy_provider_modules_loaded=False,
                paper_only=True,
            )
            deferred_logged = True
        if stopping.wait(poll):
            return False
    if deferred_logged:
        _log("provider_validation_resumed_after_cio_diagnostic")
    return True


def _wait_for_quiet_memory_lane(
    stopping: Event,
    *,
    quiet_seconds: float | None = None,
    poll_seconds: float | None = None,
) -> bool:
    """Require a diagnostic-free settling window before heavy validation starts.

    The release supervisor starts its deferred CIO/operator/collector processes as soon as
    the release diagnostic completes. Without this quiet period provider validation would
    start at the same instant, recreating the transient import/RSS spike that can kill a
    2 GB Render instance. If another diagnostic appears during the quiet period, restart
    the wait rather than allowing overlap.
    """

    quiet = (
        _seconds(
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_POST_LANE_QUIET_SECONDS",
            _DEFAULT_POST_LANE_QUIET_SECONDS,
        )
        if quiet_seconds is None
        else float(quiet_seconds)
    )
    if quiet < 0:
        raise ValueError("quiet_seconds cannot be negative")

    while not stopping.is_set():
        if not _wait_for_diagnostic_memory_lane(stopping, poll_seconds=poll_seconds):
            return False
        if quiet > 0:
            _log(
                "provider_validation_memory_quiet_period_started",
                quiet_seconds=quiet,
                heavy_provider_modules_loaded=False,
            )
            if stopping.wait(quiet):
                return False
        if not _diagnostic_active():
            return True
        _log(
            "provider_validation_quiet_period_interrupted",
            provider_validation_deferred=True,
        )
    return False


def validate_live_providers():
    """Lazy compatibility seam used only by the short-lived ``--once`` child."""

    from operations.provider_validation import validate_live_providers as implementation

    return implementation()


def write_provider_validation_report(report):
    """Lazy compatibility seam for persisted governed provider-validation evidence."""

    from operations.provider_validation import (
        write_provider_validation_report as implementation,
    )

    return implementation(report)


def validate_once() -> tuple["ProviderValidationReport", Path]:
    """Run one validation pass in the current process.

    The long-lived loop never calls this function directly; it is reserved for the
    short-lived ``--once`` child so heavy imports are released when that child exits.
    """

    report = validate_live_providers()
    report_path = write_provider_validation_report(report)
    _log(
        "provider_validation_completed",
        ready=report.ready,
        release=report.release,
        failed_required_checks=list(report.failed_required_checks),
        report_path=str(report_path),
    )
    return report, report_path


def _run_isolated_validation(
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    """Run one provider pass in a bounded child so RSS cannot remain resident.

    Reuses the diagnostic watchdog's container-memory accounting and process-group
    termination. Provider validation is operational evidence only, so a memory-bound pass
    fails closed and waits for the next interval instead of risking service availability.
    """

    resolved = dict(os.environ if values is None else values)
    timeout = (
        _seconds(
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_TIMEOUT_SECONDS",
            _DEFAULT_VALIDATION_TIMEOUT_SECONDS,
        )
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if timeout <= 0:
        raise ValueError("provider validation timeout must be positive")

    # Import only the lightweight watchdog utilities in the coordinator. The heavy
    # provider stack remains confined to the --once child process.
    import run_bounded_manual_cio_diagnostic as memory_watchdog

    script = Path(__file__).resolve()
    process = subprocess.Popen(
        (sys.executable, str(script), "--once"),
        env=resolved,
        cwd=str(script.parent),
        start_new_session=(os.name == "posix"),
    )
    _log(
        "provider_validation_isolated_child_started",
        pid=process.pid,
        heavy_provider_modules_loaded_in_coordinator=False,
    )

    return_code, timed_out, memory_limited, process_peak_kib, container_peak_kib = (
        memory_watchdog._wait_with_resource_bounds(
            process,
            timeout_seconds=timeout,
            memory_high_water_fraction=memory_watchdog._memory_high_water_fraction(resolved),
            values=resolved,
            memory_reserve_kib=memory_watchdog._memory_reserve_kib(resolved),
            poll_seconds=memory_watchdog._memory_poll_seconds(resolved),
        )
    )
    if timed_out:
        return_code = memory_watchdog._terminate(process)
        _log(
            "provider_validation_isolated_child_timed_out",
            return_code=return_code,
            process_peak_rss_kib=process_peak_kib,
            container_peak_memory_kib=container_peak_kib,
        )
        return 124
    if memory_limited:
        return_code = memory_watchdog._terminate(process)
        _log(
            "provider_validation_isolated_child_memory_limited",
            return_code=return_code,
            process_peak_rss_kib=process_peak_kib,
            container_peak_memory_kib=container_peak_kib,
            service_oom_prevented=True,
        )
        return 125

    _log(
        "provider_validation_isolated_child_finished",
        return_code=return_code,
        process_peak_rss_kib=process_peak_kib,
        container_peak_memory_kib=container_peak_kib,
        heavy_provider_modules_retained_in_coordinator=False,
    )
    return int(return_code or 0)


def run_loop(
    *,
    interval_seconds: float | None = None,
    initial_delay_seconds: float | None = None,
    stop_event: Event | None = None,
) -> int:
    """Continuously refresh validation evidence without retaining its heavy stack."""

    interval = (
        _seconds(
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_INTERVAL_SECONDS",
            _DEFAULT_INTERVAL_SECONDS,
        )
        if interval_seconds is None
        else float(interval_seconds)
    )
    initial_delay = (
        _seconds(
            "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_INITIAL_DELAY_SECONDS",
            _DEFAULT_INITIAL_DELAY_SECONDS,
        )
        if initial_delay_seconds is None
        else float(initial_delay_seconds)
    )
    if interval <= 0:
        raise ValueError("interval_seconds must be positive")
    if initial_delay < 0:
        raise ValueError("initial_delay_seconds cannot be negative")

    stopping = stop_event or Event()

    def request_stop(signum: int, frame: FrameType | None) -> None:
        del frame
        _log("shutdown_requested", signal=signum)
        stopping.set()

    previous_handlers: dict[signal.Signals, object] = {}
    if stop_event is None:
        previous_handlers = {
            signal.SIGTERM: signal.signal(signal.SIGTERM, request_stop),
            signal.SIGINT: signal.signal(signal.SIGINT, request_stop),
        }

    try:
        _log(
            "provider_validation_worker_started",
            initial_delay_seconds=initial_delay,
            interval_seconds=interval,
            heavy_provider_modules_loaded=False,
            isolated_validation_children=True,
        )
        if stopping.wait(initial_delay):
            return 0

        while not stopping.is_set():
            if not _wait_for_quiet_memory_lane(stopping):
                break
            try:
                return_code = _run_isolated_validation()
            except Exception as error:  # Coordinator boundary: never expose provider details.
                _log(
                    "provider_validation_iteration_failed",
                    error_type=type(error).__name__,
                )
            else:
                if return_code != 0:
                    _log(
                        "provider_validation_iteration_failed",
                        return_code=return_code,
                        memory_safe_retry_deferred=True,
                    )
            if stopping.wait(interval):
                break
        return 0
    finally:
        for handled_signal, previous in previous_handlers.items():
            signal.signal(handled_signal, previous)
        _log("provider_validation_worker_stopped")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)

    if args.once:
        try:
            validate_once()
        except Exception as error:  # Credential-safe CLI boundary.
            _log(
                "provider_validation_iteration_failed",
                error_type=type(error).__name__,
            )
            return 1
        return 0
    return run_loop()


if __name__ == "__main__":
    raise SystemExit(main())
