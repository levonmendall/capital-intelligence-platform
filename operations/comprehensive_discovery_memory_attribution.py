"""Credential-safe lane attribution for comprehensive-discovery memory failures.

Telemetry #709 proved that the fail-closed resource guard can terminate comprehensive
market discovery after the parent watchdog has correctly observed lane-local progress. The
active lane marker already records the finite unit being executed, so this module projects
that existing non-authoritative state into a small failure-context payload after a memory
termination.

Telemetry #716 exposed two attribution gaps: watchdog progress timestamps are stored as
``updated_at`` rather than ``recorded_at``, and a still-current active lane marker may belong
to a reusable request whose request-file mtime predates the current stage boundary. The
fallback below validates the exact-release request identity and the active marker's own
current timestamp, so stale requests cannot manufacture current failure attribution.

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


def _context_from_progress(observed: object) -> dict[str, object] | None:
    component = str(getattr(observed, "component", "") or "").strip().lower()
    substage, asset_class, progress_kind = _component_identity(component)
    recorded_at = getattr(observed, "updated_at", None)
    if not isinstance(recorded_at, datetime):
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


def _current_active_marker_context(
    values: Mapping[str, str],
    *,
    boundary: datetime,
) -> dict[str, object] | None:
    """Read only a current active marker when the reusable request itself is older.

    The request envelope remains integrity- and release-validated. Currency comes from the
    active marker's own ``updated_at`` timestamp, not the reusable request-file mtime.
    """

    from operations import comprehensive_discovery_input_spool as spool
    from operations import lane_local_comprehensive_discovery_spool as lane_local
    from operations import lane_local_watchdog_progress as lane_progress

    try:
        root = spool._root(values)
        request_paths = tuple(root.glob("*/*/request.json"))
        release = spool._release(values)
        lanes = tuple(lane_local._candidate_lanes())
    except (OSError, RuntimeError, TypeError, ValueError):
        return None

    best: tuple[datetime, dict[str, object]] | None = None
    for request_path in request_paths:
        request = lane_progress._load_request_identity(request_path, spool)
        if not isinstance(request, Mapping):
            continue
        request_id = str(request.get("request_id") or "").strip()
        if not request_id or str(request.get("release") or "").strip() != release:
            continue
        active = lane_progress._load_active_state(
            request_path,
            request_id=request_id,
            release=release,
            boundary=boundary,
        )
        if active is None:
            continue
        action, asset_class, index, updated_at = active
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            continue
        try:
            lane_identity = str(lanes[index].value).strip().lower()
        except IndexError:
            continue
        if lane_identity != asset_class or action not in lane_progress._ACTION_COMPONENTS:
            continue

        component = f"{lane_progress._ACTION_COMPONENTS[action]}:{asset_class}"
        context = _context_from_progress(
            type(
                "_ActiveLaneProgress",
                (),
                {
                    "component": component,
                    "updated_at": updated_at,
                    "metrics": {
                        "active_lane_index": index,
                        "candidate_lanes": len(lanes),
                    },
                },
            )()
        )
        if context is None:
            continue
        if best is None or updated_at > best[0]:
            best = (updated_at, context)
    return None if best is None else best[1]


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
    context = None if observed is None else _context_from_progress(observed)
    if context is not None:
        return context

    # A discovery request can legitimately be reused across a current exact-release stage.
    # In that case the request mtime is older than the stage boundary even though the active
    # marker was written immediately before the current finite child. Validate that marker
    # directly rather than losing exact memory-failure attribution.
    return _current_active_marker_context(values, boundary=boundary)


__all__ = ["lane_local_memory_failure_context"]
