"""Credential-safe lane attribution for comprehensive-discovery memory failures.

Telemetry #709 proved that the fail-closed resource guard can terminate comprehensive
market discovery after the parent watchdog has correctly observed lane-local progress. The
active lane marker already records the finite unit being executed, so this module projects
that existing non-authoritative state into a small failure-context payload after a memory
termination.

This module changes no memory boundary, timeout, market or candidate scope, evidence rule,
CIO authority, construction rule, execution behavior, or paper-only control.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping


_ACTIVE_COMPONENTS = {
    "bounded-spool-catalog-lane": "catalog-lane",
    "bounded-spool-publication-lane": "publication-lane",
    "bounded-spool-screening-lane": "screening-lane",
}
_COMPLETED_COMPONENTS = {
    "bounded-catalog-lane-complete": "catalog-lane",
    "bounded-publication-lane-complete": "publication-lane",
    "bounded-screening-lane-complete": "screening-lane",
}
_SAFE_METRICS = frozenset(
    {
        "active_lane_index",
        "candidate_lanes",
        "completed_catalog_lanes",
        "completed_publication_lanes",
        "completed_screening_lanes",
        "scheduled_lanes",
        "catalog_records",
        "decision_eligible_records",
        "peak_rss_bytes",
        "bounded_provider_publication",
    }
)


def _component_identity(component: str) -> tuple[str, str | None, str]:
    normalized = str(component or "").strip().lower()
    if normalized == "bounded-discovery-manifest-complete":
        return "manifest", None, "completed"

    prefix, separator, asset_class = normalized.partition(":")
    if not separator or not asset_class:
        return "unknown", None, "unknown"
    if prefix in _ACTIVE_COMPONENTS:
        return _ACTIVE_COMPONENTS[prefix], asset_class, "active"
    if prefix in _COMPLETED_COMPONENTS:
        return _COMPLETED_COMPONENTS[prefix], asset_class, "completed"
    return "unknown", asset_class, "unknown"


def _safe_metrics(metrics: object) -> dict[str, int]:
    if not isinstance(metrics, Mapping):
        return {}
    safe: dict[str, int] = {}
    for name in _SAFE_METRICS:
        value = metrics.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[name] = value
    return safe


def lane_local_memory_failure_context(
    values: Mapping[str, str],
    *,
    boundary: datetime,
) -> dict[str, object] | None:
    """Return the newest exact-release lane progress suitable for failure telemetry.

    An active marker is exact attribution because the coordinator writes it immediately
    before launching that finite child unit. If no active marker is available, the returned
    completed component is explicitly labeled as last durable progress and must not be
    treated as proof that the following unit was the failure source.
    """

    from operations.lane_local_watchdog_progress import (
        lane_local_bounded_discovery_progress,
    )

    observed = lane_local_bounded_discovery_progress(values, boundary=boundary)
    if observed is None:
        return None

    component = str(getattr(observed, "component", "") or "").strip().lower()
    substage, asset_class, progress_kind = _component_identity(component)
    recorded_at = getattr(observed, "recorded_at", None)
    if not component or not isinstance(recorded_at, datetime):
        return None

    metrics = _safe_metrics(getattr(observed, "metrics", None))
    lane_index = metrics.get("active_lane_index") if progress_kind == "active" else None
    return {
        "component": component,
        "substage": substage,
        "asset_class": asset_class,
        "progress_kind": progress_kind,
        "active_lane_index": lane_index,
        "recorded_at": recorded_at.isoformat(),
        "metrics": metrics,
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


__all__ = ["lane_local_memory_failure_context"]
