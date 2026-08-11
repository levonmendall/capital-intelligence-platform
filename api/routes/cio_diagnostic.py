"""Credential-safe audit status for the release-triggered CIO diagnostic."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response, status

from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic
from production_context_publication_runtime import _load_json, _state_path
from production_context_state_resilience import latest_attempt

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


def _parse_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: datetime | None, *, now: datetime) -> float | None:
    if value is None:
        return None
    return round(max(0.0, (now - value.astimezone(timezone.utc)).total_seconds()), 3)


def _latest_context_attempt(settings: Any) -> Mapping[str, Any]:
    """Return optional attempt metadata without making audit safety depend on it."""

    if getattr(settings, "portfolio_database", None) is None:
        return {}
    attempt = latest_attempt(settings)
    return attempt if isinstance(attempt, Mapping) else {}


def _market_lanes(
    payload: object,
    *,
    comprehensive_discovery_complete: bool,
) -> tuple[dict[str, object], ...]:
    """Return lane coverage without requiring a qualifying investment candidate."""
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
        represented = (not scheduled) or (
            comprehensive_discovery_complete and catalog > 0
        )
        lanes.append(
            {
                "asset_class": str(asset_class),
                "scheduled": scheduled,
                "schedule_reason": None
                if raw.get("schedule_reason") in (None, "")
                else str(raw.get("schedule_reason"))[:200],
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
    """Return only release, lifecycle, aggregate coverage, and market-lane counts.

    Persisted production context is cycle-scoped evidence. It may be included only when
    its cycle key exactly matches the current diagnostic request. Lifecycle/freshness fields
    are operational metadata only and cannot authorize an investment or execution action.
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
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
            "all_market_evaluation_complete": False,
            "market_lanes": [],
        }

    now = datetime.now(timezone.utc)
    context_path: Path = _state_path(settings)
    persisted_context = _load_json(context_path) or {}
    cycle_matches = bool(
        diagnostic.cycle_key
        and str(persisted_context.get("cycle_key") or "") == diagnostic.cycle_key
    )
    context: Mapping[str, Any] = persisted_context if cycle_matches else {}

    scope_required = context.get("comprehensive_discovery_required") is True
    scope_state = str(context.get("comprehensive_discovery_scope_state") or "missing")
    scope_complete = scope_state == "complete"
    instrument_count = _count(context, "instrument_count")
    candidate_count = _count(context, "candidate_count")
    exclusion_count = _count(context, "exclusion_count")
    qualified_candidate_count = _count(context, "qualified_candidate_count")
    terminal_screening_complete = (
        instrument_count > 0 and candidate_count + exclusion_count == instrument_count
    )
    lanes = _market_lanes(
        context.get("comprehensive_discovery_lane_counts"),
        comprehensive_discovery_complete=scope_complete,
    )
    scheduled_lanes = tuple(item for item in lanes if item["scheduled"] is True)
    scheduled_market_coverage_complete = bool(scheduled_lanes) and all(
        item["represented"] is True for item in scheduled_lanes
    )
    expected_requester = f"render-release:{release}"
    release_matches = release == "unknown" or diagnostic.requested_by == expected_requester
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

    attempt = _latest_context_attempt(settings)
    attempt_started = _parse_datetime(attempt.get("started_at"))
    current_attempt = bool(
        diagnostic.started_at is not None
        and attempt_started is not None
        and attempt_started >= diagnostic.started_at.astimezone(timezone.utc)
    )
    attempt_cycle = (
        str(attempt.get("cycle_key") or "").strip() if current_attempt else ""
    )

    return {
        "ready": all_market_evaluation_complete,
        "state": diagnostic.state,
        "detail": diagnostic.detail,
        "active_release": release,
        "release_matches": release_matches,
        "request_id": diagnostic.request_id,
        "diagnostic_id": diagnostic.request_id,
        "requested_at": diagnostic.requested_at.isoformat(),
        "started_at": None
        if diagnostic.started_at is None
        else diagnostic.started_at.isoformat(),
        "completed_at": None
        if diagnostic.completed_at is None
        else diagnostic.completed_at.isoformat(),
        "diagnostic_age_seconds": _age_seconds(diagnostic.requested_at, now=now),
        "terminal_age_seconds": _age_seconds(diagnostic.completed_at, now=now),
        "stage": diagnostic.progress_stage,
        "cycle_key": diagnostic.cycle_key,
        "snapshot_identifier": diagnostic.snapshot_identifier,
        "context_cycle_matches": cycle_matches,
        "context_attempt_state": (
            str(attempt.get("state") or "unknown") if current_attempt else "not_current"
        ),
        "context_attempt_cycle_matches": bool(
            attempt_cycle
            and diagnostic.cycle_key
            and attempt_cycle == diagnostic.cycle_key
        ),
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
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


@router.get(
    "/v1/operations/cio-diagnostic",
    responses={503: {"description": "The current all-market CIO diagnostic is incomplete"}},
)
def cio_diagnostic_status(request: Request, response: Response) -> dict[str, object]:
    payload = build_cio_diagnostic_audit(settings=request.app.state.settings)
    if payload["ready"] is not True:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.get(
    "/v1/operations/cio-diagnostic/telemetry",
    summary="Read live credential-safe CIO diagnostic telemetry",
)
def cio_diagnostic_telemetry(request: Request) -> dict[str, object]:
    """Expose live diagnostic progress without using readiness HTTP status as transport state."""

    return build_cio_diagnostic_audit(settings=request.app.state.settings)


__all__ = [
    "build_cio_diagnostic_audit",
    "cio_diagnostic_status",
    "cio_diagnostic_telemetry",
    "router",
]
