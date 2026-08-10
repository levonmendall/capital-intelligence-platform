"""Refresh live-provider readiness without blocking Render web startup.

The loop intentionally stays lightweight while a manual CIO diagnostic owns the constrained
Render memory lane. Heavy provider-validation imports are delayed until the memory lane is
open so a sleeping validation worker cannot consume avoidable resident memory during the
comprehensive all-market diagnostic.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from pathlib import Path
from threading import Event
from types import FrameType
from typing import TYPE_CHECKING, Sequence

from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic

if TYPE_CHECKING:
    from operations.provider_validation import ProviderValidationReport

_DEFAULT_INTERVAL_SECONDS = 3600.0
_DEFAULT_INITIAL_DELAY_SECONDS = 5.0
_DEFAULT_DIAGNOSTIC_POLL_SECONDS = 5.0
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


def validate_live_providers():
    """Lazy compatibility seam; do not load the heavy provider stack while deferred."""

    from operations.provider_validation import validate_live_providers as implementation

    return implementation()


def write_provider_validation_report(report):
    """Lazy compatibility seam for persisted governed provider-validation evidence."""

    from operations.provider_validation import (
        write_provider_validation_report as implementation,
    )

    return implementation(report)


def validate_once() -> tuple["ProviderValidationReport", Path]:
    """Run one validation pass; heavy provider modules load only at this boundary."""

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

    try:
        _log(
            "provider_validation_worker_started",
            initial_delay_seconds=initial_delay,
            interval_seconds=interval,
            heavy_provider_modules_loaded=False,
        )
        if stopping.wait(initial_delay):
            return 0

        while not stopping.is_set():
            if not _wait_for_diagnostic_memory_lane(stopping):
                break
            try:
                validate_once()
            except Exception as error:  # Worker boundary: never expose provider details.
                _log(
                    "provider_validation_iteration_failed",
                    error_type=type(error).__name__,
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
