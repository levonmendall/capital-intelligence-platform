"""Start Render web availability while isolating release-diagnostic memory.

The release-triggered comprehensive CIO diagnostic preserves every evidence, discovery,
specialist, CIO, construction, and paper-only gate. On constrained Render instances the
bootstrap primes diagnostic coordination before the provider worker starts, defers the
normal heavyweight operating stack, and treats a memory-bound diagnostic as terminal for
that release attempt instead of immediately forcing the same workload to run again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from operations.composite_readiness import component_heartbeat_path
from operations.heartbeat import WorkerHeartbeatStore
from operations.storage_pressure import reclaim_from_environment
from prime_release_cio_diagnostic import prime_release_diagnostic_request
from run_render_service import prepare_render_environment, run_supervisor


_DEFAULT_RELEASE_DIAGNOSTIC_MAX_ATTEMPTS = 4
_MAX_RELEASE_DIAGNOSTIC_ATTEMPTS = 12
_DEFAULT_RELEASE_DIAGNOSTIC_RETRY_SECONDS = 75.0
_MAX_RELEASE_DIAGNOSTIC_RETRY_SECONDS = 600.0
_DEFAULT_RELEASE_DIAGNOSTIC_AUDIT_REFRESH_SECONDS = 15.0
_RESOURCE_LIMIT_RETURN_CODES = frozenset({125})


def _enabled(values: MutableMapping[str, str], name: str, *, default: bool) -> bool:
    raw = values.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_float(
    values: MutableMapping[str, str],
    name: str,
    *,
    default: float,
) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _positive_int(
    values: MutableMapping[str, str],
    name: str,
    *,
    default: int,
    maximum: int,
) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    if value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value


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


def _release_diagnostic_environment(
    values: MutableMapping[str, str],
) -> dict[str, str]:
    diagnostic = dict(values)
    diagnostic.update(
        {
            "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE": "false",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_MARKET_DISCOVERY": "true",
            "CAPITAL_INTELLIGENCE_DISCOVERY_REQUIRE_COMPLETE_MARKET_COVERAGE": "true",
            "CAPITAL_INTELLIGENCE_REQUIRE_LIVE_PROVIDER": "true",
            "CAPITAL_INTELLIGENCE_PROVIDER_RUNTIME_MODE": "live",
            "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_ENABLED": "true",
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_PROGRESS_ENABLED": "true",
        }
    )
    return diagnostic


def _release_diagnostic_command(
    values: MutableMapping[str, str],
    *,
    force: bool = False,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    command = [
        python_executable or sys.executable,
        "run_bounded_manual_cio_diagnostic.py",
    ]
    if force or _enabled(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_FORCE_ON_RELEASE",
        default=False,
    ):
        command.append("--force")
    return tuple(command)


def _release_diagnostic_audit_command(
    *,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    return (
        python_executable or sys.executable,
        "publish_cio_diagnostic_audit.py",
    )


def _publish_release_diagnostic_audit(
    values: MutableMapping[str, str],
) -> int | None:
    command = _release_diagnostic_audit_command()
    try:
        completed = subprocess.run(command, env=dict(values), check=False)
    except OSError as error:
        _log(
            "manual_cio_release_audit_publication_failed",
            error_type=type(error).__name__,
            paper_only=True,
        )
        return None
    _log(
        "manual_cio_release_audit_publication_finished",
        return_code=completed.returncode,
        release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        public_path="/app/static/cio-diagnostic.json",
        paper_only=True,
    )
    return completed.returncode


def _run_release_diagnostic_with_live_audit(
    command: Sequence[str],
    *,
    diagnostic_values: MutableMapping[str, str],
    refresh_seconds: float = _DEFAULT_RELEASE_DIAGNOSTIC_AUDIT_REFRESH_SECONDS,
) -> int:
    """Run the bounded diagnostic while republishing its durable redacted state."""

    process = subprocess.Popen(tuple(command), env=dict(diagnostic_values))
    while True:
        try:
            return process.wait(timeout=refresh_seconds)
        except subprocess.TimeoutExpired:
            _publish_release_diagnostic_audit(diagnostic_values)


def _release_components_ready(
    values: MutableMapping[str, str],
    *,
    not_before: datetime,
) -> bool:
    state_root = Path(values["CAPITAL_INTELLIGENCE_DATA_DIR"])
    for component in ("api", "streamlit"):
        try:
            heartbeat = WorkerHeartbeatStore(
                component_heartbeat_path(state_root, component)
            ).read()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if heartbeat is None or heartbeat.status != "healthy":
            return False
        if heartbeat.observed_at.astimezone(timezone.utc) < not_before:
            return False
    return True


def _release_diagnostic_retry_policy(
    values: MutableMapping[str, str],
) -> tuple[int, float]:
    max_attempts = _positive_int(
        values,
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_MAX_ATTEMPTS",
        default=_DEFAULT_RELEASE_DIAGNOSTIC_MAX_ATTEMPTS,
        maximum=_MAX_RELEASE_DIAGNOSTIC_ATTEMPTS,
    )
    retry_seconds = _positive_float(
        values,
        "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_RETRY_SECONDS",
        default=_DEFAULT_RELEASE_DIAGNOSTIC_RETRY_SECONDS,
    )
    if retry_seconds > _MAX_RELEASE_DIAGNOSTIC_RETRY_SECONDS:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_RELEASE_DIAGNOSTIC_RETRY_SECONDS "
            f"must be at most {_MAX_RELEASE_DIAGNOSTIC_RETRY_SECONDS:g}"
        )
    return max_attempts, retry_seconds


def _release_diagnostic_retryable(return_code: int) -> bool:
    """Never force-repeat a diagnostic that stopped to preserve service memory."""

    return int(return_code) not in _RESOURCE_LIMIT_RETURN_CODES


def _run_release_diagnostic_after_readiness(
    values: MutableMapping[str, str],
    *,
    not_before: datetime,
) -> None:
    diagnostic_values = _release_diagnostic_environment(values)
    _publish_release_diagnostic_audit(diagnostic_values)
    wait_seconds = _positive_float(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_WAIT_SECONDS",
        default=180.0,
    )
    poll_seconds = min(
        5.0,
        _positive_float(
            values,
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_STARTUP_POLL_SECONDS",
            default=1.0,
        ),
    )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _release_components_ready(values, not_before=not_before):
            break
        time.sleep(poll_seconds)
    else:
        _log(
            "manual_cio_release_diagnostic_readiness_wait_expired",
            reason=(
                "current release API and Streamlit readiness was not observed; "
                "continuing with the fully governed fail-closed diagnostic"
            ),
            startup_wait_seconds=wait_seconds,
            complete_all_market_coverage_required=True,
            paper_only=True,
        )

    max_attempts, retry_seconds = _release_diagnostic_retry_policy(values)
    for attempt in range(1, max_attempts + 1):
        command = _release_diagnostic_command(
            diagnostic_values,
            force=attempt > 1,
        )
        _log(
            "manual_cio_release_diagnostic_starting",
            command=list(command),
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            max_attempts=max_attempts,
            complete_all_market_coverage_required=True,
            source_transition_disabled_for_diagnostic=True,
            certified_reference_cache_reuse_allowed=True,
            paper_only=True,
        )
        try:
            return_code = _run_release_diagnostic_with_live_audit(
                command,
                diagnostic_values=diagnostic_values,
            )
        except OSError as error:
            _log(
                "manual_cio_release_diagnostic_start_failed",
                error_type=type(error).__name__,
                attempt=attempt,
                max_attempts=max_attempts,
                paper_only=True,
            )
            _publish_release_diagnostic_audit(diagnostic_values)
            return

        _publish_release_diagnostic_audit(diagnostic_values)
        _log(
            "manual_cio_release_diagnostic_finished",
            return_code=return_code,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            max_attempts=max_attempts,
            complete_all_market_coverage_required=True,
            paper_only=True,
        )
        if return_code == 0:
            return
        if not _release_diagnostic_retryable(return_code):
            _log(
                "manual_cio_release_diagnostic_resource_limit_terminal",
                return_code=return_code,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                attempt=attempt,
                retries_suppressed=True,
                complete_all_market_coverage_required=True,
                service_availability_preserved=True,
                paper_only=True,
            )
            return
        if attempt >= max_attempts:
            _log(
                "manual_cio_release_diagnostic_attempts_exhausted",
                return_code=return_code,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                attempts=max_attempts,
                complete_all_market_coverage_required=True,
                paper_only=True,
            )
            return

        _log(
            "manual_cio_release_diagnostic_retry_scheduled",
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            failed_attempt=attempt,
            next_attempt=attempt + 1,
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
            certified_reference_cache_reuse_allowed=True,
            complete_all_market_coverage_required=True,
            paper_only=True,
        )
        time.sleep(retry_seconds)


def _start_release_diagnostic(
    values: MutableMapping[str, str],
) -> threading.Thread | None:
    if not _enabled(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE",
        default=False,
    ):
        return None
    # Prime synchronously before any background provider worker starts. The worker can
    # therefore see the pending state before it has an opportunity to import or execute
    # the heavy provider-validation path.
    prime_release_diagnostic_request(values)
    not_before = datetime.now(timezone.utc)
    thread = threading.Thread(
        name="manual-cio-release-diagnostic",
        target=_run_release_diagnostic_after_readiness,
        kwargs={"values": values, "not_before": not_before},
        daemon=True,
    )
    thread.start()
    _log(
        "manual_cio_release_diagnostic_armed",
        release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        complete_all_market_coverage_required=True,
        paper_only=True,
    )
    return thread


def _diagnostic_completion_gate(
    diagnostic_thread: threading.Thread | None,
) -> Callable[[], bool] | None:
    if diagnostic_thread is None:
        return None
    return lambda: not diagnostic_thread.is_alive()


def run_nonblocking_render_service(
    environment: MutableMapping[str, str] | None = None,
) -> int:
    """Run the existing supervisor with provider validation detached from startup."""

    values = prepare_render_environment(os.environ if environment is None else environment)
    try:
        storage_report = reclaim_from_environment(values)
    except (OSError, TypeError, ValueError) as error:
        _log(
            "persistent_storage_recovery_failed",
            error_type=type(error).__name__,
            canonical_authorities_deleted=False,
        )
    else:
        _log("persistent_storage_checked", **storage_report.to_dict())

    background_enabled = _enabled(
        values,
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED",
        default=True,
    )
    if background_enabled:
        values["CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"] = "false"

    bond_source_transition = _enabled(
        values,
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE",
        default=False,
    )
    if bond_source_transition:
        values["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] = "false"
        _log(
            "bond_source_transition_mode_enabled",
            comprehensive_discovery_required=False,
            direct_bond_discovery_authority=False,
            degraded_scope_disclosed=True,
            listed_bond_wrappers_remain_available=True,
        )

    validation_process: subprocess.Popen[bytes] | subprocess.Popen[str] | None = None
    try:
        # Arm/prime the release diagnostic first. This closes the startup race in which
        # provider validation could begin before durable diagnostic coordination existed.
        diagnostic_thread = _start_release_diagnostic(values)

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
                    diagnostic_coordination_primed=diagnostic_thread is not None,
                )

        deferred_start_ready = _diagnostic_completion_gate(diagnostic_thread)
        if deferred_start_ready is None:
            return run_supervisor(environment=values)
        return run_supervisor(
            environment=values,
            deferred_start_ready=deferred_start_ready,
        )
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
