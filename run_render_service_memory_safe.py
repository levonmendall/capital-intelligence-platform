"""Run the Render service with post-diagnostic heavyweight memory isolation.

The release diagnostic already owns an exclusive startup window, but the legacy supervisor
released every deferred background process at the same instant when that diagnostic ended.
On a 2 GB Render instance, the combined imports/working sets of the CIO operator, historical
backfill, backup, and provider validation could therefore OOM-kill the instance even when
each individual task was bounded.

This entrypoint preserves the existing supervisor and governed release diagnostic while
replacing heavyweight resident loops with lightweight coordinators.  Each expensive pass
runs in a short-lived, memory-bounded child and shares one cross-process memory lane.
Noncritical jobs are staggered after the release diagnostic.  No market scope, CIO rule,
threshold, construction logic, paper-execution authority, or real-money capability changes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import MutableMapping, Sequence

import run_render_service as render_supervisor
import run_render_service_nonblocking as render_bootstrap


_ORIGINAL_MANAGED_PROCESSES = render_supervisor.managed_processes


def memory_safe_managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
) -> tuple[render_supervisor.ManagedProcess, ...]:
    """Replace only heavyweight resident loops with bounded coordinators."""

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
    return tuple(resolved)


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
    render_supervisor.managed_processes = memory_safe_managed_processes
    try:
        # The durable diagnostic request is primed before the provider coordinator starts,
        # preserving the existing fail-closed release ordering.
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
