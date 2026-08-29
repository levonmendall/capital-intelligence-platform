"""Runtime contract for authoritative comprehensive-discovery orchestration.

The manual CIO diagnostic intentionally rejects unknown stages and metrics, so every
operational certification-DAG boundary must be registered before the scheduler emits it.
This module also preserves a credential-safe finalizer boundary, installs the spawn-safe
authoritative lane runner, installs transactional bounded spool materialization, installs
parent-owned DAG supervision, reclaims exact-release spool cache immediately after each
successful lane process exits, and retains broader fail-soft cache reclamation after the
durable success checkpoint.

This is operational orchestration only. It cannot relax market coverage, evidence
freshness/completeness, screening, CIO authority, construction, execution, or paper-only
controls.
"""

from __future__ import annotations

import os
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
        "certification_dag_failed",
        "bounded_spool_catalog_lane",
        "bounded_spool_catalog_lane_complete",
        "bounded_spool_publication_lane",
        "bounded_spool_publication_lane_complete",
        "bounded_spool_screening_lane",
    }
)
_PROGRESS_METRICS = frozenset(
    {
        "provider_budget_count",
        "required_nodes",
        "completed_nodes",
        "reused_nodes",
        "failed_nodes",
        "running_nodes",
        "pending_nodes",
        "compatibility_rebound_nodes",
        "rebound_nodes",
        "catalog_records",
        "peak_rss_bytes",
    }
)


def _register_manual_diagnostic_contract() -> None:
    """Make every authoritative DAG progress emission valid under the strict schema."""

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


def _install_spawn_safe_acquisition() -> None:
    """Ensure lane children receive picklable, lane-scoped governed inputs only."""

    from operations.spawn_safe_authoritative_acquisition import (
        install_spawn_safe_authoritative_acquisition,
    )

    install_spawn_safe_authoritative_acquisition()


def _install_lane_local_spool() -> None:
    """Keep every comprehensive lane as one compact, resumable transaction."""

    from operations.lane_local_comprehensive_discovery_spool import (
        install_lane_local_comprehensive_discovery_spool,
    )
    from operations.transactional_lane_comprehensive_discovery_coordinator import (
        install_transactional_lane_comprehensive_discovery_coordinator,
    )

    install_lane_local_comprehensive_discovery_spool()
    install_transactional_lane_comprehensive_discovery_coordinator()


def _install_dag_native_supervision() -> None:
    """Move the hard kill boundary from the aggregate coordinator to each DAG node."""

    from operations.certification_failure_projection import (
        install_certification_failure_projection,
    )
    from operations.dag_native_comprehensive_supervision import (
        install_dag_native_comprehensive_supervision,
    )
    from operations.dag_node_failure_transport import install_dag_node_failure_transport
    from operations.progress_aware_release_certification import (
        install_progress_aware_dag_node_supervision,
        install_resume_aware_release_dag_projection,
    )

    install_dag_native_comprehensive_supervision()
    install_progress_aware_dag_node_supervision()
    install_resume_aware_release_dag_projection()
    # Install after supervision wrappers so every clean-spawn node preserves the same
    # bounded direct-cause truth already retained by the nested lane subprocess boundary.
    install_dag_node_failure_transport()
    install_certification_failure_projection()


def _install_lane_exit_cache_reclamation() -> None:
    """Reclaim exact-release spool cache at the parent-owned child-exit handoff."""

    from operations import dag_native_comprehensive_supervision as supervision
    from operations.post_lane_cache_reclamation import (
        run_lane_exit_exact_spool_cache_reclamation,
    )

    current = supervision._terminal_result
    if getattr(current, "_lane_exit_exact_spool_cache_reclamation", False):
        return

    def terminal_result(item, message):
        outcome = current(item, message)
        if not isinstance(outcome, BaseException):
            try:
                run_lane_exit_exact_spool_cache_reclamation(
                    os.environ,
                    node_id=str(getattr(item.node, "node_id", "certification-node")),
                    asset_class=str(getattr(item.node, "asset_class", "other")),
                )
            except Exception:  # noqa: BLE001 - operational cache hygiene is fail-soft.
                pass
        return outcome

    terminal_result._lane_exit_exact_spool_cache_reclamation = True  # type: ignore[attr-defined]
    supervision._terminal_result = terminal_result


def _install_post_lane_cache_reclamation() -> None:
    """Retain broad cache fallback only after a lane success checkpoint is durable."""

    from operations import persistent_certification_scheduler as scheduler
    from operations.post_lane_cache_reclamation import run_post_lane_cache_reclamation

    current = scheduler.PersistentCertificationScheduler._write_success
    if getattr(current, "_post_lane_cache_reclamation", False):
        return

    def write_success(self, node, *, evidence_complete_count: int):
        result = current(
            self,
            node,
            evidence_complete_count=evidence_complete_count,
        )
        try:
            run_post_lane_cache_reclamation(
                self.values,
                node_id=node.node_id,
                asset_class=node.asset_class,
            )
        except Exception:  # noqa: BLE001 - cache hygiene is deliberately fail-soft.
            pass
        return result

    write_success._post_lane_cache_reclamation = True  # type: ignore[attr-defined]
    scheduler.PersistentCertificationScheduler._write_success = write_success


def install_comprehensive_discovery_runtime_contract() -> None:
    """Install strict progress, transactional lanes, DAG supervision, and cache hygiene."""

    _register_manual_diagnostic_contract()
    _install_finalizer_failure_boundary()
    _install_spawn_safe_acquisition()
    _install_lane_local_spool()
    _install_dag_native_supervision()
    _install_lane_exit_cache_reclamation()
    _install_post_lane_cache_reclamation()


__all__ = ["install_comprehensive_discovery_runtime_contract"]
