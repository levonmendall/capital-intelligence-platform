"""Runtime contract for authoritative comprehensive-discovery orchestration.

PR #687 introduced explicit certification-DAG and provider-free-finalizer progress
boundaries. The manual CIO diagnostic intentionally rejects unknown stages and metrics,
so those operational names must be registered before the authoritative scheduler emits
them. This module also preserves a credential-safe finalizer boundary when an exception
escapes the deterministic second phase.

This is operational observability only. It cannot relax market coverage, evidence
freshness/completeness, screening, CIO authority, construction, execution, or paper-only
controls.
"""

from __future__ import annotations

from typing import Any

from operations import manual_cio_diagnostic as _diagnostic


_EXACT_PROGRESS_STAGES = frozenset(
    {
        "certification_dag_catalog_dependency",
        "certification_dag_catalog_dependency_complete",
        "certification_dag_provider_factor_dependency",
        "certification_dag_provider_factor_dependency_complete",
        "certification_dag_compatibility_rebind",
        "certification_dag_ready",
        "comprehensive_discovery_provider_free_finalizer",
        "comprehensive_discovery_provider_free_finalizer_complete",
    }
)
_LANE_PROGRESS_STAGES = frozenset(
    {
        "certification_dag",
        "certification_dag_complete",
    }
)
_PROGRESS_METRICS = frozenset(
    {
        "provider_budget_count",
        "required_nodes",
        "completed_nodes",
        "reused_nodes",
        "compatibility_rebound_nodes",
        "rebound_nodes",
    }
)


def _register_manual_diagnostic_contract() -> None:
    """Make every #687 progress emission valid under the strict diagnostic schema."""

    _diagnostic._PROGRESS_STAGES = frozenset(
        (*_diagnostic._PROGRESS_STAGES, *_EXACT_PROGRESS_STAGES)
    )
    _diagnostic._PROGRESS_LANE_STAGES = frozenset(
        (*_diagnostic._PROGRESS_LANE_STAGES, *_LANE_PROGRESS_STAGES)
    )
    _diagnostic._PROGRESS_METRICS = frozenset(
        (*_diagnostic._PROGRESS_METRICS, *_PROGRESS_METRICS)
    )


def _install_finalizer_failure_boundary() -> None:
    """Retain a safe deterministic-finalizer token instead of an opaque internal error."""

    from operations import authoritative_comprehensive_discovery as authoritative

    current = authoritative._provider_free_finalize
    if getattr(current, "_comprehensive_discovery_failure_boundary", False):
        return

    def provider_free_finalize(*args: Any, **kwargs: Any):
        try:
            return current(*args, **kwargs)
        except Exception as error:
            if "provider-free-finalizer" in str(error).lower():
                raise
            raise authoritative._scheduler.CertificationSchedulerError(
                "provider-free-finalizer; "
                f"failure_type={type(error).__name__}"
            ) from error

    provider_free_finalize._comprehensive_discovery_failure_boundary = True  # type: ignore[attr-defined]
    authoritative._provider_free_finalize = provider_free_finalize


def install_comprehensive_discovery_runtime_contract() -> None:
    """Install the diagnostic schema and safe finalizer boundary exactly once."""

    _register_manual_diagnostic_contract()
    _install_finalizer_failure_boundary()


__all__ = ["install_comprehensive_discovery_runtime_contract"]
