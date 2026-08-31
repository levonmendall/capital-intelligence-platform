"""Coordinate complete all-market evidence through fresh finite stage interpreters.

The coordinator is intentionally lightweight. It imports no provider, discovery, market
history, or paper-evidence stack. Each required evidence stage runs as a child process in
the same exclusive heavy-memory lane, commits its durable checkpoint, exits, and releases
its working set before the next stage begins.

A running attempt resumes the same still-fresh evidence epoch from the first incomplete
stage. A terminal failed attempt is archived and superseded by a fresh attempt so durable
stage stores are revalidated rather than allowing a failed operational journal to authorize
skipping work. No stage can be skipped, reordered, or treated as certified merely because
the coordinator survived. Missing or failed work remains fail-closed.

Comprehensive discovery additionally has an exact cross-process owner lease. The journal can
say that a stage is active, but only the lease proves whether the owner is still alive. A
second coordinator therefore observes a live owner without restarting or expiring it. Once
ownership is available, stale independently-sessioned DAG descendants are reaped by exact
PID/start-time identity before any restart/freshness decision.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.comprehensive_descendant_reaper import (
    reap_stale_comprehensive_descendants,
)
from operations.stage_isolated_evidence_pipeline import (
    _STAGES,
    _max_age_seconds,
    StageIsolatedEvidenceState,
    begin_evidence_stage,
    ensure_stage_isolated_evidence_pipeline,
    fail_evidence_stage,
    load_stage_isolated_evidence_state,
)
from operations.stage_owner_lease import StageOwnerLease, try_acquire_stage_owner


_FAILURE_EVENT = "continuous_evidence_plane_failure_context"
_DAG_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_REFERENCE_CACHE_RECLAMATION_EVENT = "stage_isolated_reference_cache_reclamation"
_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_EVENT = (
    "stage_isolated_comprehensive_discovery_cache_reclamation"
)
_FAILED_ATTEMPT_CACHE_RECLAMATION_EVENT = "stage_isolated_failed_attempt_cache_reclamation"
_REFERENCE_CACHE_RECLAMATION_TIMEOUT_SECONDS = 10.0
_STAGE_TERMINATION_GRACE_SECONDS = 5.0
_STAGE_FRESHNESS_EXPIRED_RETURN_CODE = 124
_STAGE_ACTIVE_OWNER_RETURN_CODE = 75
_STAGE_FRESHNESS_ERROR_TYPE = "EvidenceFreshnessExpired"
_STAGE_WRAPPER_INTERNAL_ERROR_RETURN_CODE = 2
_COMPREHENSIVE_STAGE = "comprehensive_discovery"
_COMPREHENSIVE_DISCOVERY_RESTART_RESERVE_SECONDS = 480.0
_PRECOMPREHENSIVE_CACHE_RECLAMATION_SCHEMA = "pre-comprehensive-cache-reclamation.v1"
_REFERENCE_CACHE_RECLAMATION_CODE = """
import os
from operations.evidence_file_cache_release import release_completed_operating_evidence_file_cache
release_completed_operating_evidence_file_cache(os.environ)
""".strip()
_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE = """
import json
import os
from operations.pre_comprehensive_cache_reclamation import release_pre_comprehensive_completed_stage_file_cache
report = release_pre_comprehensive_completed_stage_file_cache(os.environ)
print(json.dumps(report, sort_keys=True))
""".strip()


def _safe_failure(
    *,
    pipeline_id: str,
    stage: str,
    return_code: int,
    error_type: str | None,
    error_detail: str | None,
) -> None:
    detail = (
        f"stage_isolated_evidence_failure; stage={stage}; return_code={return_code}; "
        f"child_error_type={error_type or 'StageProcessError'}; "
        f"child_detail={error_detail or 'stage process exited before durable completion'}"
    )[:1600]
    print(
        json.dumps(
            {
                "event": _FAILURE_EVENT,
                "error_type": error_type or "StageProcessError",
                "failure_stage": f"stage_isolated_evidence:{stage}",
                "error_detail": detail,
                "pipeline_id": pipeline_id,
                "credential_safe": True,
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "construction_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
        flush=True,
    )


def _emit_active_stage_owner(state: StageIsolatedEvidenceState) -> None:
    """Publish a retryable observation without modifying the active stage journal."""

    print(
        json.dumps(
            {
                "event": "stage_isolated_evidence_stage_owner_active",
                "pipeline_id": state.pipeline_id,
                "stage": _COMPREHENSIVE_STAGE,
                "evidence_as_of": state.evidence_as_of.isoformat(),
                "stage_started_at": (
                    None
                    if state.stage_started_at is None
                    else state.stage_started_at.isoformat()
                ),
                "retry_deferred": True,
                "journal_modified": False,
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "construction_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _reap_comprehensive_descendants(
    values: Mapping[str, str],
    state: StageIsolatedEvidenceState,
) -> None:
    """Best-effort exact-identity cleanup before restart/failure reconciliation."""

    try:
        report = reap_stale_comprehensive_descendants(
            values,
            evidence_as_of=state.evidence_as_of,
            release=state.release,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        report = {
            "attempted": False,
            "runtime_journal_found": False,
            "running_nodes_recorded": 0,
            "identity_matched": 0,
            "reaped": 0,
            "identity_mismatch_or_gone": 0,
            "credential_safe": True,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
    print(
        json.dumps(
            {
                "event": "stage_isolated_comprehensive_descendants_reaped",
                "pipeline_id": state.pipeline_id,
                "evidence_as_of": state.evidence_as_of.isoformat(),
                **report,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _acquire_comprehensive_owner(
    state: StageIsolatedEvidenceState,
) -> StageOwnerLease | None:
    return try_acquire_stage_owner(
        state.path,
        pipeline_id=state.pipeline_id,
        stage=_COMPREHENSIVE_STAGE,
    )


def _durably_completed_stage_exit(
    latest: StageIsolatedEvidenceState | None,
    *,
    pipeline_id: str,
    stage: str,
    return_code: int,
) -> bool:
    """Accept only the wrapper's late internal error after exact durable completion."""

    return (
        return_code == _STAGE_WRAPPER_INTERNAL_ERROR_RETURN_CODE
        and latest is not None
        and latest.pipeline_id == pipeline_id
        and latest.state in {"running", "completed"}
        and stage in latest.completed_stages
    )


def _emit_stage_exit_reconciled(
    *,
    pipeline_id: str,
    stage: str,
    return_code: int,
) -> None:
    """Publish advisory reconciliation telemetry without creating a new failure path."""

    try:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_stage_exit_reconciled",
                    "pipeline_id": pipeline_id,
                    "stage": stage,
                    "child_return_code": return_code,
                    "durable_stage_completion": True,
                    "reconciliation_authority": "exact_stage_journal",
                    "decision_authority": False,
                    "candidate_authority": False,
                    "sizing_authority": False,
                    "construction_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    except Exception:
        pass


def _evidence_deadline(
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
) -> datetime:
    return state.evidence_as_of + timedelta(seconds=_max_age_seconds(values))


def _remaining_evidence_lifetime_seconds(
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
) -> float:
    return max(
        0.0,
        (_evidence_deadline(state, values) - datetime.now(timezone.utc)).total_seconds(),
    )


def _terminate_and_reap_stage_process(process: subprocess.Popen[bytes]) -> int:
    """Bound termination of one stale stage child without touching the parent process group."""

    process.terminate()
    try:
        return int(process.wait(timeout=_STAGE_TERMINATION_GRACE_SECONDS))
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            return int(process.wait(timeout=_STAGE_TERMINATION_GRACE_SECONDS))
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                "stage-isolated evidence child remained live after bounded kill"
            ) from error


def _wait_for_stage_process(
    process: subprocess.Popen[bytes],
    *,
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
) -> tuple[int, bool]:
    """Wait only through the evidence epoch and identify a supervisor-owned expiration."""

    remaining = _remaining_evidence_lifetime_seconds(state, values)
    if remaining > 0.0:
        try:
            return int(process.wait(timeout=remaining)), False
        except subprocess.TimeoutExpired:
            pass

    # The child may have exited while Popen.wait was raising TimeoutExpired. Re-check
    # liveness before sending any signal so real child terminal evidence always wins.
    return_code = process.poll()
    if return_code is not None:
        return int(return_code), False
    return _terminate_and_reap_stage_process(process), True


def _freshness_expired_detail(
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
    *,
    stage: str,
    child_return_code: int | None,
) -> str:
    return (
        "stage-isolated evidence epoch expired while stage child remained live; "
        f"stage={stage}; evidence_as_of={state.evidence_as_of.isoformat()}; "
        f"deadline={_evidence_deadline(state, values).isoformat()}; "
        f"max_age_seconds={_max_age_seconds(values):g}; "
        f"child_return_code={child_return_code}"
    )[:1600]


def _comprehensive_restart_freshness_detail(
    state: StageIsolatedEvidenceState,
    values: Mapping[str, str],
    *,
    remaining_seconds: float,
) -> str:
    return (
        "stage-isolated comprehensive discovery restart refused because the existing "
        "evidence epoch no longer preserves the downstream reserve; "
        f"stage=comprehensive_discovery; evidence_as_of={state.evidence_as_of.isoformat()}; "
        f"deadline={_evidence_deadline(state, values).isoformat()}; "
        f"max_age_seconds={_max_age_seconds(values):g}; "
        f"remaining_seconds={remaining_seconds:.3f}; "
        f"required_remaining_seconds={_COMPREHENSIVE_DISCOVERY_RESTART_RESERVE_SECONDS:g}"
    )[:1600]


def _validated_cache_ownership_report(raw: str | None) -> dict[str, object] | None:
    try:
        report = json.loads(str(raw or "").strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    if report.get("schema_version") != _PRECOMPREHENSIVE_CACHE_RECLAMATION_SCHEMA:
        return None
    expected = {
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }
    if any(report.get(key) is not value for key, value in expected.items()):
        return None
    return report


def _run_completed_evidence_cache_reclamation(
    values: Mapping[str, str],
    *,
    stage: str,
    event: str,
    code: str,
    capture_report: bool = False,
) -> None:
    """Bound and isolate advisory completed-evidence cache reclamation at one boundary.

    The coordinator remains descriptor-only. Cache ownership discovery and page-cache
    advice execute in a disposable child. Timeout, launch failure, malformed telemetry,
    and nonzero exit are advisory only: none can advance an evidence checkpoint or certify
    the subsequently spawned stage.
    """

    status = "completed"
    return_code: int | None = None
    error_type: str | None = None
    report: dict[str, object] | None = None
    try:
        completed = subprocess.run(
            (sys.executable, "-c", code),
            env=dict(values),
            cwd=str(Path(__file__).resolve().parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture_report else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=capture_report,
            timeout=_REFERENCE_CACHE_RECLAMATION_TIMEOUT_SECONDS,
            check=False,
            start_new_session=False,
        )
        return_code = int(completed.returncode)
        if return_code != 0:
            status = "failed"
            error_type = "CacheReclamationProcessError"
        elif capture_report:
            report = _validated_cache_ownership_report(completed.stdout)
            if report is None:
                status = "invalid_report"
                error_type = "CacheReclamationReportError"
    except subprocess.TimeoutExpired:
        status = "timed_out"
        error_type = "CacheReclamationTimeout"
    except OSError:
        status = "unavailable"
        error_type = "CacheReclamationLaunchError"

    payload: dict[str, object] = {
        "event": event,
        "stage": stage,
        "status": status,
        "return_code": return_code,
        "error_type": error_type,
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    if report is not None:
        payload["cache_ownership"] = report
        for key in (
            "candidate_file_count",
            "candidate_bytes",
            "selected_file_count",
            "selected_bytes",
            "released_file_count",
            "released_bytes",
            "scan_truncated",
            "manifest_truncated",
            "raw_current_reclaimed_kib",
            "inactive_file_reclaimed_kib",
        ):
            payload[key] = report.get(key)

    print(json.dumps(payload, sort_keys=True), flush=True)


def _run_reference_cache_reclamation(values: Mapping[str, str]) -> None:
    """Release bounded clean data-root cache before reference imports begin."""

    _run_completed_evidence_cache_reclamation(
        values,
        stage="reference",
        event=_REFERENCE_CACHE_RECLAMATION_EVENT,
        code=_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
        capture_report=True,
    )


def _run_comprehensive_discovery_cache_reclamation(values: Mapping[str, str]) -> None:
    """Release exact clean cache owners after US discovery and before all-market discovery."""

    _run_completed_evidence_cache_reclamation(
        values,
        stage="comprehensive_discovery",
        event=_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_EVENT,
        code=_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
        capture_report=True,
    )


def _run_failed_attempt_cache_reclamation(values: Mapping[str, str]) -> None:
    """Release clean cache owned by a durably archived failed evidence attempt."""

    _run_completed_evidence_cache_reclamation(
        values,
        stage="attempt_supersession",
        event=_FAILED_ATTEMPT_CACHE_RECLAMATION_EVENT,
        code=_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
        capture_report=True,
    )


def _archive_failed_attempt(state: StageIsolatedEvidenceState) -> Path | None:
    """Archive one validated failed latest journal without overwriting prior lineage."""

    try:
        failed_bytes = state.path.read_bytes()
    except FileNotFoundError:
        return None

    archive_dir = state.path.parent / "attempts"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{state.pipeline_id}.json"
    try:
        with archive_path.open("xb") as handle:
            handle.write(failed_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        try:
            archived_bytes = archive_path.read_bytes()
        except OSError as error:
            raise RuntimeError(
                "failed stage-isolated attempt archive is unreadable"
            ) from error
        if archived_bytes != failed_bytes:
            raise RuntimeError(
                "failed stage-isolated attempt archive identity collision"
            )

    # Treat the latest pointer as a compare-and-remove boundary. If another coordinator
    # already replaced it, leave that newer state untouched. Otherwise removing only the
    # exact failed bytes makes the next ensure call create a new attempt identity.
    try:
        current_bytes = state.path.read_bytes()
    except FileNotFoundError:
        return archive_path
    if current_bytes == failed_bytes:
        try:
            state.path.unlink()
        except FileNotFoundError:
            pass
    return archive_path


def _ensure_active_attempt(values: Mapping[str, str]) -> StageIsolatedEvidenceState:
    """Return a non-terminal attempt, superseding any persisted failed attempt exactly once."""

    existing = load_stage_isolated_evidence_state(values)
    if existing is None or existing.state != "failed":
        return ensure_stage_isolated_evidence_pipeline(values)

    previous = existing
    archive = _archive_failed_attempt(previous)
    _run_failed_attempt_cache_reclamation(values)
    replacement = ensure_stage_isolated_evidence_pipeline(values)
    if replacement.state == "failed":
        raise RuntimeError(
            "failed stage-isolated evidence attempt remained active after supersession"
        )
    if replacement.pipeline_id == previous.pipeline_id:
        raise RuntimeError(
            "stage-isolated evidence retry did not receive a fresh attempt identity"
        )

    print(
        json.dumps(
            {
                "event": "stage_isolated_evidence_attempt_superseded",
                "previous_pipeline_id": previous.pipeline_id,
                "pipeline_id": replacement.pipeline_id,
                "previous_failed_stage": previous.current_stage,
                "previous_completed_stages": list(previous.completed_stages),
                "previous_evidence_as_of": previous.evidence_as_of.isoformat(),
                "evidence_as_of": replacement.evidence_as_of.isoformat(),
                "archive": None if archive is None else str(archive),
                "canonical_stage_revalidation_required": True,
                "durable_evidence_reuse_permitted_only_by_stage_loaders": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return replacement


def _failed_comprehensive_owner_is_live(
    values: Mapping[str, str],
) -> bool:
    """Refuse failed-attempt supersession while its comprehensive owner still holds lease."""

    existing = load_stage_isolated_evidence_state(values)
    if (
        existing is None
        or existing.state != "failed"
        or existing.current_stage != _COMPREHENSIVE_STAGE
    ):
        return False
    lease = _acquire_comprehensive_owner(existing)
    if lease is None:
        _emit_active_stage_owner(existing)
        return True
    try:
        _reap_comprehensive_descendants(values, existing)
    finally:
        lease.release()
    return False


def run_pipeline(values: Mapping[str, str] | None = None) -> int:
    resolved = dict(os.environ if values is None else values)
    if str(resolved.get("RENDER") or "").strip().lower() == "true":
        # The stage coordinator already owns the single exclusive heavy-memory lane.
        # Comprehensive discovery keeps every required DAG node but executes lane workers
        # serially so nested interpreters cannot recreate a parallel memory spike.
        resolved[_DAG_WORKERS_ENV] = "1"
        os.environ[_DAG_WORKERS_ENV] = "1"

    if _failed_comprehensive_owner_is_live(resolved):
        return _STAGE_ACTIVE_OWNER_RETURN_CODE

    state = _ensure_active_attempt(resolved)
    if state.state == "completed" and state.generation_id:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_pipeline_current",
                    "pipeline_id": state.pipeline_id,
                    "generation_id": state.generation_id,
                    "evidence_as_of": state.evidence_as_of.isoformat(),
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 0

    script = Path(__file__).resolve().with_name("run_stage_isolated_evidence_stage.py")
    while True:
        state = load_stage_isolated_evidence_state(resolved)
        if state is None:
            raise RuntimeError("stage-isolated evidence state disappeared during execution")
        if state.state == "completed":
            if not state.generation_id:
                raise RuntimeError("completed stage-isolated pipeline has no generation id")
            print(
                json.dumps(
                    {
                        "event": "stage_isolated_evidence_pipeline_completed",
                        "pipeline_id": state.pipeline_id,
                        "generation_id": state.generation_id,
                        "evidence_as_of": state.evidence_as_of.isoformat(),
                        "completed_stages": list(state.completed_stages),
                        "all_required_stages_complete": state.completed_stages == _STAGES,
                        "paper_only": True,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            return 0

        stage = state.next_stage
        if stage is None:
            raise RuntimeError("stage-isolated evidence pipeline has no runnable next stage")

        stage_owner: StageOwnerLease | None = None
        if stage == _COMPREHENSIVE_STAGE:
            stage_owner = _acquire_comprehensive_owner(state)
            if stage_owner is None:
                _emit_active_stage_owner(state)
                return _STAGE_ACTIVE_OWNER_RETURN_CODE

        try:
            # A comprehensive child that already exited without completing its durable
            # stage may be retried by a later coordinator invocation. The owner lease proves
            # that no live coordinator still owns it. Reap any exact independently-sessioned
            # DAG descendants before deciding whether the unchanged epoch has enough time to
            # restart while preserving the existing 480-second downstream reserve.
            if stage == _COMPREHENSIVE_STAGE and state.current_stage == stage:
                _reap_comprehensive_descendants(resolved, state)
                remaining = _remaining_evidence_lifetime_seconds(state, resolved)
                if remaining <= _COMPREHENSIVE_DISCOVERY_RESTART_RESERVE_SECONDS:
                    detail = _comprehensive_restart_freshness_detail(
                        state,
                        resolved,
                        remaining_seconds=remaining,
                    )
                    latest = fail_evidence_stage(
                        resolved,
                        pipeline_id=state.pipeline_id,
                        stage=stage,
                        error_type=_STAGE_FRESHNESS_ERROR_TYPE,
                        error_detail=detail,
                    )
                    _safe_failure(
                        pipeline_id=state.pipeline_id,
                        stage=stage,
                        return_code=_STAGE_FRESHNESS_EXPIRED_RETURN_CODE,
                        error_type=latest.error_type,
                        error_detail=latest.error_detail,
                    )
                    return _STAGE_FRESHNESS_EXPIRED_RETURN_CODE

            # The parent must own the reference-stage handoff before it spawns the fresh child.
            # Otherwise a child that stalls during interpreter/import startup leaves the outer
            # prequalification watchdog observing only the previous public-live boundary. The
            # child still calls begin_evidence_stage itself; that repeat write is deliberately
            # harmless and immediately yields to the finer reference progress journal.
            if stage == "reference" and state.current_stage != "reference":
                state = begin_evidence_stage(
                    resolved,
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                )

            # Release clean pages at the heavyweight stage boundaries where production
            # telemetry has shown persistent raw cgroup pressure. Each boundary uses the same
            # bounded data-root scan and clean-page advice before the fresh stage interpreter is
            # spawned. Failed-attempt dirty-page flushing remains separately restricted to the
            # supersession boundary. Neither path changes an evidence or memory threshold.
            if stage == "reference":
                _run_reference_cache_reclamation(resolved)
            elif stage == "public_live":
                _run_completed_evidence_cache_reclamation(
                    resolved,
                    stage="public_live",
                    event="stage_isolated_public_live_cache_reclamation",
                    code=_COMPREHENSIVE_DISCOVERY_CACHE_RECLAMATION_CODE,
                    capture_report=True,
                )
            elif stage == _COMPREHENSIVE_STAGE:
                _run_comprehensive_discovery_cache_reclamation(resolved)

            print(
                json.dumps(
                    {
                        "event": "stage_isolated_evidence_stage_starting",
                        "pipeline_id": state.pipeline_id,
                        "stage": stage,
                        "evidence_as_of": state.evidence_as_of.isoformat(),
                        "completed_stages": list(state.completed_stages),
                        "fresh_interpreter": True,
                        "exclusive_heavy_memory_lane_inherited": True,
                        "exact_stage_owner_lease": stage == _COMPREHENSIVE_STAGE,
                        "paper_only": True,
                        "real_money_authorized": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            process = subprocess.Popen(
                (
                    sys.executable,
                    str(script),
                    stage,
                    "--pipeline-id",
                    state.pipeline_id,
                ),
                env=resolved,
                cwd=str(script.parent),
                # Keep every stage in the coordinator's process group. The outer reclaimable
                # memory governor can therefore terminate the complete ordinary stage tree.
                # Comprehensive DAG nodes may create their own sessions, and their exact
                # identities are persisted/reaped separately by the owner contract above.
                start_new_session=False,
            )
            return_code, freshness_expired = _wait_for_stage_process(
                process,
                state=state,
                values=resolved,
            )
            latest = load_stage_isolated_evidence_state(resolved)

            # If comprehensive did not finish cleanly, its stage process may have died before
            # its DAG supervisor could clear separately-sessioned node groups. Reap only exact
            # persisted PID/start-time identities while this coordinator still holds the owner
            # lease, so no later attempt can overlap them.
            if stage == _COMPREHENSIVE_STAGE and (freshness_expired or return_code != 0):
                _reap_comprehensive_descendants(resolved, state)

            if freshness_expired:
                # Reload after the stale child and descendants have been reaped. A child can
                # commit terminal truth between timeout and liveness re-check; never overwrite
                # that newer durable evidence with a supervisor timeout classification.
                latest = load_stage_isolated_evidence_state(resolved)
                if latest is not None and latest.pipeline_id == state.pipeline_id:
                    if stage in latest.completed_stages:
                        continue
                    if latest.state == "failed" and latest.current_stage == stage:
                        _safe_failure(
                            pipeline_id=state.pipeline_id,
                            stage=stage,
                            return_code=(return_code if return_code != 0 else 2),
                            error_type=latest.error_type,
                            error_detail=latest.error_detail,
                        )
                        return return_code if return_code != 0 else 2
                if latest is None or latest.pipeline_id != state.pipeline_id:
                    _safe_failure(
                        pipeline_id=state.pipeline_id,
                        stage=stage,
                        return_code=2,
                        error_type="StageCheckpointError",
                        error_detail=(
                            "stage evidence identity changed while enforcing freshness deadline"
                        ),
                    )
                    return 2

                detail = _freshness_expired_detail(
                    state,
                    resolved,
                    stage=stage,
                    child_return_code=return_code,
                )
                latest = fail_evidence_stage(
                    resolved,
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                    error_type=_STAGE_FRESHNESS_ERROR_TYPE,
                    error_detail=detail,
                )
                _safe_failure(
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                    return_code=_STAGE_FRESHNESS_EXPIRED_RETURN_CODE,
                    error_type=latest.error_type,
                    error_detail=latest.error_detail,
                )
                return _STAGE_FRESHNESS_EXPIRED_RETURN_CODE

            if return_code != 0:
                # Only the wrapper's known generic internal-error exit may be reconciled after
                # exact durable completion. All other positive exits, signals, identity changes,
                # failed journals, and every pre-completion exit remain fail-closed.
                if _durably_completed_stage_exit(
                    latest,
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                    return_code=return_code,
                ):
                    _emit_stage_exit_reconciled(
                        pipeline_id=state.pipeline_id,
                        stage=stage,
                        return_code=return_code,
                    )
                    continue
                _safe_failure(
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                    return_code=return_code,
                    error_type=None if latest is None else latest.error_type,
                    error_detail=None if latest is None else latest.error_detail,
                )
                return return_code
            if (
                latest is None
                or latest.pipeline_id != state.pipeline_id
                or stage not in latest.completed_stages
            ):
                _safe_failure(
                    pipeline_id=state.pipeline_id,
                    stage=stage,
                    return_code=2,
                    error_type="StageCheckpointError",
                    error_detail="stage process exited successfully without durable stage completion",
                )
                return 2
        finally:
            if stage_owner is not None:
                stage_owner.release()


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        return run_pipeline()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": _FAILURE_EVENT,
                    "error_type": type(error).__name__,
                    "failure_stage": "stage_isolated_evidence_pipeline",
                    "error_detail": str(error)[:1600],
                    "credential_safe": True,
                    "decision_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
