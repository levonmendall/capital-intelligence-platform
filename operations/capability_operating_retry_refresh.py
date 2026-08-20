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

from operations.capability_scoped_release_diagnostic import (
    capability_scoped_operation_enabled,
    load_capability_operating_reference_manifest,
)

_INSTALLED_ATTR = "_capability_operating_retry_refresh_installed"
_EVIDENCE_NOT_READY_RETURN_CODE = 69


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
            return prequalify_capability_operating_evidence(memory_safe, values)
        if callable(legacy_prequalify):
            return bool(legacy_prequalify(values))
        return False

    def run_with_live_audit(
        command: Sequence[str],
        *,
        diagnostic_values: MutableMapping[str, str],
        refresh_seconds: float = 15.0,
    ) -> int:
        if capability_scoped_operation_enabled(diagnostic_values):
            if not _ensure_fresh_operating_evidence(
                diagnostic_values,
                prequalify=prequalify,
            ):
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

        return original_run_with_audit(
            command,
            diagnostic_values=diagnostic_values,
            refresh_seconds=refresh_seconds,
        )

    render_bootstrap._run_release_diagnostic_with_live_audit = run_with_live_audit
    setattr(render_bootstrap, _INSTALLED_ATTR, True)


__all__ = ["install"]
