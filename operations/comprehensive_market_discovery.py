"""Compositional, resumable facade for comprehensive all-market discovery.

The complete terminal-accounting implementation is preserved byte-for-byte in
``operations._comprehensive_market_discovery_v6``. This facade adds only durable,
exact-release/epoch evidence checkpoints and immutable lane certification artifacts.

No catalog membership, screening rule, factor requirement, ranking, threshold, CIO
authority, portfolio construction, execution behavior, or paper-only control changes.
"""

from __future__ import annotations

from operations import _comprehensive_market_discovery_v6 as _core
from operations._comprehensive_market_discovery_v6 import *  # noqa: F401,F403
from operations.all_market_lane_certification import (
    AllMarketLaneCertificationError,
    install_checkpointed_market_probe,
    publish_compositional_certification,
)


install_checkpointed_market_probe(_core)

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
    """Run unchanged full-universe discovery, then enforce the compositional barrier."""

    _assert_public_terminal_screening_bound(
        chunk_size=_PRODUCTION_TERMINAL_SCREENING_CHUNK_SIZE
    )
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
