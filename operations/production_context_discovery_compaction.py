"""Release heavyweight discovery graphs before production-context evidence finalization.

Production context needs discovery to establish the governed instrument universe, but after
that handoff it consumes only a small set of discovery metadata plus observed prices used
for opportunity-outcome reconciliation.  The canonical discovery results additionally
retain detailed selected/excluded evidence graphs which are no longer authoritative once
the instrument contracts have been materialized into the governed universe.

This Render-only installation seam replaces those results with read-only compact views at
the production-context boundary.  It does not change discovery membership, rankings,
evidence requirements, point-in-time lineage, market scope, memory limits, CIO authority,
construction, execution, or the paper-only boundary.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from typing import Any

import production_context_publication_governed as _governed


_INSTALLED_ATTR = "_production_context_discovery_compaction_installed"
_ORIGINAL_DISCOVER_US_EQUITIES = _governed.discover_us_equities
_ORIGINAL_DISCOVER_COMPREHENSIVE_SCOPE = _governed._discover_comprehensive_scope


@dataclass(frozen=True, slots=True)
class _CompactEquityDiscovery:
    identifier: str
    as_of: object
    policy_version: str
    screened_asset_count: int
    snapshot_covered_count: int
    deep_shortlist_count: int
    selected_count: int
    observed_prices: tuple[object, ...]
    security_master_snapshot_identifier: str
    instruments: tuple[object, ...]

    @property
    def selected(self) -> range:
        """Expose only the selected cardinality required by context telemetry."""

        return range(self.selected_count)

    def instruments_for_holdings(self, _held_symbols) -> tuple[object, ...]:
        """Return the exact contracts already materialized for this holding set."""

        return self.instruments


@dataclass(frozen=True, slots=True)
class _CompactLane:
    asset_class: object
    catalog_count: int
    deep_analyzed_count: int
    scheduled: bool
    schedule_reason: str
    selected_count: int

    @property
    def selected(self) -> range:
        return range(self.selected_count)


@dataclass(frozen=True, slots=True)
class _CompactComprehensiveDiscovery:
    identifier: str
    manifest_fingerprint: str
    policy_version: str
    scope_state: str
    limitations: tuple[str, ...]
    lanes: tuple[_CompactLane, ...]
    instruments: tuple[object, ...]

    def instruments_for_holdings(self, _held_symbols) -> tuple[object, ...]:
        """Return the exact contracts already materialized for this holding set."""

        return self.instruments


def _compact_equity_result(result: Any, *, held_symbols) -> _CompactEquityDiscovery:
    """Retain only production-context consumers of a completed equity discovery."""

    instruments = tuple(result.instruments_for_holdings(held_symbols))
    return _CompactEquityDiscovery(
        identifier=str(result.identifier),
        as_of=getattr(result, "as_of", None),
        policy_version=str(result.policy_version),
        screened_asset_count=int(result.screened_asset_count),
        snapshot_covered_count=int(result.snapshot_covered_count),
        deep_shortlist_count=int(getattr(result, "deep_shortlist_count", 0)),
        selected_count=len(result.selected),
        observed_prices=tuple(result.observed_prices),
        security_master_snapshot_identifier=str(
            result.security_master_snapshot_identifier
        ),
        instruments=instruments,
    )


def _compact_comprehensive_result(
    result: Any,
    *,
    held_symbols,
) -> _CompactComprehensiveDiscovery:
    """Retain terminal accounting metadata without retaining discovery evidence graphs."""

    instruments = tuple(result.instruments_for_holdings(held_symbols))
    lanes = tuple(
        _CompactLane(
            asset_class=lane.asset_class,
            catalog_count=int(lane.catalog_count),
            deep_analyzed_count=int(lane.deep_analyzed_count),
            scheduled=bool(lane.scheduled),
            schedule_reason=str(lane.schedule_reason),
            selected_count=len(lane.selected),
        )
        for lane in result.lanes
    )
    return _CompactComprehensiveDiscovery(
        identifier=str(result.identifier),
        manifest_fingerprint=str(result.manifest_fingerprint),
        policy_version=str(result.policy_version),
        scope_state=str(getattr(result, "scope_state", "complete")),
        limitations=tuple(str(item) for item in getattr(result, "limitations", ())),
        lanes=lanes,
        instruments=instruments,
    )


def _compact_discover_us_equities(*args, **kwargs):
    held_symbols = tuple(kwargs.get("held_symbols", ()))
    result = _ORIGINAL_DISCOVER_US_EQUITIES(*args, **kwargs)
    compact = _compact_equity_result(result, held_symbols=held_symbols)
    del result
    gc.collect()
    return compact


def _compact_discover_comprehensive_scope(
    *,
    as_of,
    held_symbols,
    tracked_symbols,
    excluded_symbols,
    probe,
    required,
):
    result = _ORIGINAL_DISCOVER_COMPREHENSIVE_SCOPE(
        as_of=as_of,
        held_symbols=held_symbols,
        tracked_symbols=tracked_symbols,
        excluded_symbols=excluded_symbols,
        probe=probe,
        required=required,
    )
    compact = _compact_comprehensive_result(result, held_symbols=held_symbols)
    del result
    gc.collect()
    return compact


def install() -> None:
    """Install compact discovery handoffs exactly once for the governed context runtime."""

    if getattr(_governed, _INSTALLED_ATTR, False):
        return
    _governed.discover_us_equities = _compact_discover_us_equities
    _governed._discover_comprehensive_scope = _compact_discover_comprehensive_scope
    setattr(_governed, _INSTALLED_ATTR, True)


__all__ = ["install"]
