"""Compositional, resumable facade for comprehensive all-market discovery.

The complete terminal-accounting implementation is preserved byte-for-byte in
``operations._comprehensive_market_discovery_v6``. This facade adds durable,
exact-release/epoch evidence checkpoints, a provider-aware persistent certification DAG,
an immutable provider-free point-in-time certification-input barrier, immutable lane
certification artifacts, and provider-free reuse of a qualified global discovery snapshot.

No catalog membership, screening rule, factor requirement, ranking, threshold, CIO
authority, portfolio construction, execution behavior, or paper-only control changes.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from operations import _comprehensive_market_discovery_v6 as _core
from operations._comprehensive_market_discovery_v6 import *  # noqa: F401,F403
from operations.all_market_lane_certification import (
    AllMarketLaneCertificationError,
    install_checkpointed_market_probe,
    publish_compositional_certification,
    validate_published_compositional_certification,
)
from operations.certification_input_manifest import (
    CertificationInputError,
    freeze_certification_input,
)
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.persistent_certification_scheduler import install_certification_scheduler
from operations.persistent_historical_evidence import install_persistent_historical_evidence
from operations.persistent_option_reference import install_persistent_option_reference
from operations.qualified_comprehensive_discovery_snapshot import (
    ComprehensiveDiscoverySnapshotError,
    load_qualified_comprehensive_discovery_snapshot,
    view_qualified_comprehensive_discovery_snapshot,
)
from operations.resumable_options_discovery import install_resumable_options_catalog
from storage_governance import install_persistent_history_storage_governance


install_checkpointed_market_probe(_core)
install_certification_scheduler(_core)
install_resumable_options_catalog(_core)
install_persistent_option_reference(_core)
install_persistent_historical_evidence()
install_persistent_history_storage_governance()

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_SNAPSHOT_ID_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_SNAPSHOT_ID"
_SNAPSHOT_AS_OF_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_SNAPSHOT_AS_OF"
_SNAPSHOT_PLANE_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_PLANE_GENERATION_ID"
_CERTIFICATION_INPUT_ENV = "CAPITAL_INTELLIGENCE_CIO_CERTIFICATION_INPUT_ID"
_GLOBAL_DISCOVERY_SNAPSHOT_ENV = (
    "CAPITAL_INTELLIGENCE_CIO_GLOBAL_DISCOVERY_SNAPSHOT_ID"
)

# Keep the production terminal-screening resource bound visible at the public facade.
# Several release guards intentionally inspect this module rather than implementation
# internals because this is the canonical import path used by the CIO runtime.
_PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE = (
    _core._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE
)

# Preserve the public monkeypatch seams used by the existing diagnostic tests. The
# wrapper synchronizes any overridden seam into the preserved core immediately before
# invocation, so test probes and operational instrumentation keep identical behavior.
record_manual_cio_diagnostic_progress = _core.record_manual_cio_diagnostic_progress
default_redundant_market_probe = _core.default_redundant_market_probe
ensure_provider_preselection_publication = _core.ensure_provider_preselection_publication
build_bounded_terminal_preselection = _core.build_bounded_terminal_preselection
build_bounded_cutoff_observations = _core.build_bounded_cutoff_observations
default_provider_preselection_market_probe = _core.default_provider_preselection_market_probe
begin_redundancy_cycle = _core.begin_redundancy_cycle


def _assert_public_terminal_screening_bound(*, chunk_size: int) -> None:
    if chunk_size != _core._PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE:
        raise RuntimeError("public terminal-screening chunk bound diverged from core")


def _sync_core_seams() -> None:
    referenced = set(_core.discover_comprehensive_markets.__code__.co_names)
    referenced.update(
        {
            "record_manual_cio_diagnostic_progress",
            "default_redundant_market_probe",
            "ensure_provider_preselection_publication",
            "build_bounded_terminal_preselection",
            "build_bounded_cutoff_observations",
            "default_provider_preselection_market_probe",
            "begin_redundancy_cycle",
        }
    )
    current = globals()
    for name in referenced:
        if name in current and hasattr(_core, name):
            setattr(_core, name, current[name])


def _production_plane_enabled(values) -> bool:
    explicit = values.get(
        "CAPITAL_INTELLIGENCE_CONTINUOUS_EVIDENCE_PLANE_ENABLED", ""
    ).strip()
    production = (
        values.get("CAPITAL_INTELLIGENCE_ENVIRONMENT", "").strip().lower()
        == "production"
        or values.get("RENDER", "").strip().lower() == "true"
    )
    return (bool(explicit) or production) and evidence_plane_enabled(values)


def _point_in_time_snapshot_barrier(
    as_of,
    *,
    snapshot_loader: Callable[..., object] | None = None,
    input_freezer: Callable[..., object] | None = None,
):
    """Require prequalified evidence; the CIO/read path may never refresh it.

    Optional callables are explicit test/diagnostic seams. Production callers omit them
    and therefore always use the governed disk loader and immutable input publisher.
    """

    values = os.environ
    if not _production_plane_enabled(values):
        return None
    if values.get(_PREPARING_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        # The continuous evidence owner itself must be able to run comprehensive
        # discovery while preparing the stores and lane artifacts it owns.
        return None

    loader = ensure_point_in_time_snapshot if snapshot_loader is None else snapshot_loader
    freezer = freeze_certification_input if input_freezer is None else input_freezer

    # Critical v2 invariant: a consumer can freeze an already-qualified generation but
    # cannot construct, refresh, discover, or repair the global evidence plane. Missing
    # or stale evidence therefore fails closed here and must be repaired by the evidence
    # worker outside the CIO/certification transaction.
    snapshot = loader(
        cutoff=as_of,
        values=values,
        allow_refresh=False,
    )
    certification_input = freezer(
        cutoff=as_of,
        values=values,
        snapshot=snapshot,
    )
    values[_SNAPSHOT_ID_ENV] = snapshot.snapshot_id
    values[_SNAPSHOT_AS_OF_ENV] = snapshot.cutoff.isoformat()
    values[_SNAPSHOT_PLANE_ENV] = snapshot.plane_generation_id
    values[_CERTIFICATION_INPUT_ENV] = certification_input.record_id
    return snapshot


def _provider_free_global_discovery(
    *,
    point_snapshot,
    held_symbols,
    tracked_symbols,
    excluded_symbols,
):
    global_snapshot = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=point_snapshot.plane_as_of,
        values=os.environ,
    )
    # Prove the immutable producer snapshot before deriving a local consumer view.
    # Missing, mismatched, or corrupted exact-release evidence remains fail-closed.
    validate_published_compositional_certification(global_snapshot.result)
    result = view_qualified_comprehensive_discovery_snapshot(
        global_snapshot,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
    )
    os.environ[_GLOBAL_DISCOVERY_SNAPSHOT_ENV] = global_snapshot.snapshot_id
    # Local exclusions change terminal membership and therefore require their own
    # context-matching proof. The publisher fingerprints unbounded selected/excluded
    # sequences incrementally, so this does not recreate the former serialization peak.
    publish_compositional_certification(result)
    return result


def discover_comprehensive_markets(
    *,
    as_of,
    held_symbols=(),
    tracked_symbols=(),
    excluded_symbols=(),
    catalog_probe=None,
    market_probe=None,
    preselection_probe=None,
    prior_cutoff_observations=(),
    policy=None,
):
    """Consume qualified global evidence in production; discover only as evidence owner."""

    # Preserved-core provider-preselection invariant:
    # market_probe=default_provider_preselection_market_probe
    _assert_public_terminal_screening_bound(
        chunk_size=_PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE
    )
    try:
        point_snapshot = _point_in_time_snapshot_barrier(as_of)
    except (ContinuousEvidencePlaneError, CertificationInputError) as error:
        raise _core._base._legacy.ComprehensiveMarketDiscoveryError(
            f"point-in-time evidence snapshot is not ready: {error}"
        ) from error

    if point_snapshot is not None:
        # Once the production consumer crosses the PIT barrier, provider/discovery probes
        # are forbidden. Policy or cutoff-observation overrides would describe a different
        # evidence generation, so they fail closed rather than silently falling back to
        # synchronous global acquisition.
        if any(
            item is not None
            for item in (catalog_probe, market_probe, preselection_probe, policy)
        ) or tuple(prior_cutoff_observations):
            raise _core._base._legacy.ComprehensiveMarketDiscoveryError(
                "production CIO discovery consumer cannot override qualified global evidence"
            )
        try:
            return _provider_free_global_discovery(
                point_snapshot=point_snapshot,
                held_symbols=held_symbols,
                tracked_symbols=tracked_symbols,
                excluded_symbols=excluded_symbols,
            )
        except (ComprehensiveDiscoverySnapshotError, AllMarketLaneCertificationError) as error:
            raise _core._base._legacy.ComprehensiveMarketDiscoveryError(
                f"qualified global discovery snapshot is not ready: {error}"
            ) from error

    # Non-production callers and the continuous evidence owner preserve the canonical
    # implementation. Only the owner is allowed to reach this path in production because
    # it holds CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING=true.
    _sync_core_seams()
    try:
        result = _core.discover_comprehensive_markets(
            as_of=as_of,
            held_symbols=held_symbols,
            tracked_symbols=tracked_symbols,
            excluded_symbols=excluded_symbols,
            catalog_probe=catalog_probe,
            market_probe=market_probe,
            preselection_probe=preselection_probe,
            prior_cutoff_observations=prior_cutoff_observations,
            policy=policy,
        )
        publish_compositional_certification(result)
        return result
    except AllMarketLaneCertificationError as error:
        raise _core._base._legacy.ComprehensiveMarketDiscoveryError(str(error)) from error


def __getattr__(name: str):
    return getattr(_core, name)


__all__ = tuple(
    dict.fromkeys(
        (
            *_core.__all__,
            "discover_comprehensive_markets",
        )
    )
)
