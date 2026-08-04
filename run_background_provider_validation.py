"""Refresh live-provider readiness without blocking Render web startup.

The report produced here remains an operational prerequisite for governed CIO analysis
and paper implementation. This worker is deliberately noncritical to web availability:
provider outages or slow responses are recorded in the readiness report while the
authenticated console and health endpoint remain online.

When explicitly enabled, the worker also launches one paper-only diagnostic CIO pass per
release after the first provider-validation attempt. That pass bypasses only the calendar
due check; every evidence, specialist, CIO, construction, and paper-execution control
remains active and fail-closed.
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
from typing import Sequence

from operations.provider_validation import (
    ProviderValidationReport,
    validate_live_providers,
    write_provider_validation_report,
)

_DEFAULT_INTERVAL_SECONDS = 3600.0
_DEFAULT_INITIAL_DELAY_SECONDS = 5.0


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


def validate_once() -> tuple[ProviderValidationReport, Path]:
    """Run one credential-safe validation pass and persist its governed report."""

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


def _run_release_diagnostic() -> None:
    """Launch the bounded diagnostic without making it a web-service dependency."""

    try:
        completed = subprocess.run(
            (sys.executable, "run_manual_cio_diagnostic.py"),
            env=dict(os.environ),
            check=False,
        )
    except OSError as error:
        _log(
            "manual_cio_diagnostic_launch_failed",
            error_type=type(error).__name__,
        )
        return
    _log(
        "manual_cio_diagnostic_process_finished",
        return_code=completed.returncode,
    )


def run_loop(
    *,
    interval_seconds: float | None = None,
    initial_delay_seconds: float | None = None,
    stop_event: Event | None = None,
) -> int:
    """Continuously refresh validation evidence without terminating the web service."""

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

    diagnostic_attempted = False
    try:
        _log(
            "provider_validation_worker_started",
            initial_delay_seconds=initial_delay,
            interval_seconds=interval,
        )
        if stopping.wait(initial_delay):
            return 0
        while not stopping.is_set():
            try:
                validate_once()
            except Exception as error:  # Worker boundary: never expose provider details.
                _log(
                    "provider_validation_iteration_failed",
                    error_type=type(error).__name__,
                )
            if not diagnostic_attempted:
                _run_release_diagnostic()
                diagnostic_attempted = True
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
