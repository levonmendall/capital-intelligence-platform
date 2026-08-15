"""Run Render with component-qualified evidence ahead of the CIO diagnostic.

Deployment first validates or selectively refreshes the continuous evidence plane in the
exclusive heavy-memory lane. Only after an immutable exact-release generation exists is a
CIO diagnostic request created. The diagnostic itself is a disk-only consumer and cannot
perform provider/reference/public acquisition.

Provider validation and the normal heavy operating stack remain deferred behind the same
startup gate, so evidence qualification cannot race another heavyweight worker on the
constrained Render instance. No market scope, investment rule, threshold, construction,
paper-execution authority, or real-money capability changes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from typing import MutableMapping, Sequence

import run_render_service as render_supervisor
import run_render_service_nonblocking as render_bootstrap
from operations.release_evidence_prequalification import (
    write_release_evidence_prequalification,
)


_ORIGINAL_MANAGED_PROCESSES = render_supervisor.managed_processes
_PROVIDER_VALIDATION_BACKGROUND_ENABLED = False


def memory_safe_managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
) -> tuple[render_supervisor.ManagedProcess, ...]:
    """Replace heavyweight loops and serialize all post-diagnostic heavy workers."""

    python = python_executable or sys.executable
    resolved: list[render_supervisor.ManagedProcess] = []
    for spec in _ORIGINAL_MANAGED_PROCESSES(
        port=port,
        python_executable=python_executable,
    ):
        if spec.name == "cio-paper-operator":
            spec = render_supervisor.ManagedProcess(
                name=spec.name,
                command=(
                    python,
                    "run_bounded_render_worker.py",
                    "cio-paper-operator",
                    "--loop",
                    "--initial-delay-seconds",
                    "90",
                ),
                critical=spec.critical,
                restart_delay_seconds=spec.restart_delay_seconds,
            )
        elif spec.name == "historical-backfill":
            spec = render_supervisor.ManagedProcess(
                name=spec.name,
                command=(
                    python,
                    "run_bounded_render_worker.py",
                    "historical-backfill",
                    "--loop",
                    "--initial-delay-seconds",
                    "1800",
                ),
                critical=spec.critical,
                restart_delay_seconds=spec.restart_delay_seconds,
            )
        elif spec.name == "encrypted-backup":
            spec = render_supervisor.ManagedProcess(
                name=spec.name,
                command=(
                    python,
                    "run_bounded_render_worker.py",
                    "encrypted-backup",
                    "--loop",
                    "--initial-delay-seconds",
                    "900",
                ),
                critical=spec.critical,
                restart_delay_seconds=spec.restart_delay_seconds,
            )
        resolved.append(spec)

    resolved.append(
        render_supervisor.ManagedProcess(
            name="continuous-evidence-plane",
            command=(python, "run_bounded_continuous_evidence_plane.py"),
            critical=False,
            restart_delay_seconds=60,
        )
    )
    if _PROVIDER_VALIDATION_BACKGROUND_ENABLED:
        resolved.append(
            render_supervisor.ManagedProcess(
                name="provider-validation",
                command=(
                    python,
                    "run_locked_background_provider_validation.py",
                    "--loop",
                ),
                critical=False,
                restart_delay_seconds=60,
            )
        )
    return tuple(resolved)


def _prequalify_release_evidence(
    diagnostic_values: MutableMapping[str, str],
) -> bool:
    """Publish one exact-release generation before any CIO request exists."""

    from operations.continuous_evidence_plane import load_latest_evidence_plane

    started_at = datetime.now(timezone.utc)
    status = write_release_evidence_prequalification(
        diagnostic_values,
        state="in_progress",
        stage="evidence_prequalifying",
        started_at=started_at,
        detail="validating release-independent evidence components",
    )
    prequalification_id = str(status["prequalification_id"])
    render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)

    evidence_command = (
        sys.executable,
        "run_bounded_continuous_evidence_plane.py",
        "--once",
    )
    render_bootstrap._log(
        "release_evidence_prequalification_starting",
        command=list(evidence_command),
        release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        prequalification_id=prequalification_id,
        diagnostic_request_created=False,
        exact_release_required=True,
        paper_only=True,
    )
    try:
        completed = subprocess.run(
            evidence_command,
            env=dict(diagnostic_values),
            check=False,
        )
    except OSError as error:
        write_release_evidence_prequalification(
            diagnostic_values,
            state="failed",
            stage="evidence_prequalification_failed",
            prequalification_id=prequalification_id,
            started_at=started_at,
            detail=f"evidence qualifier could not start: {type(error).__name__}",
        )
        render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
        render_bootstrap._log(
            "release_evidence_prequalification_start_failed",
            error_type=type(error).__name__,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_request_created=False,
            paper_only=True,
        )
        return False

    if completed.returncode != 0:
        write_release_evidence_prequalification(
            diagnostic_values,
            state="failed",
            stage="evidence_prequalification_failed",
            prequalification_id=prequalification_id,
            started_at=started_at,
            detail=f"bounded evidence qualification returned code {completed.returncode}",
        )
        render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
        render_bootstrap._log(
            "release_evidence_prequalification_failed",
            return_code=completed.returncode,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_request_created=False,
            paper_only=True,
        )
        return False

    generation = load_latest_evidence_plane(diagnostic_values)
    if generation is None:
        write_release_evidence_prequalification(
            diagnostic_values,
            state="failed",
            stage="evidence_prequalification_failed",
            prequalification_id=prequalification_id,
            started_at=started_at,
            detail="evidence qualifier returned success without a qualified generation",
        )
        render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
        return False

    write_release_evidence_prequalification(
        diagnostic_values,
        state="completed",
        stage="evidence_generation_ready",
        prequalification_id=prequalification_id,
        started_at=started_at,
        detail="immutable exact-release evidence generation ready",
        generation_id=generation.generation_id,
        metrics={
            "scheduled_lanes": len(generation.scheduled_lanes),
            "historical_scope_count": generation.historical_scope_count,
        },
    )
    render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
    render_bootstrap._log(
        "release_evidence_prequalification_finished",
        return_code=0,
        release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        prequalification_id=prequalification_id,
        generation_id=generation.generation_id,
        diagnostic_request_created=False,
        paper_only=True,
    )
    return True


def _start_release_diagnostic_after_prequalification(
    values: MutableMapping[str, str],
) -> threading.Thread | None:
    """Qualify evidence first, then create and run the governed CIO request."""

    if not render_bootstrap._enabled(
        values,
        "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE",
        default=False,
    ):
        return None

    def qualify_then_run() -> None:
        diagnostic_values = render_bootstrap._release_diagnostic_environment(values)
        if not _prequalify_release_evidence(diagnostic_values):
            return
        # The CIO request is created only after evidence_generation_ready is durable.
        render_bootstrap.prime_release_diagnostic_request(values)
        not_before = datetime.now(timezone.utc)
        render_bootstrap._run_release_diagnostic_after_readiness(
            values,
            not_before=not_before,
        )

    thread = threading.Thread(
        name="release-evidence-then-cio-diagnostic",
        target=qualify_then_run,
        daemon=True,
    )
    thread.start()
    render_bootstrap._log(
        "release_evidence_prequalification_armed",
        release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        diagnostic_request_created=False,
        complete_all_market_coverage_required=True,
        paper_only=True,
    )
    return thread


def run_memory_safe_render_service(
    environment: MutableMapping[str, str] | None = None,
) -> int:
    """Run the existing supervisor with one serialized heavyweight-memory lane."""

    global _PROVIDER_VALIDATION_BACKGROUND_ENABLED

    values = render_supervisor.prepare_render_environment(
        os.environ if environment is None else environment
    )
    try:
        storage_report = render_bootstrap.reclaim_from_environment(values)
    except (OSError, TypeError, ValueError) as error:
        render_bootstrap._log(
            "persistent_storage_recovery_failed",
            error_type=type(error).__name__,
            canonical_authorities_deleted=False,
        )
    else:
        render_bootstrap._log("persistent_storage_checked", **storage_report.to_dict())

    background_enabled = render_bootstrap._enabled(
        values,
        "CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_BACKGROUND_ENABLED",
        default=True,
    )
    if background_enabled:
        values["CAPITAL_INTELLIGENCE_RUN_PROVIDER_VALIDATION_ON_STARTUP"] = "false"

    bond_source_transition = render_bootstrap._enabled(
        values,
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE",
        default=False,
    )
    if bond_source_transition:
        values["CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY"] = "false"
        render_bootstrap._log(
            "bond_source_transition_mode_enabled",
            comprehensive_discovery_required=False,
            direct_bond_discovery_authority=False,
            degraded_scope_disclosed=True,
            listed_bond_wrappers_remain_available=True,
        )

    previous_managed_processes = render_supervisor.managed_processes
    previous_background_flag = _PROVIDER_VALIDATION_BACKGROUND_ENABLED
    _PROVIDER_VALIDATION_BACKGROUND_ENABLED = background_enabled
    render_supervisor.managed_processes = memory_safe_managed_processes
    try:
        diagnostic_thread = _start_release_diagnostic_after_prequalification(values)
        deferred_start_ready = render_bootstrap._diagnostic_completion_gate(diagnostic_thread)
        if deferred_start_ready is None:
            return render_supervisor.run_supervisor(environment=values)
        return render_supervisor.run_supervisor(
            environment=values,
            deferred_start_ready=deferred_start_ready,
        )
    finally:
        render_supervisor.managed_processes = previous_managed_processes
        _PROVIDER_VALIDATION_BACKGROUND_ENABLED = previous_background_flag
        render_bootstrap._log("render_memory_safe_bootstrap_stopped")


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError(
            "run_render_service_memory_safe.py does not accept command-line arguments"
        )
    try:
        return run_memory_safe_render_service()
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, RuntimeError) as error:
        render_bootstrap._log(
            "render_memory_safe_bootstrap_failed",
            error_type=type(error).__name__,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())