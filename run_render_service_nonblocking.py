"""Start the Render web service before live-provider validation completes.

Core datastore and market-scope initialization still completes synchronously. Slow or
unavailable external providers are validated by a separate noncritical worker, allowing
Streamlit to open Render's health-check port promptly. Existing readiness gates continue
to prevent CIO analysis and paper implementation from using missing or stale provider
evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import MutableMapping, Sequence

from run_render_service import prepare_render_environment, run_supervisor


def _enabled(values: MutableMapping[str, str], name: str, *, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _log(event: str, **details: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "service": "capital-intelligence-render-bootstrap",
                "timestamp": time.time(),
                "real_money_authorized": False,
                **details,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _terminate(process: subprocess.Popen[bytes] | subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_nonblocking_render_service(
    environment: MutableMapping[str, str] | None = None,
) -> int:
    """Run the existing supervisor with provider validation detached from startup."""

    values = prepare_render_environment(os.environ if environment is None else environment)
    background_enabled = _enabled(
        values,
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED",
        default=True,
    )
    if background_enabled:
        values["CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"] = "false"

    validation_process: subprocess.Popen[bytes] | subprocess.Popen[str] | None = None
    try:
        if background_enabled:
            try:
                validation_process = subprocess.Popen(
                    (sys.executable, "run_background_provider_validation.py", "--loop"),
                    env=dict(values),
                )
            except OSError as error:
                _log(
                    "provider_validation_worker_start_failed",
                    error_type=type(error).__name__,
                )
            else:
                _log(
                    "provider_validation_worker_started",
                    pid=validation_process.pid,
                )
        return run_supervisor(environment=values)
    finally:
        _terminate(validation_process)
        _log("render_bootstrap_stopped")


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError(
            "run_render_service_nonblocking.py does not accept command-line arguments"
        )
    try:
        return run_nonblocking_render_service()
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, RuntimeError) as error:
        _log("render_bootstrap_failed", error_type=type(error).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
