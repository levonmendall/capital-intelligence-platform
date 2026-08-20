"""Run Render with durable all-market evidence and isolated finite heavy jobs.

Deployment validates or selectively refreshes the continuous evidence plane before an
exact-release CIO diagnostic request is created. Heavy analytical and maintenance work is
executed through short-lived subprocesses sharing one exclusive memory lane, so allocator
state is returned to the OS between passes instead of accumulating in the serving process.

API and Streamlit remain the serving-critical boundary. A CIO, evidence, historical, or
backup worker failure is recorded and retried independently and cannot take the read-only
product offline. Comprehensive all-market coverage remains fail-closed and is never relaxed
by a transition mode, diagnostic, or operational capability scope. No investment rule,
threshold, construction, paper-execution authority, or real-money capability changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Mapping, MutableMapping, Sequence

import run_render_service as render_supervisor
import run_render_service_nonblocking as render_bootstrap
from operations.release_evidence_prequalification import (
    write_release_evidence_prequalification,
)


_ORIGINAL_MANAGED_PROCESSES = render_supervisor.managed_processes
_PROVIDER_VALIDATION_BACKGROUND_ENABLED = False
_QUALIFIER_FAILURE_CONTEXT_EVENT = "continuous_evidence_plane_failure_context"


def _positive_int(
    values: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw = str(values.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _nonnegative_seconds(
    values: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = str(values.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric") from error
    if value < 0:
        raise ValueError(f"{name} cannot be negative")
    return value


def _qualifier_metrics(
    *,
    attempt: int,
    maximum_attempts: int,
    return_code: int | None = None,
    generation_missing: bool = False,
) -> dict[str, int]:
    metrics = {
        "attempt": attempt,
        "maximum_attempts": maximum_attempts,
    }
    if return_code is not None:
        metrics["qualifier_return_code"] = abs(int(return_code))
        metrics["qualifier_return_code_negative"] = int(int(return_code) < 0)
    if generation_missing:
        metrics["qualified_generation_missing"] = 1
    return metrics


def _qualifier_failure_context(stderr: object) -> dict[str, str] | None:
    """Extract only the child's explicitly credential-safe structured failure record."""

    if not isinstance(stderr, str) or not stderr.strip():
        return None
    for raw_line in reversed(stderr.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if payload.get("event") != _QUALIFIER_FAILURE_CONTEXT_EVENT:
            continue
        if payload.get("credential_safe") is not True:
            continue
        if payload.get("paper_only") is not True:
            continue
        if payload.get("real_money_authorized") is not False:
            continue
        error_type = str(payload.get("error_type") or "").strip()[:120]
        failure_stage = str(payload.get("failure_stage") or "").strip()[:160]
        error_detail = str(payload.get("error_detail") or "").strip()[:1600]
        if not error_type or not error_detail:
            continue
        return {
            "error_type": error_type,
            "failure_stage": failure_stage or "continuous_evidence_plane",
            "error_detail": error_detail,
        }
    return None


def memory_safe_managed_processes(
    *,
    port: int,
    python_executable: str | None = None,
) -> tuple[render_supervisor.ManagedProcess, ...]:
    """Return a serving-safe process graph with finite heavyweight work."""

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
                # Investment availability is fail-closed independently from serving
                # availability. A failed CIO coordinator may not take the read-only
                # dashboard/API offline or erase its durable terminal evidence.
                critical=False,
                restart_delay_seconds=60,
            )
        elif spec.name == "global-public-evidence":
            spec = render_supervisor.ManagedProcess(
                name=spec.name,
                command=(
                    python,
                    "run_bounded_render_worker.py",
                    "global-public-evidence",
                    "--loop",
                    "--initial-delay-seconds",
                    "300",
                ),
                critical=False,
                restart_delay_seconds=60,
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
                critical=False,
                restart_delay_seconds=300,
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
                critical=False,
                restart_delay_seconds=300,
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
    """Publish one exact-release all-market generation before any CIO request exists.

    Evidence qualification is intentionally resumable. A transient provider, memory-lane,
    or child-process failure never creates a CIO request and never causes the CIO to repair
    evidence. Instead the evidence owner retries in the same exclusive heavy-memory lane
    until a bounded release qualification budget is exhausted.
    """

    from operations.continuous_evidence_plane import load_latest_evidence_plane

    started_at = datetime.now(timezone.utc)
    maximum_attempts = _positive_int(
        diagnostic_values,
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_ATTEMPTS",
        6,
    )
    retry_seconds = _nonnegative_seconds(
        diagnostic_values,
        "CAPITAL_INTELLIGENCE_RELEASE_EVIDENCE_PREQUALIFICATION_RETRY_SECONDS",
        30.0,
    )
    status = write_release_evidence_prequalification(
        diagnostic_values,
        state="in_progress",
        stage="evidence_prequalifying",
        started_at=started_at,
        detail="validating release-independent comprehensive all-market evidence",
        metrics={
            "attempt": 1,
            "maximum_attempts": maximum_attempts,
            "complete_all_market_coverage_required": 1,
        },
    )
    prequalification_id = str(status["prequalification_id"])
    render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)

    evidence_command = (
        sys.executable,
        "run_bounded_continuous_evidence_plane.py",
        "--once",
    )

    for attempt in range(1, maximum_attempts + 1):
        if attempt > 1:
            write_release_evidence_prequalification(
                diagnostic_values,
                state="in_progress",
                stage="evidence_refresh",
                prequalification_id=prequalification_id,
                started_at=started_at,
                detail=(
                    f"retrying comprehensive all-market evidence qualification attempt "
                    f"{attempt} of {maximum_attempts}"
                ),
                metrics={
                    "attempt": attempt,
                    "maximum_attempts": maximum_attempts,
                    "complete_all_market_coverage_required": 1,
                },
            )
            render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)

        render_bootstrap._log(
            "release_evidence_prequalification_starting",
            command=list(evidence_command),
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            prequalification_id=prequalification_id,
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            diagnostic_request_created=False,
            exact_release_required=True,
            complete_all_market_coverage_required=True,
            paper_only=True,
        )

        completed: subprocess.CompletedProcess | None = None
        start_error: OSError | None = None
        try:
            completed = subprocess.run(
                evidence_command,
                env=dict(diagnostic_values),
                check=False,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            start_error = error

        generation = None
        return_code: int | None = None
        qualifier_context: dict[str, str] | None = None
        if completed is not None:
            return_code = int(completed.returncode)
            qualifier_context = _qualifier_failure_context(completed.stderr)
            if return_code == 0:
                generation = load_latest_evidence_plane(diagnostic_values)

        if return_code == 0 and generation is not None:
            write_release_evidence_prequalification(
                diagnostic_values,
                state="completed",
                stage="evidence_generation_ready",
                prequalification_id=prequalification_id,
                started_at=started_at,
                detail="immutable exact-release comprehensive all-market generation ready",
                generation_id=generation.generation_id,
                metrics={
                    "attempt": attempt,
                    "maximum_attempts": maximum_attempts,
                    "scheduled_lanes": len(generation.scheduled_lanes),
                    "historical_scope_count": generation.historical_scope_count,
                    "complete_all_market_coverage_required": 1,
                },
            )
            render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
            render_bootstrap._log(
                "release_evidence_prequalification_finished",
                return_code=0,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                prequalification_id=prequalification_id,
                generation_id=generation.generation_id,
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                complete_all_market_coverage_required=True,
                diagnostic_request_created=False,
                paper_only=True,
            )
            return True

        generation_missing = return_code == 0 and generation is None
        failure_stage: str | None = None
        failure_error_detail: str | None = None
        if start_error is not None:
            failure_detail = (
                "evidence qualifier could not start: " + type(start_error).__name__
            )
            metrics = {
                "attempt": attempt,
                "maximum_attempts": maximum_attempts,
                "qualifier_start_failed": 1,
                "complete_all_market_coverage_required": 1,
            }
            error_type = type(start_error).__name__
        elif generation_missing:
            failure_detail = "evidence qualifier returned success without a qualified generation"
            metrics = _qualifier_metrics(
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                return_code=0,
                generation_missing=True,
            )
            metrics["complete_all_market_coverage_required"] = 1
            error_type = None
        else:
            metrics = _qualifier_metrics(
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                return_code=return_code,
            )
            metrics["complete_all_market_coverage_required"] = 1
            if qualifier_context is None:
                failure_detail = f"bounded evidence qualification returned code {return_code}"
                error_type = None
            else:
                failure_stage = qualifier_context["failure_stage"]
                error_type = qualifier_context["error_type"]
                failure_error_detail = qualifier_context["error_detail"]
                failure_detail = (
                    f"bounded evidence qualification returned code {return_code}; "
                    f"child_stage={failure_stage}; child_error_type={error_type}; "
                    f"child_detail={failure_error_detail}"
                )

        if attempt < maximum_attempts:
            write_release_evidence_prequalification(
                diagnostic_values,
                state="in_progress",
                stage="evidence_refresh",
                prequalification_id=prequalification_id,
                started_at=started_at,
                detail=(
                    failure_detail
                    + f"; retrying after bounded backoff ({attempt}/{maximum_attempts})"
                ),
                metrics=metrics,
            )
            render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
            render_bootstrap._log(
                "release_evidence_prequalification_retrying",
                return_code=return_code,
                error_type=error_type,
                failure_stage=failure_stage,
                failure_detail=failure_error_detail,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                prequalification_id=prequalification_id,
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                retry_seconds=retry_seconds,
                complete_all_market_coverage_required=True,
                diagnostic_request_created=False,
                paper_only=True,
            )
            if retry_seconds:
                time.sleep(retry_seconds)
            continue

        write_release_evidence_prequalification(
            diagnostic_values,
            state="failed",
            stage="evidence_prequalification_failed",
            prequalification_id=prequalification_id,
            started_at=started_at,
            detail=failure_detail,
            metrics=metrics,
        )
        render_bootstrap._publish_release_diagnostic_audit(diagnostic_values)
        render_bootstrap._log(
            "release_evidence_prequalification_failed",
            return_code=return_code,
            error_type=error_type,
            failure_stage=failure_stage,
            failure_detail=failure_error_detail,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            prequalification_id=prequalification_id,
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            complete_all_market_coverage_required=True,
            diagnostic_request_created=False,
            paper_only=True,
        )
        return False

    return False


def _start_release_diagnostic_after_prequalification(
    values: MutableMapping[str, str],
) -> threading.Thread | None:
    """Qualify complete evidence first, then create and run the governed CIO request."""

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
    """Run serving continuously while finite heavy jobs serialize through one lane."""

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

    # Comprehensive all-market discovery is a governed requirement from deployment
    # configuration. Transition modes may describe provider limitations but may never
    # silently weaken the certification requirement.
    if render_bootstrap._enabled(
        values,
        "CAPITAL_INTELLIGENCE_BOND_SOURCE_TRANSITION_MODE",
        default=False,
    ):
        render_bootstrap._log(
            "bond_source_transition_mode_enabled",
            comprehensive_discovery_required=render_bootstrap._enabled(
                values,
                "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY",
                default=True,
            ),
            direct_bond_discovery_authority=False,
            degraded_scope_disclosed=True,
            listed_bond_wrappers_remain_available=True,
            certification_requirement_relaxed=False,
        )

    previous_managed_processes = render_supervisor.managed_processes
    previous_background_flag = _PROVIDER_VALIDATION_BACKGROUND_ENABLED
    _PROVIDER_VALIDATION_BACKGROUND_ENABLED = background_enabled
    render_supervisor.managed_processes = memory_safe_managed_processes
    try:
        _start_release_diagnostic_after_prequalification(values)
        render_bootstrap._log(
            "production_runtime_v2_started",
            serving_failure_domain=("api", "streamlit"),
            finite_heavy_jobs=True,
            deferred_worker_thundering_herd=False,
            complete_all_market_coverage_required=render_bootstrap._enabled(
                values,
                "CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY",
                default=True,
            ),
            paper_only=True,
            real_money_authorized=False,
        )
        # Do not hold the whole operating stack behind a diagnostic-completion barrier.
        # Finite workers independently contend for the exclusive heavy-memory lane and
        # retry with bounded delays; serving remains available throughout.
        return render_supervisor.run_supervisor(environment=values)
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
