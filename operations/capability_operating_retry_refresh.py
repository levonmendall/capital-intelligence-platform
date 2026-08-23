"""Refresh stale capability evidence before each release-diagnostic attempt.

A release diagnostic may run long enough that operating evidence qualified at startup
becomes stale before a retry begins. This coordinator revalidates only that orthogonal
operating snapshot immediately before each CIO watchdog process. Comprehensive all-market
evidence remains a separate, already-required release gate and is never downgraded or
replaced during this refresh.

This module does not collect provider data itself and grants no investment, specialist,
construction, execution, or real-money authority. Failure to refresh or revalidate remains
fail-closed.
"""

from __future__ import annotations

from collections.abc import Callable, MutableMapping, Sequence
from datetime import datetime, timedelta, timezone

from operations.capability_scoped_release_diagnostic import (
    capability_scoped_operation_enabled,
    load_capability_operating_reference_manifest,
)
from operations.manual_cio_diagnostic import (
    claim_manual_cio_diagnostic,
    finish_manual_cio_diagnostic,
    latest_manual_cio_diagnostic,
)

_INSTALLED_ATTR = "_capability_operating_retry_refresh_installed"
_EVIDENCE_NOT_READY_RETURN_CODE = 69
_GOVERNED_DEADLINE_RETURN_CODE = 124
_DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS = 1800.0
_DEADLINE_SAFETY_SECONDS = 1.0
_OPERATING_ATTEMPTS_ENV = "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_ATTEMPTS"
_OPERATING_RETRY_ENV = "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_RETRY_SECONDS"
_OPERATING_SUBPROCESS_TIMEOUT_ENV = (
    "CAPITAL_INTELLIGENCE_RELEASE_OPERATING_EVIDENCE_SUBPROCESS_TIMEOUT_SECONDS"
)
_OPERATING_PASS_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_OPERATING_EVIDENCE_PASS_TIMEOUT_SECONDS"
_DIAGNOSTIC_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_MANUAL_CIO_DIAGNOSTIC_TIMEOUT_SECONDS"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _release(values: MutableMapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _diagnostic_timeout_seconds(values: MutableMapping[str, str]) -> float:
    raw = str(values.get(_DIAGNOSTIC_TIMEOUT_ENV) or "").strip()
    if not raw:
        return _DEFAULT_DIAGNOSTIC_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError(f"{_DIAGNOSTIC_TIMEOUT_ENV} must be numeric") from error
    if timeout <= 0:
        raise ValueError(f"{_DIAGNOSTIC_TIMEOUT_ENV} must be positive")
    return timeout


def _current_pending_request(values: MutableMapping[str, str]):
    request = latest_manual_cio_diagnostic(values=values)
    if request is None or request.state != "pending":
        return None
    if request.requested_by != f"render-release:{_release(values)}":
        return None
    return request


def _remaining_diagnostic_seconds(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
) -> float | None:
    request = _current_pending_request(values)
    if request is None:
        return None
    current = (now or _utc_now()).astimezone(timezone.utc)
    deadline = request.requested_at.astimezone(timezone.utc) + timedelta(
        seconds=_diagnostic_timeout_seconds(values)
    )
    return max(0.0, (deadline - current).total_seconds())


def _fail_pending_at_governed_deadline(
    values: MutableMapping[str, str],
    *,
    now: datetime | None = None,
) -> bool:
    request = _current_pending_request(values)
    if request is None:
        return False
    completed_at = (now or _utc_now()).astimezone(timezone.utc)
    claimed = claim_manual_cio_diagnostic(now=completed_at, values=values)
    if claimed is None or claimed.request_id != request.request_id:
        return False
    finish_manual_cio_diagnostic(
        claimed,
        succeeded=False,
        cycle_key=claimed.cycle_key,
        snapshot_identifier=claimed.snapshot_identifier,
        detail=(
            "Manual CIO diagnostic exceeded its governed operational deadline before "
            "bounded CIO child startup and was terminated fail-closed; "
            "diagnostic_child_started=false"
        ),
        now=completed_at,
        values=values,
    )
    return True


def _positive_int(values: MutableMapping[str, str], name: str, default: int) -> int:
    raw = str(values.get(name) or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _nonnegative_seconds(
    values: MutableMapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = str(values.get(name) or "").strip()
    if not raw:
        return default
    value = float(raw)
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _operating_subprocess_timeout_seconds(values: MutableMapping[str, str]) -> float:
    configured = str(values.get(_OPERATING_SUBPROCESS_TIMEOUT_ENV) or "").strip()
    if configured:
        timeout = float(configured)
        if timeout <= 0:
            raise ValueError(f"{_OPERATING_SUBPROCESS_TIMEOUT_ENV} must be positive")
        return timeout
    pass_timeout = _nonnegative_seconds(values, _OPERATING_PASS_TIMEOUT_ENV, 480.0)
    return max(1.0, pass_timeout + 30.0)


def _bounded_operating_refresh_values(
    values: MutableMapping[str, str],
    *,
    remaining_seconds: float,
) -> dict[str, str]:
    """Cap the existing retry batch so its worst-case wall time fits the attempt."""

    bounded = dict(values)
    maximum_attempts = _positive_int(bounded, _OPERATING_ATTEMPTS_ENV, 3)
    configured_retry = _nonnegative_seconds(bounded, _OPERATING_RETRY_ENV, 15.0)
    configured_timeout = _operating_subprocess_timeout_seconds(bounded)
    usable = max(0.0, float(remaining_seconds) - _DEADLINE_SAFETY_SECONDS)
    if usable <= 0:
        return bounded

    configured_retry_total = configured_retry * max(0, maximum_attempts - 1)
    if configured_retry_total >= usable:
        effective_retry = 0.0
    else:
        effective_retry = configured_retry
    attempt_budget = max(
        0.001,
        (usable - effective_retry * max(0, maximum_attempts - 1)) / maximum_attempts,
    )
    effective_timeout = min(configured_timeout, attempt_budget)
    bounded[_OPERATING_RETRY_ENV] = f"{effective_retry:.6f}"
    bounded[_OPERATING_SUBPROCESS_TIMEOUT_ENV] = f"{effective_timeout:.6f}"
    return bounded


def _command_with_remaining_timeout(
    command: Sequence[str],
    *,
    remaining_seconds: float | None,
) -> tuple[str, ...]:
    resolved = tuple(command)
    if remaining_seconds is None or "--timeout-seconds" in resolved:
        return resolved
    if not any(item.endswith("run_bounded_manual_cio_diagnostic.py") for item in resolved):
        return resolved
    return (*resolved, "--timeout-seconds", f"{max(0.001, remaining_seconds):.6f}")


def _ensure_fresh_operating_evidence(
    values: MutableMapping[str, str],
    *,
    prequalify: Callable[[MutableMapping[str, str]], bool],
) -> bool:
    """Return true only when fresh immutable evidence is ready for this exact attempt."""

    try:
        load_capability_operating_reference_manifest(values)
        return True
    except RuntimeError:
        pass

    if not prequalify(values):
        return False

    try:
        load_capability_operating_reference_manifest(values)
    except RuntimeError:
        return False
    return True


def install(memory_safe) -> None:
    """Patch the live-audit runner so retries cannot consume stale operating evidence."""

    render_bootstrap = memory_safe.render_bootstrap
    if getattr(render_bootstrap, _INSTALLED_ATTR, False):
        return

    from operations.capability_scoped_render_bootstrap import (
        prequalify_capability_operating_evidence,
    )

    original_run_with_audit = render_bootstrap._run_release_diagnostic_with_live_audit
    original_retryable = getattr(render_bootstrap, "_release_diagnostic_retryable", None)

    # Production uses the dedicated operating-evidence owner. Lightweight integration
    # harnesses that intentionally expose only the legacy prequalification seam keep a
    # compatible injection point without changing production behavior.
    injected_prequalify = getattr(
        memory_safe,
        "_prequalify_capability_operating_evidence",
        None,
    )
    legacy_prequalify = getattr(memory_safe, "_prequalify_release_evidence", None)
    production_helpers_available = all(
        hasattr(memory_safe, name) for name in ("_positive_int", "_nonnegative_seconds")
    )

    def prequalify(values: MutableMapping[str, str]) -> bool:
        if callable(injected_prequalify):
            return bool(injected_prequalify(values))
        if production_helpers_available:
            remaining = _remaining_diagnostic_seconds(values)
            if remaining is None:
                return prequalify_capability_operating_evidence(memory_safe, values)
            if remaining <= _DEADLINE_SAFETY_SECONDS:
                return False
            bounded_values = _bounded_operating_refresh_values(
                values,
                remaining_seconds=remaining,
            )
            result = prequalify_capability_operating_evidence(
                memory_safe,
                bounded_values,
            )
            snapshot_id = bounded_values.get(
                "CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"
            )
            if snapshot_id:
                values["CAPITAL_INTELLIGENCE_CIO_PAPER_EVIDENCE_SNAPSHOT_ID"] = snapshot_id
            return bool(result)
        if callable(legacy_prequalify):
            return bool(legacy_prequalify(values))
        return False

    def terminalize_deadline(values: MutableMapping[str, str]) -> int:
        finalized = _fail_pending_at_governed_deadline(values)
        render_bootstrap._log(
            "manual_cio_release_governed_deadline_exhausted",
            release=values.get("CAPITAL_INTELLIGENCE_RELEASE"),
            return_code=_GOVERNED_DEADLINE_RETURN_CODE,
            pending_request_finalized=finalized,
            diagnostic_child_started=False,
            retries_suppressed=True,
            complete_all_market_coverage_required=True,
            paper_only=True,
            real_money_authorized=False,
        )
        return _GOVERNED_DEADLINE_RETURN_CODE

    def run_with_live_audit(
        command: Sequence[str],
        *,
        diagnostic_values: MutableMapping[str, str],
        refresh_seconds: float = 15.0,
    ) -> int:
        remaining = _remaining_diagnostic_seconds(diagnostic_values)
        if remaining is not None and remaining <= _DEADLINE_SAFETY_SECONDS:
            return terminalize_deadline(diagnostic_values)

        if capability_scoped_operation_enabled(diagnostic_values):
            if not _ensure_fresh_operating_evidence(
                diagnostic_values,
                prequalify=prequalify,
            ):
                remaining = _remaining_diagnostic_seconds(diagnostic_values)
                if remaining is not None and remaining <= _DEADLINE_SAFETY_SECONDS:
                    return terminalize_deadline(diagnostic_values)
                render_bootstrap._log(
                    "manual_cio_release_operating_evidence_not_ready",
                    release=diagnostic_values.get("CAPITAL_INTELLIGENCE_RELEASE"),
                    return_code=_EVIDENCE_NOT_READY_RETURN_CODE,
                    diagnostic_child_started=False,
                    evidence_refresh_attempted=True,
                    comprehensive_all_market_gate_required=True,
                    paper_only=True,
                    real_money_authorized=False,
                )
                return _EVIDENCE_NOT_READY_RETURN_CODE

        remaining = _remaining_diagnostic_seconds(diagnostic_values)
        if remaining is not None and remaining <= _DEADLINE_SAFETY_SECONDS:
            return terminalize_deadline(diagnostic_values)
        bounded_command = _command_with_remaining_timeout(
            command,
            remaining_seconds=remaining,
        )
        return original_run_with_audit(
            bounded_command,
            diagnostic_values=diagnostic_values,
            refresh_seconds=refresh_seconds,
        )

    if callable(original_retryable):
        def retryable(return_code: int) -> bool:
            if int(return_code) == _GOVERNED_DEADLINE_RETURN_CODE:
                return False
            return bool(original_retryable(return_code))

        render_bootstrap._release_diagnostic_retryable = retryable

    render_bootstrap._run_release_diagnostic_with_live_audit = run_with_live_audit
    setattr(render_bootstrap, _INSTALLED_ATTR, True)


__all__ = ["install"]
