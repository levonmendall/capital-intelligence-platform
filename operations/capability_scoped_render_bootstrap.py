"""Install capability evidence as an additional all-market Render requirement.

Release diagnostics require both a complete immutable all-market evidence generation and a
fresh immutable capability-operating snapshot before the CIO request is created. Capability
scope constrains which instruments may be operated on; it never narrows discovery,
certification, or market-coverage requirements.

Both evidence owners remain resource bounded and share the exclusive heavy-memory lane. No
investment rule, threshold, construction, paper-execution, or real-money authority changes.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Mapping, MutableMapping

from operations.capability_operating_evidence import (
    CapabilityOperatingEvidenceError,
    load_capability_operating_evidence,
)
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic
from operations.release_evidence_prequalification import (
    load_release_evidence_prequalification,
    write_release_evidence_prequalification,
)

_INSTALLED_ATTR = "_capability_scoped_operating_bootstrap_installed"
_DEFAULT_OPERATING_EVIDENCE_SUBPROCESS_GRACE_SECONDS = 30.0
_SAFE_FAILURE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_SAFE_CHILD_FAILURE_EVENTS = frozenset(
    {
        "capability_operating_evidence_failed",
        "capability_operating_evidence_coordinator_failed",
        "heavy_memory_lane_busy",
        "isolated_worker_pass_timed_out",
        "isolated_worker_pass_memory_limited",
        "bounded_worker_failed",
    }
)


def _enabled(values: Mapping[str, str]) -> bool:
    raw = values.get("CAPITAL_INTELLIGENCE_CAPABILITY_SCOPED_OPERATION")
    if raw is not None and str(raw).strip():
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _parse_aware(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_failure_token(value: object) -> str | None:
    candidate = str(value or "").strip()
    return candidate if _SAFE_FAILURE_TOKEN.fullmatch(candidate) else None


def _operating_prequalification_status(
    values: Mapping[str, str],
) -> tuple[str, datetime, str | None] | None:
    """Return the exact broad-evidence generation coordinates already made durable."""

    status = load_release_evidence_prequalification(values)
    if not isinstance(status, Mapping):
        return None
    if str(status.get("release") or "") != _release(values):
        return None
    prequalification_id = str(status.get("prequalification_id") or "").strip()
    started_at = _parse_aware(status.get("started_at"))
    generation_id = str(status.get("generation_id") or "").strip() or None
    if not prequalification_id or started_at is None or generation_id is None:
        return None
    return prequalification_id, started_at, generation_id


def _publish_operating_prequalification(
    memory_safe,
    values: MutableMapping[str, str],
    *,
    state: str,
    detail: str,
    attempt: int,
    maximum_attempts: int,
    timed_out: bool = False,
    return_code: int | None = None,
    failure_reason: str | None = None,
) -> None:
    """Keep public release state truthful while the additional capability gate runs."""

    coordinates = _operating_prequalification_status(values)
    if coordinates is None:
        raise RuntimeError(
            "exact-release all-market generation coordinates are unavailable for capability handoff"
        )
    prequalification_id, started_at, generation_id = coordinates
    stage = (
        "evidence_prequalification_failed"
        if state == "failed"
        else "evidence_generation_ready"
        if state == "completed"
        else "evidence_refresh"
    )
    metrics = {
        "attempt": attempt,
        "maximum_attempts": maximum_attempts,
        "capability_operating_evidence_required": 1,
        "capability_operating_evidence_timeout": int(timed_out),
        "complete_all_market_coverage_required": 1,
    }
    if return_code is not None:
        normalized_return_code = int(return_code)
        metrics["capability_operating_evidence_return_code"] = abs(
            normalized_return_code
        )
        metrics["capability_operating_evidence_return_code_negative"] = int(
            normalized_return_code < 0
        )
    normalized_reason = _safe_failure_token(failure_reason)
    if normalized_reason is not None:
        metrics["capability_operating_evidence_resource_exhausted"] = int(
            normalized_reason == "resource_exhausted"
        )
        metrics["capability_operating_evidence_resource_busy"] = int(
            normalized_reason == "resource_busy"
        )
        metrics["capability_operating_evidence_internal_error"] = int(
            normalized_reason == "internal_error"
        )

    write_release_evidence_prequalification(
        values,
        state=state,
        stage=stage,
        prequalification_id=prequalification_id,
        started_at=started_at,
        detail=detail,
        generation_id=generation_id,
        metrics=metrics,
    )
    memory_safe.render_bootstrap._publish_release_diagnostic_audit(values)


def _operating_subprocess_timeout_seconds(memory_safe, values: Mapping[str, str]) -> float:
    pass_timeout = memory_safe._nonnegative_seconds(
        values,
        "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS",
        480.0,
    )
    configured = str(
        values.get("CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS")
        or ""
    ).strip()
    if configured:
        try:
            timeout = float(configured)
        except ValueError as error:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS must be numeric"
            ) from error
        if timeout <= 0:
            raise ValueError(
                "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS must be positive"
            )
        return timeout
    return max(1.0, pass_timeout + _DEFAULT_OPERATING_EVIDENCE_SUBPROCESS_GRACE_SECONDS)


def _safe_child_failure_identity(output: str) -> tuple[str | None, str | None]:
    """Extract only allowlisted non-authoritative failure identity from child stdout."""

    for raw_line in reversed(str(output or "").splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        event = _safe_failure_token(payload.get("event"))
        if event not in _SAFE_CHILD_FAILURE_EVENTS:
            continue
        if payload.get("paper_only") is not True:
            continue
        if payload.get("real_money_authorized") is not False:
            continue
        if (
            event == "capability_operating_evidence_failed"
            and payload.get("credential_safe") is not True
        ):
            continue
        return event, _safe_failure_token(payload.get("error_type"))
    return None, None


def _classify_capability_attempt_failure(
    *,
    return_code: int,
    output: str,
    timed_out: bool,
    explicit_error_type: str | None = None,
) -> tuple[str, str, str, str]:
    """Classify the exact bounded attempt without persisting raw child/provider output."""

    event, child_error_type = _safe_child_failure_identity(output)
    explicit = _safe_failure_token(explicit_error_type)
    observed_error_type = explicit or child_error_type

    if timed_out or return_code == 124 or event == "isolated_worker_pass_timed_out":
        return (
            "deadline_exceeded",
            "CapabilityOperatingEvidenceTimeout",
            "capability_operating_evidence_timeout",
            event or "outer_subprocess_timeout",
        )
    if return_code == 125 or event == "isolated_worker_pass_memory_limited":
        return (
            "resource_exhausted",
            "CapabilityOperatingEvidenceMemoryLimited",
            "capability_operating_evidence_memory_limited",
            event or "memory_limited",
        )
    if return_code == 126 or event == "heavy_memory_lane_busy":
        return (
            "resource_busy",
            "CapabilityOperatingEvidenceMemoryLaneBusy",
            "heavy_memory_lane_busy",
            event or "memory_lane_busy",
        )

    return (
        "internal_error",
        observed_error_type or "CapabilityOperatingEvidenceUnavailable",
        "capability_operating_evidence_unavailable",
        event or "unclassified_failure",
    )


def _safe_attempt_detail(
    *,
    prefix: str,
    error_type: str,
    detail_token: str,
) -> str:
    """Encode only typed safe tokens in the generic child-attribution grammar."""

    safe_error = _safe_failure_token(error_type) or "CapabilityOperatingEvidenceUnavailable"
    safe_detail = _safe_failure_token(detail_token) or "capability_operating_evidence_unavailable"
    return (
        f"{prefix}; child_stage=capability_operating_gate; "
        f"child_error_type={safe_error}; child_detail={safe_detail}"
    )


def prequalify_capability_operating_evidence(
    memory_safe,
    diagnostic_values: MutableMapping[str, str],
) -> bool:
    """Require one fresh operating snapshot without allowing an unbounded child.

    The comprehensive release prequalifier owns the release-wide generation/status. This
    function owns only the orthogonal operating-capability requirement. Its child process
    has an outer wall-clock bound so a wedged provider or child cannot leave a release
    indefinitely parked at ``evidence_generation_ready`` before the CIO request exists.
    """

    started_at = datetime.now(timezone.utc)
    maximum_attempts = memory_safe._positive_int(
        diagnostic_values,
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS",
        3,
    )
    retry_seconds = memory_safe._nonnegative_seconds(
        diagnostic_values,
        "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_RETRY_SECONDS",
        15.0,
    )
    subprocess_timeout = _operating_subprocess_timeout_seconds(memory_safe, diagnostic_values)
    command = (
        sys.executable,
        "run_bounded_capability_operating_evidence.py",
        "--once",
    )

    for attempt in range(1, maximum_attempts + 1):
        _publish_operating_prequalification(
            memory_safe,
            diagnostic_values,
            state="in_progress",
            detail=(
                "qualifying fresh capability-operating evidence before current-release "
                f"CIO activation; attempt {attempt} of {maximum_attempts}"
            ),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
        )
        memory_safe.render_bootstrap._log(
            "release_operating_evidence_prequalification_starting",
            command=list(command),
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            subprocess_timeout_seconds=subprocess_timeout,
            diagnostic_request_created=False,
            complete_all_market_coverage_required=True,
            paper_only=True,
            real_money_authorized=False,
        )

        timed_out = False
        explicit_error_type: str | None = None
        try:
            completed = subprocess.run(
                command,
                env=dict(diagnostic_values),
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=subprocess_timeout,
            )
            return_code = int(completed.returncode)
            output = str(completed.stdout or "")[-1600:]
        except subprocess.TimeoutExpired as error:
            timed_out = True
            return_code = 124
            output = error.stdout[-1600:] if isinstance(error.stdout, str) else ""
        except OSError as error:
            return_code = 2
            output = ""
            explicit_error_type = type(error).__name__

        evidence = None
        if return_code == 0:
            try:
                evidence = load_capability_operating_evidence(
                    cutoff=datetime.now(timezone.utc),
                    values=diagnostic_values,
                )
            except CapabilityOperatingEvidenceError as error:
                explicit_error_type = type(error).__name__

        if return_code == 0 and evidence is not None:
            _publish_operating_prequalification(
                memory_safe,
                diagnostic_values,
                state="completed",
                detail=(
                    "immutable exact-release comprehensive all-market generation and fresh "
                    "capability-operating evidence are ready for CIO activation"
                ),
                attempt=attempt,
                maximum_attempts=maximum_attempts,
            )
            diagnostic_values[
                "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"
            ] = evidence.snapshot_id
            memory_safe.render_bootstrap._log(
                "release_operating_evidence_prequalification_finished",
                return_code=0,
                release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                snapshot_id=evidence.snapshot_id,
                instrument_count=len(evidence.universe.instruments),
                holding_only_count=len(evidence.holding_only_symbols),
                comprehensive_all_market_generation_preserved=True,
                complete_all_market_coverage_required=True,
                diagnostic_request_created=False,
                paper_only=True,
                real_money_authorized=False,
                elapsed_seconds=max(
                    0.0,
                    (datetime.now(timezone.utc) - started_at).total_seconds(),
                ),
            )
            return True

        failure_reason, failure_error_type, detail_token, failure_event = (
            _classify_capability_attempt_failure(
                return_code=return_code,
                output=output,
                timed_out=timed_out,
                explicit_error_type=explicit_error_type,
            )
        )
        memory_safe.render_bootstrap._log(
            "release_operating_evidence_prequalification_retrying"
            if attempt < maximum_attempts
            else "release_operating_evidence_prequalification_failed",
            return_code=return_code,
            failure_reason=failure_reason,
            failure_error_type=failure_error_type,
            failure_event=failure_event,
            release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            complete_all_market_coverage_required=True,
            diagnostic_request_created=False,
            paper_only=True,
            real_money_authorized=False,
        )
        if attempt < maximum_attempts:
            _publish_operating_prequalification(
                memory_safe,
                diagnostic_values,
                state="in_progress",
                detail=_safe_attempt_detail(
                    prefix="capability-operating evidence did not qualify; retry remains bounded",
                    error_type=failure_error_type,
                    detail_token=detail_token,
                ),
                attempt=attempt,
                maximum_attempts=maximum_attempts,
                timed_out=timed_out,
                return_code=return_code,
                failure_reason=failure_reason,
            )
            if retry_seconds:
                time.sleep(retry_seconds)
            continue

        _publish_operating_prequalification(
            memory_safe,
            diagnostic_values,
            state="failed",
            detail=_safe_attempt_detail(
                prefix="capability-operating evidence prequalification failed closed",
                error_type=failure_error_type,
                detail_token=detail_token,
            ),
            attempt=attempt,
            maximum_attempts=maximum_attempts,
            timed_out=timed_out,
            return_code=return_code,
            failure_reason=failure_reason,
        )
        return False

    return False


def _verify_current_release_handoff(values: MutableMapping[str, str]) -> bool:
    """Require the primer to leave durable coordination owned by this exact release."""

    current = latest_manual_cio_diagnostic(values=values)
    if current is None:
        return False
    expected_requester = f"render-release:{_release(values)}"
    return current.requested_by == expected_requester and current.state in {
        "pending",
        "in_progress",
        "completed",
        "failed",
    }


def install(memory_safe) -> None:
    """Require all-market and capability evidence while keeping concerns independent."""

    if getattr(memory_safe, _INSTALLED_ATTR, False):
        return

    original_managed_processes = memory_safe.memory_safe_managed_processes
    original_prequalify = memory_safe._prequalify_release_evidence
    original_start = memory_safe._start_release_diagnostic_after_prequalification

    os.environ.setdefault("CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_INTERVAL_SECONDS", "300")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS", "480")
    os.environ.setdefault("CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_MAX_AGE_SECONDS", "900")

    def prequalify_required_evidence(
        diagnostic_values: MutableMapping[str, str],
    ) -> bool:
        if not _enabled(diagnostic_values):
            return original_prequalify(diagnostic_values)

        # The broad release generation is always first and remains the canonical
        # certification input. Operating evidence is an additional fail-closed gate and
        # now remains visibly prequalifying until that additional gate is actually done.
        if not original_prequalify(diagnostic_values):
            return False
        return prequalify_capability_operating_evidence(memory_safe, diagnostic_values)

    def start_release_diagnostic(values: MutableMapping[str, str]):
        if not _enabled(values):
            return original_start(values)
        if not memory_safe.render_bootstrap._enabled(
            values,
            "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_ON_RELEASE",
            default=False,
        ):
            return None

        def qualify_then_run() -> None:
            diagnostic_values = memory_safe.render_bootstrap._release_diagnostic_environment(
                values
            )
            if not prequalify_required_evidence(diagnostic_values):
                return

            # Only after every required evidence owner is complete do we publish
            # evidence_generation_ready and establish the current-release CIO request.
            memory_safe.render_bootstrap.prime_release_diagnostic_request(values)
            if not _verify_current_release_handoff(values):
                # One idempotent self-recovery is permitted. The primer preserves a live
                # current owner and never creates investment authority by itself.
                memory_safe.render_bootstrap.prime_release_diagnostic_request(values)
            if not _verify_current_release_handoff(values):
                coordinates = _operating_prequalification_status(diagnostic_values)
                if coordinates is not None:
                    prequalification_id, started_at, generation_id = coordinates
                    write_release_evidence_prequalification(
                        diagnostic_values,
                        state="failed",
                        stage="evidence_prequalification_failed",
                        prequalification_id=prequalification_id,
                        started_at=started_at,
                        generation_id=generation_id,
                        detail="production_context_activation_not_started",
                        metrics={
                            "capability_operating_evidence_required": 1,
                            "complete_all_market_coverage_required": 1,
                            "current_release_handoff_missing": 1,
                        },
                    )
                    memory_safe.render_bootstrap._publish_release_diagnostic_audit(
                        diagnostic_values
                    )
                memory_safe.render_bootstrap._log(
                    "release_current_diagnostic_handoff_failed",
                    release=_release(values),
                    failure_reason="production_context_activation_not_started",
                    self_recovery_attempted=True,
                    decision_authority=False,
                    execution_authority=False,
                    paper_only=True,
                    real_money_authorized=False,
                )
                return

            memory_safe.render_bootstrap._run_release_diagnostic_after_readiness(
                values,
                not_before=datetime.now(timezone.utc),
            )

        thread = threading.Thread(
            name="release-all-market-evidence-then-cio-diagnostic",
            target=qualify_then_run,
            daemon=True,
        )
        thread.start()
        memory_safe.render_bootstrap._log(
            "release_required_evidence_prequalification_armed",
            release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            diagnostic_request_created=False,
            complete_all_market_coverage_required=True,
            capability_operating_evidence_required=True,
            paper_only=True,
            real_money_authorized=False,
        )
        return thread

    def managed_processes(*, port: int, python_executable: str | None = None):
        specs = list(
            original_managed_processes(
                port=port,
                python_executable=python_executable,
            )
        )
        if not _enabled(os.environ):
            return tuple(specs)
        if any(spec.name == "capability-operating-evidence" for spec in specs):
            return tuple(specs)
        python = python_executable or sys.executable
        specs.append(
            memory_safe.render_supervisor.ManagedProcess(
                name="capability-operating-evidence",
                command=(
                    python,
                    "run_bounded_capability_operating_evidence.py",
                    "--loop",
                ),
                critical=False,
                restart_delay_seconds=30,
            )
        )
        return tuple(specs)

    memory_safe._prequalify_release_evidence = prequalify_required_evidence
    memory_safe._start_release_diagnostic_after_prequalification = start_release_diagnostic
    memory_safe.memory_safe_managed_processes = managed_processes
    setattr(memory_safe, _INSTALLED_ATTR, True)


__all__ = [
    "_verify_current_release_handoff",
    "install",
    "prequalify_capability_operating_evidence",
]
