"""Start the Render web service before live-provider validation completes.

Core datastore and market-scope initialization still completes synchronously. Slow or
unavailable external providers are validated by a separate noncritical worker, allowing
Streamlit to open Render's health-check port promptly. Existing readiness gates continue
to prevent CIO analysis and paper implementation from using missing or stale provider
evidence.

During the explicitly configured bond-source transition, comprehensive direct-market
discovery becomes an optional expansion rather than a prerequisite for the entire CIO
cycle. The governed publication already records that degraded scope and cannot represent
it as complete all-market coverage. The canonical listed-wrapper bond alternatives,
broad U.S.-security discovery, six-specialist review, CIO authority, portfolio
construction, paper-only execution, and real-money prohibition remain unchanged.

Before any child process starts, the bootstrap also checks the persistent disk reserve.
When the disk is under pressure it may remove only oldest canonical backup archives and
stale backup temporary files while preserving at least the configured newest archive.
Canonical databases, portfolio state, evidence, lineage, reports, and research records
are never deleted by this recovery path.

When explicitly enabled, one release diagnostic waits until the current API and Streamlit
children are healthy, then invokes the existing fully governed manual CIO diagnostic. The
diagnostic is one-shot, paper-only, requires complete all-market discovery even while the
long-running service remains in an explicit source transition, and is never restarted in
a loop by this bootstrap.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import MutableMapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from operations.composite_readiness import component_heartbeat_path
from operations.heartbeat import WorkerHeartbeatStore
from operations.storage_pressure import reclaim_from_environment
from run_render_service import prepare_render_environment, run_supervisor


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
        }
    )
    return diagnostic


def _release_diagnostic_command(
    values: MutableMapping[str, str],
    *,
    python_executable: str | None = None,
) -> tuple[str, ...]:
    command = [python_executable or sys.executable, "run_manual_cio_diagnostic.py"]
    if _enabled(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_FORCE_ON_RELEASE",
        default=False,
    ):
        command.append("--force")
    return tuple(command)


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


def _run_release_diagnostic_after_readiness(
    values: MutableMapping[str, str],
    *,
    not_before: datetime,
) -> None:
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
            "manual_cio_release_diagnostic_not_started",
            reason="current release API and Streamlit readiness was not observed",
            startup_wait_seconds=wait_seconds,
            paper_only=True,
        )
        return

    diagnostic_values = _release_diagnostic_environment(values)
    command = _release_diagnostic_command(diagnostic_values)
    _log(
        "manual_cio_release_diagnostic_starting",
        command=list(command),
        release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        complete_all_market_coverage_required=True,
        source_transition_disabled_for_diagnostic=True,
        paper_only=True,
    )
    try:
        completed = subprocess.run(command, env=diagnostic_values, check=False)
    except OSError as error:
        _log(
            "manual_cio_release_diagnostic_start_failed",
            error_type=type(error).__name__,
            paper_only=True,
        )
        return
    _log(
        "manual_cio_release_diagnostic_finished",
        return_code=completed.returncode,
        release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        complete_all_market_coverage_required=True,
        paper_only=True,
    )


def _start_release_diagnostic(
    values: MutableMapping[str, str],
) -> threading.Thread | None:
    if not _enabled(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE",
        default=False,
    ):
        return None
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
        _start_release_diagnostic(values)
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
