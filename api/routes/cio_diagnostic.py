"""Credential-safe audit status for the release-triggered CIO diagnostic."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response, status

from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic
from production_context_publication_runtime import _load_json, _state_path

router = APIRouter(tags=["operations"])


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _count(payload: Mapping[str, Any], name: str) -> int:
    value = payload.get(name, 0)
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _market_lanes(payload: object) -> tuple[dict[str, object], ...]:
    """Return credential-safe coverage counts for each governed discovery lane.

    A successful comprehensive-discovery publication already guarantees that every
    current record in a scheduled nonempty catalog has an explicit selected or excluded
    outcome. Therefore market representation is catalog coverage, not a requirement to
    manufacture a candidate. Deep and selected counts remain visible diagnostics but
    cannot turn a truthful all-excluded lane into a false coverage failure.
    """

    if not isinstance(payload, Mapping):
        return ()
    lanes: list[dict[str, object]] = []
    for asset_class, raw in sorted(payload.items(), key=lambda item: str(item[0])):
        if not isinstance(raw, Mapping):
            continue
        scheduled = raw.get("scheduled") is True
        catalog = _count(raw, "catalog")
        deep = _count(raw, "deep")
        selected = _count(raw, "selected")
        represented = (not scheduled) or catalog > 0
        lanes.append(
            {
                "asset_class": str(asset_class),
                "scheduled": scheduled,
                "schedule_reason": (
                    None
                    if raw.get("schedule_reason") in (None, "")
                    else str(raw.get("schedule_reason"))[:200]
                ),
                "catalog_count": catalog,
                "deep_analyzed_count": deep,
                "selected_count": selected,
                "represented": represented,
            }
        )
    return tuple(lanes)


def build_cio_diagnostic_audit(
    *,
    settings: Any,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return only release, state, aggregate coverage, and market-lane counts.

    Persisted production context is cycle-scoped evidence. It may be included only when
    its cycle key exactly matches the current diagnostic request. A diagnostic that fails
    before publishing its own context therefore reports fresh failure state with empty,
    fail-closed aggregates instead of inheriting counts, sources, or limitations from an
    older cycle.
    """

    resolved = os.environ if values is None else values
    release = _release(resolved)
    diagnostic = latest_manual_cio_diagnostic(values=resolved)
    if diagnostic is None:
        return {
            "ready": False,
            "state": "not_recorded",
            "detail": "no release-triggered CIO diagnostic has been recorded",
            "active_release": release,
            "paper_only": True,
            "real_money_authorized": False,
            "all_market_evaluation_complete": False,
            "market_lanes": [],
        }

    context_path: Path = _state_path(settings)
    persisted_context = _load_json(context_path) or {}
    cycle_matches = bool(
        diagnostic.cycle_key
        and str(persisted_context.get("cycle_key") or "")
        == diagnostic.cycle_key
    )
    # Never expose or evaluate persisted evidence from another diagnostic cycle.
    context: Mapping[str, Any] = persisted_context if cycle_matches else {}

    scope_required = context.get("comprehensive_discovery_required") is True
    scope_state = str(
        context.get("comprehensive_discovery_scope_state") or "missing"
    )
    scope_complete = scope_state == "complete"
    instrument_count = _count(context, "instrument_count")
    candidate_count = _count(context, "candidate_count")
    exclusion_count = _count(context, "exclusion_count")
    qualified_candidate_count = _count(context, "qualified_candidate_count")
    terminal_screening_complete = (
        instrument_count > 0
        and candidate_count + exclusion_count == instrument_count
    )
    lanes = _market_lanes(context.get("comprehensive_discovery_lane_counts"))
    scheduled_lanes = tuple(item for item in lanes if item["scheduled"] is True)
    scheduled_market_coverage_complete = bool(scheduled_lanes) and all(
        item["represented"] is True for item in scheduled_lanes
    )
    expected_requester = f"render-release:{release}"
    release_matches = (
        release == "unknown" or diagnostic.requested_by == expected_requester
    )
    diagnostic_completed = diagnostic.state == "completed"
    all_market_evaluation_complete = all(
        (
            diagnostic_completed,
            release_matches,
            cycle_matches,
            scope_required,
            scope_complete,
            scheduled_market_coverage_complete,
            terminal_screening_complete,
        )
    )
    return {
        "ready": all_market_evaluation_complete,
        "state": diagnostic.state,
        "detail": diagnostic.detail,
        "active_release": release,
        "release_matches": release_matches,
        "request_id": diagnostic.request_id,
        "requested_at": diagnostic.requested_at.isoformat(),
        "started_at": (
            None if diagnostic.started_at is None else diagnostic.started_at.isoformat()
        ),
        "completed_at": (
            None
            if diagnostic.completed_at is None
            else diagnostic.completed_at.isoformat()
        ),
        "cycle_key": diagnostic.cycle_key,
        "snapshot_identifier": diagnostic.snapshot_identifier,
        "context_cycle_matches": cycle_matches,
        "comprehensive_discovery_required": scope_required,
        "comprehensive_discovery_scope_state": scope_state,
        "comprehensive_discovery_complete": scope_complete,
        "comprehensive_discovery_limitations": [
            str(item)[:500]
            for item in context.get("comprehensive_discovery_limitations", [])
            if isinstance(item, str)
        ],
        "instrument_count": instrument_count,
        "candidate_count": candidate_count,
        "exclusion_count": exclusion_count,
        "qualified_candidate_count": qualified_candidate_count,
        "terminal_screening_complete": terminal_screening_complete,
        "scheduled_market_coverage_complete": scheduled_market_coverage_complete,
        "all_market_evaluation_complete": all_market_evaluation_complete,
        "market_lanes": list(lanes),
        "paper_only": True,
        "real_money_authorized": False,
    }


@router.get(
    "/v1/operations/cio-diagnostic",
    responses={503: {"description": "The current all-market CIO diagnostic is incomplete"}},
)
def cio_diagnostic_status(
    request: Request,
    response: Response,
) -> dict[str, object]:
    payload = build_cio_diagnostic_audit(settings=request.app.state.settings)
    if payload["ready"] is not True:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


__all__ = ["build_cio_diagnostic_audit", "cio_diagnostic_status", "router"]
