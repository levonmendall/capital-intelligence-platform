"""Run the Render service with post-diagnostic heavyweight memory isolation.

The release diagnostic owns an exclusive startup window, and the legacy supervisor
releases deferred background processes only after that diagnostic ends. On a 2 GB Render
instance, heavyweight provider/discovery work is therefore run through one serialized,
memory-bounded lane.

Before every release diagnostic attempt this entrypoint now runs one bounded continuous-
evidence maintenance pass. The diagnostic itself only consumes the resulting exact-release
point-in-time generation; it cannot synchronously acquire provider/reference/public data.
The normal continuous coordinator remains deferred until the release diagnostic finishes.
No market scope, CIO rule, threshold, construction logic, paper-execution authority, or
real-money capability changes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import MutableMapping, Sequence

import run_render_service as render_supervisor
import run_render_service_nonblocking as render_bootstrap


_ORIGINAL_MANAGED_PROCESSES = render_supervisor.managed_processes
_ORIGINAL_RELEASE_DIAGNOSTIC_EXECUTOR = (
    render_bootstrap._run_release_diagnostic_with_live_audit
)


def memory_safe_managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
) -> tuple[render_supervisor.ManagedProcess, ...]:
    """Replace heavyweight loops and add the bounded continuous evidence coordinator."""

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

    # The normal coordinator remains noncritical and deferred until the release
    # diagnostic gate opens. Release attempts receive their own one-shot bounded pass.
    resolved.append(
        render_supervisor.ManagedProcess(
            name="continuous-evidence-plane",
            command=(python, "run_bounded_continuous_evidence_plane.py"),
            critical=False,
            restart_delay_seconds=60,
        )
    )
    return tuple(resolved)


def _run_release_diagnostic_with_prequalified_evidence(
    command: Sequence[str],
    *,
    diagnostic_values: MutableMapping[str, str],
    refresh_seconds: float = render_bootstrap._DEFAULT_RELEASE_DIAGNOSTIC_AUDIT_REFRESH_SECONDS,
) -> int:
    """Maintain exact-release evidence before invoking one bounded CIO attempt."""

    evidence_command = (
        sys.executable,
        "run_bounded_continuous_evidence_plane.py",
        "--once",
    )
    render_bootstrap._log(
        "release_evidence_prequalification_starting",
        command=list(evidence_command),
        release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
        exact_release_required=True,
        provider_work_inside_cio_diagnostic=False,
        paper_only=True,
    )
    try:
        completed = subprocess.run(
            evidence_command,
            env=dict(diagnostic_values),
            check=False,
        )
    except OSError as error:
        render_bootstrap._log(
            "release_evidence_prequalification_start_failed",
            error_type=type(error).__name__,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_will_fail_closed=True,
            paper_only=True,
        )
    else:
        render_bootstrap._log(
            "release_evidence_prequalification_finished",
            return_code=completed.returncode,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_will_fail_closed=completed.returncode != 0,
            paper_only=True,
        )

    # Always invoke the diagnostic. If maintenance failed, its production reference
    # loader performs no provider work and closes the request quickly with the missing/
    # stale prequalified-evidence reason, giving the verifier a terminal fail-closed state.
    return _ORIGINAL_RELEASE_DIAGNOSTIC_EXECUTOR(
        command,
        diagnostic_values=diagnostic_values,
        refresh_seconds=refresh_seconds,
    )


def run_memory_safe_render_service(
    environment: MutableMapping[str, str] | None = None,
) -> int:
    """Run the existing bootstrap with one serialized heavyweight-memory lane."""

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

    validation_process: subprocess.Popen[bytes] | subprocess.Popen[str] | None = None
    previous_managed_processes = render_supervisor.managed_processes
    previous_release_executor = render_bootstrap._run_release_diagnostic_with_live_audit
    render_supervisor.managed_processes = memory_safe_managed_processes
    render_bootstrap._run_release_diagnostic_with_live_audit = (
        _run_release_diagnostic_with_prequalified_evidence
    )
    try:
        # Prime the durable request before any background provider coordinator starts.
        # Each release attempt then enters the bounded evidence maintainer before the
        # disk-only CIO watchdog is invoked.
        diagnostic_thread = render_bootstrap._start_release_diagnostic(values)

        if background_enabled:
            try:
                validation_process = subprocess.Popen(
                    (
                        sys.executable,
                        "run_locked_background_provider_validation.py",
                        "--loop",
                    ),
                    env=dict(values),
                )
            except OSError as error:
                render_bootstrap._log(
                    "provider_validation_worker_start_failed",
                    error_type=type(error).__name__,
                )
            else:
                render_bootstrap._log(
                    "provider_validation_worker_started",
                    pid=validation_process.pid,
                    diagnostic_coordination_primed=diagnostic_thread is not None,
                    exclusive_heavy_memory_lane=True,
                )

        deferred_start_ready = render_bootstrap._diagnostic_completion_gate(diagnostic_thread)
        if deferred_start_ready is None:
            return render_supervisor.run_supervisor(environment=values)
        return render_supervisor.run_supervisor(
            environment=values,
            deferred_start_ready=deferred_start_ready,
        )
    finally:
        render_supervisor.managed_processes = previous_managed_processes
        render_bootstrap._run_release_diagnostic_with_live_audit = previous_release_executor
        render_bootstrap._terminate(validation_process)
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
