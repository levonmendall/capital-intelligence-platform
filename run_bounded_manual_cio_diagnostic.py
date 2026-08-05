"""Run one manual CIO diagnostic with explicit lifecycle logs and a hard deadline.

The underlying diagnostic remains the only component that can prepare evidence, invoke the
specialists and CIO, construct a portfolio, or attempt governed paper implementation. This
wrapper adds operational observability and prevents a stalled diagnostic from remaining
silent indefinitely. It never authorizes real money.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import (
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
)


_DEFAULT_TIMEOUT_SECONDS = 900.0


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


def _close_timed_out_request(
    *,
    values: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[str | None, str | None]:
    """Truthfully close only a request that the timed-out child had claimed."""

    existing = latest_manual_cio_diagnostic(values=values)
    if existing is None:
        return None, None
    if existing.state != "in_progress":
        return existing.request_id, existing.state
    finished = finish_manual_cio_diagnostic(
        existing,
        succeeded=False,
        cycle_key=existing.cycle_key,
        snapshot_identifier=existing.snapshot_identifier,
        detail=(
            "Manual CIO diagnostic exceeded its governed operational deadline of "
            f"{timeout_seconds:g} seconds and was terminated fail-closed."
        ),
        values=values,
    )
    return finished.request_id, finished.state


def run_bounded_diagnostic(
    *,
    values: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    release = _release(resolved)
    timeout = _timeout_seconds(resolved) if timeout_seconds is None else float(timeout_seconds)
    if timeout <= 0:
        raise ValueError("timeout_seconds must be positive")

    script = Path(__file__).resolve().with_name("run_manual_cio_diagnostic.py")
    _log(
        "manual_cio_diagnostic_run_started",
        release=release,
        timeout_seconds=timeout,
    )
    try:
        process = subprocess.Popen(
            (sys.executable, str(script)),
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

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
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
        )
        return 124

    _log(
        "manual_cio_diagnostic_process_finished",
        release=release,
        return_code=return_code,
    )
    return int(return_code)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        return run_bounded_diagnostic(timeout_seconds=args.timeout_seconds)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        _log(
            "manual_cio_diagnostic_watchdog_failed",
            error_type=type(error).__name__,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
