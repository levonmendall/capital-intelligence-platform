"""Compositional, resumable facade for comprehensive all-market discovery.

The complete terminal-accounting implementation is preserved byte-for-byte in
``operations._comprehensive_market_discovery_v6``. This facade adds only durable,
exact-release/epoch evidence checkpoints, the point-in-time evidence snapshot barrier,
and immutable lane certification artifacts.

No catalog membership, screening rule, factor requirement, ranking, threshold, CIO
authority, portfolio construction, execution behavior, or paper-only control changes.
"""

from __future__ import annotations

import os

from operations import _comprehensive_market_discovery_v6 as _core
from operations._comprehensive_market_discovery_v6 import *  # noqa: F401,F403
from operations.all_market_lane_certification import (
    AllMarketLaneCertificationError,
    install_checkpointed_market_probe,
    publish_compositional_certification,
)
from operations.continuous_evidence_plane import (
    ContinuousEvidencePlaneError,
    ensure_point_in_time_snapshot,
    evidence_plane_enabled,
)
from operations.persistent_historical_evidence import install_persistent_historical_evidence
from operations.persistent_option_reference import install_persistent_option_reference
from operations.resumable_options_discovery import install_resumable_options_catalog


install_checkpointed_market_probe(_core)
install_resumable_options_catalog(_core)
install_persistent_option_reference(_core)
install_persistent_historical_evidence()

_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_SNAPSHOT_ID_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_SNAPSHOT_ID"
_SNAPSHOT_AS_OF_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_SNAPSHOT_AS_OF"
_SNAPSHOT_PLANE_ENV = "CAPITAL_INTELLIGENCE_CIO_EVIDENCE_PLANE_GENERATION_ID"

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


def _point_in_time_snapshot_barrier(as_of):
    """Require a qualified evidence-plane snapshot before governed discovery begins."""

    values = os.environ
    if not _production_plane_enabled(values):
        return None
    if values.get(_PREPARING_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        # The background/pre-clock evidence preparation itself must be able to execute
        # comprehensive discovery in order to populate the stores it is qualifying.
        return None

    prior = values.get(_PREPARING_ENV)
    values[_PREPARING_ENV] = "true"
    try:
        snapshot = ensure_point_in_time_snapshot(
            cutoff=as_of,
            values=values,
            allow_refresh=True,
        )
    finally:
        if prior is None:
            values.pop(_PREPARING_ENV, None)
        else:
            values[_PREPARING_ENV] = prior
    values[_SNAPSHOT_ID_ENV] = snapshot.snapshot_id
    values[_SNAPSHOT_AS_OF_ENV] = snapshot.cutoff.isoformat()
    values[_SNAPSHOT_PLANE_ENV] = snapshot.plane_generation_id
    return snapshot


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
    """Freeze PIT evidence, run unchanged discovery, then enforce composition."""

    # Preserved-core provider-preselection invariant:
    # market_probe=default_provider_preselection_market_probe
    _assert_public_terminal_screening_bound(
        chunk_size=_PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE
    )
    try:
        _point_in_time_snapshot_barrier(as_of)
    except ContinuousEvidencePlaneError as error:
        raise _core._base._legacy.ComprehensiveMarketDiscoveryError(
            f"point-in-time evidence snapshot is not ready: {error}"
        ) from error
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