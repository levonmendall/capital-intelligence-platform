"""Bootstrap continuous evidence with the authoritative DAG runtime installed first.

The bounded evidence worker starts a fresh interpreter for every preparation pass.  That
fresh process must install comprehensive-discovery runtime contracts before importing the
continuous-evidence owner; otherwise component-qualified maintenance can capture the legacy
aggregate 540-second discovery supervisor before the DAG-native installer is imported.

The evidence owner also performs provider-facing preparation after public-live qualification
and before the first certification-DAG journal exists.  Genuine completed requests from that
interval are persisted as non-authoritative progress so the parent no-progress supervisor
does not mistake active discovery for a dead bootstrap.

This bootstrap changes only operational supervision and observability.  It does not change
market scope, evidence freshness/completeness, screening, CIO authority, construction,
execution, or paper-only controls.
"""

from __future__ import annotations

from collections.abc import Sequence

from operations.comprehensive_discovery_runtime_contract import (
    install_comprehensive_discovery_runtime_contract,
)


_CACHED_TRANSACTION_MODULE = "operations.cached_transactional_comprehensive_discovery_lane"


def install_and_verify_dag_native_runtime() -> None:
    """Install the runtime contract and fail closed if any legacy seam remains active."""

    install_comprehensive_discovery_runtime_contract()

    from operations.evidence_preparation_progress import (
        install_post_public_provider_progress,
    )

    # Install only after the DAG contract is authoritative.  This hook runs in the
    # disposable evidence-owner interpreter; spawned lane workers have their own progress
    # transport and start from fresh interpreters.
    install_post_public_provider_progress()

    from operations import authoritative_comprehensive_discovery as authoritative
    from operations import component_qualified_evidence_maintenance as maintenance
    from operations import persistent_certification_scheduler as scheduler
    from operations import transactional_lane_comprehensive_discovery_coordinator as coordinator

    # Comprehensive retry epochs may reuse only release/reference-bound raw catalog
    # reconstruction. The finite child wrapper delegates every current-epoch provider
    # publication, screening, node, and market-evidence step to the unchanged canonical
    # transaction implementation.
    coordinator._MODULE = _CACHED_TRANSACTION_MODULE

    missing: list[str] = []
    if not getattr(
        maintenance._supervised_discovery_runner,
        "_dag_native_supervision",
        False,
    ):
        missing.append("discovery_coordinator")
    if not getattr(
        scheduler.PersistentCertificationScheduler.run,
        "_dag_native_supervision",
        False,
    ):
        missing.append("certification_scheduler")
    if not getattr(
        authoritative._acquire,
        "_spawn_safe_authoritative_acquisition",
        False,
    ):
        missing.append("spawn_safe_acquisition")
    if coordinator._MODULE != _CACHED_TRANSACTION_MODULE:
        missing.append("structural_cache_transaction_worker")
    if missing:
        raise RuntimeError(
            "continuous evidence refused legacy comprehensive-discovery runtime: "
            + ",".join(missing)
        )


def main(argv: Sequence[str] | None = None) -> int:
    install_and_verify_dag_native_runtime()
    from run_continuous_evidence_plane import main as evidence_main

    return evidence_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
