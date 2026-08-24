"""Credential-safe audit status for the release-triggered CIO diagnostic."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response, status

from operations.all_market_certification_readonly import (
    public_all_market_certification_readonly,
)
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic
from operations.public_live_requirement_qualification import (
    load_public_live_requirement_progress,
)
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


def _safe(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


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


def _safe_public_requirement_progress(
    values: Mapping[str, str],
) -> dict[str, object] | None:
    """Expose only the credential-safe operational subset of public qualification state."""

    payload = load_public_live_requirement_progress(values)
    if not isinstance(payload, Mapping):
        return None
    failures: list[dict[str, object]] = []
    for item in payload.get("failures", []):
        if not isinstance(item, Mapping):
            continue
        failures.append(
            {
                "required_information": _safe(str(item.get("required_information") or "unknown")),
                "provider": _safe(str(item.get("provider") or "unknown")),
                "fallback_providers_attempted": [
                    _safe(str(value))
                    for value in item.get("fallback_providers_attempted", [])
                    if str(value).strip()
                ],
                "failure_type": _safe(str(item.get("failure_type") or "unknown")),
            }
        )
    return {
        "state": str(payload.get("state") or "unknown")[:32],
        "updated_at": str(payload.get("updated_at") or "") or None,
        "required_count": _count(payload, "required_count"),
        "qualified_count": _count(payload, "qualified_count"),
        "reused_count": _count(payload, "reused_count"),
        "newly_qualified_count": _count(payload, "newly_qualified_count"),
        "failed_count": _count(payload, "failed_count"),
        "pending_count": _count(payload, "pending_count"),
        "active_required_information": None
        if payload.get("active_required_information") in (None, "")
        else _safe(str(payload.get("active_required_information"))),
        "failed_required_information": [
            _safe(str(value))
            for value in payload.get("failed_required_information", [])
            if str(value).strip()
        ],
        "failures": failures,
    }


def _v2_evidence_as_of(
    certification: Mapping[str, object],
    *,
    values: Mapping[str, str],
) -> datetime | None:
    """Read the already-integrity-verified immutable input's evidence timestamp."""

    if certification.get("all_market_certification_v2_input_integrity_valid") is not True:
        return None
    certification_id = str(certification.get("all_market_certification_v2_id") or "").strip()
    data_root = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    release = _release(values)
    if not certification_id or not data_root or release == "unknown":
        return None
    path = (
        Path(data_root).expanduser()
        / "all-market-certification-v2"
        / "inputs"
        / _safe(release)
        / f"{certification_id}.json"
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if (
        str(payload.get("record_id") or "") != certification_id
        or str(payload.get("release") or "") != release
        or str(payload.get("evidence_generation_id") or "")
        != str(certification.get("all_market_evidence_generation_id") or "")
        or str(payload.get("global_discovery_snapshot_id") or "")
        != str(certification.get("all_market_global_discovery_snapshot_id") or "")
    ):
        return None
    return _parse_datetime(payload.get("evidence_as_of"))


def _certification_context_matches(
    certification: Mapping[str, object],
    *,
    values: Mapping[str, str],
    context_decision_as_of: datetime | None,
) -> tuple[bool, bool]:
    """Prove the two intentionally different point-in-time bindings."""

    if context_decision_as_of is None:
        return False, False
    legacy_epoch = _parse_datetime(certification.get("all_market_certification_epoch"))
    evidence_as_of = _v2_evidence_as_of(certification, values=values)
    v2_cutoff = _parse_datetime(certification.get("certification_v2_cutoff"))
    return (
        legacy_epoch is not None
        and evidence_as_of is not None
        and legacy_epoch == evidence_as_of,
        v2_cutoff == context_decision_as_of,
    )


def build_cio_diagnostic_audit(
    *,
    settings: Any,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Return release, lifecycle, coverage, and integrity-proven certification state."""

    resolved = os.environ if values is None else values
    release = _release(resolved)
    certification = public_all_market_certification_readonly(resolved)
    public_requirement_progress = _safe_public_requirement_progress(resolved)
    diagnostic = latest_manual_cio_diagnostic(values=resolved)
    if diagnostic is None:
        return {
            "schema_version": "public-cio-diagnostic-audit.v3-independent-certification",
            "credential_safe": True,
            "ready": False,
            "state": "not_recorded",
            "detail": "no release-triggered CIO diagnostic has been recorded",
            "active_release": release,
            "release_matches": False,
            "paper_only": True,
            "real_money_authorized": False,
            "all_market_evaluation_complete": False,
            "all_market_certification_context_matches": False,
            "all_market_certification_v2_context_matches": False,
            "market_lanes": [],
            "public_live_requirement_progress": public_requirement_progress,
            **certification,
        }

    now = datetime.now(timezone.utc)
    context_path: Path = _state_path(settings)
    persisted_context = _load_json(context_path) or {}
    cycle_matches = bool(
        diagnostic.cycle_key
        and str(persisted_context.get("cycle_key") or "") == diagnostic.cycle_key
    )
    context: Mapping[str, Any] = persisted_context if cycle_matches else {}

    configured_scope_required = str(
        resolved.get("CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY", "")
    ).strip().lower() in {"1", "true", "yes", "on"}
    scope_required = (
        context.get("comprehensive_discovery_required") is True
        or configured_scope_required
    )
    operating_scope_state = str(
        context.get("comprehensive_discovery_scope_state") or "missing"
    )
    certification_available = bool(
        certification.get("all_market_runtime_certified") is True
        or certification.get("all_market_certification_v2_available") is True
    )
    scope_complete = (
        certification.get("all_market_comprehensive_discovery_complete") is True
    )
    certification_scope_state = (
        "complete"
        if scope_complete
        else "incomplete"
        if certification_available
        else "missing"
    )
    lanes_raw = certification.get("all_market_certified_lanes")
    lanes = tuple(
        dict(item)
        for item in lanes_raw
        if isinstance(item, Mapping)
    ) if isinstance(lanes_raw, list) else ()
    scheduled_market_coverage_complete = (
        certification.get("all_market_scheduled_market_coverage_complete") is True
    )
    terminal_screening_complete = (
        certification.get("all_market_terminal_screening_complete") is True
    )

    # Capability-scoped context counts remain useful operational telemetry, but they do
    # not impersonate the independently certified all-market universe.
    instrument_count = _count(context, "instrument_count")
    candidate_count = _count(context, "candidate_count")
    exclusion_count = _count(context, "exclusion_count")
    qualified_candidate_count = _count(context, "qualified_candidate_count")

    expected_requester = f"render-release:{release}"
    release_matches = release != "unknown" and diagnostic.requested_by == expected_requester
    diagnostic_completed = diagnostic.state == "completed"

    context_decision_as_of = _parse_datetime(context.get("decision_as_of"))
    legacy_context_matches, v2_context_matches = _certification_context_matches(
        certification,
        values=resolved,
        context_decision_as_of=context_decision_as_of,
    )
    terminal_outcome_certified = (
        certification.get("all_market_paper_implementation_certified") is True
        or certification.get("all_market_no_action_certified") is True
    )
    analytical_certification_complete = all(
        (
            certification.get("all_market_runtime_certified") is True,
            certification.get("all_market_certification_integrity_valid") is True,
            certification.get("all_market_certification_release_matches") is True,
            legacy_context_matches,
            certification.get("all_market_certification_v2_available") is True,
            certification.get("all_market_certification_v2_input_integrity_valid") is True,
            certification.get("all_market_certification_v2_state_integrity_valid") is True,
            certification.get("all_market_certification_v2_release_matches") is True,
            v2_context_matches,
            certification.get("all_market_evidence_certified") is True,
            certification.get("all_market_screening_certified") is True,
            certification.get("all_market_committee_certified") is True,
            certification.get("all_market_cio_certified") is True,
            certification.get("all_market_construction_certified") is True,
            terminal_outcome_certified,
            certification.get("all_market_operational_certified") is True,
        )
    )
    all_market_evaluation_complete = all(
        (
            diagnostic_completed,
            release_matches,
            cycle_matches,
            scope_required,
            scope_complete,
            scheduled_market_coverage_complete,
            terminal_screening_complete,
            analytical_certification_complete,
        )
    )

    attempt = _latest_context_attempt(settings)
    attempt_started = _parse_datetime(attempt.get("started_at"))
    current_attempt = bool(
        diagnostic.started_at is not None
        and attempt_started is not None
        and attempt_started >= diagnostic.started_at.astimezone(timezone.utc)
    )
    attempt_cycle = str(attempt.get("cycle_key") or "").strip() if current_attempt else ""
    progress_metrics = getattr(diagnostic, "progress_metrics", ())
    progress_recorded_at = getattr(diagnostic, "progress_recorded_at", None)

    return {
        "schema_version": "public-cio-diagnostic-audit.v3-independent-certification",
        "credential_safe": True,
        "ready": all_market_evaluation_complete,
        "state": diagnostic.state,
        "detail": diagnostic.detail,
        "active_release": release,
        "release_matches": release_matches,
        "request_id": diagnostic.request_id,
        "diagnostic_id": diagnostic.request_id,
        "requested_at": diagnostic.requested_at.isoformat(),
        "started_at": None if diagnostic.started_at is None else diagnostic.started_at.isoformat(),
        "completed_at": None if diagnostic.completed_at is None else diagnostic.completed_at.isoformat(),
        "diagnostic_age_seconds": _age_seconds(diagnostic.requested_at, now=now),
        "terminal_age_seconds": _age_seconds(diagnostic.completed_at, now=now),
        "stage": diagnostic.progress_stage,
        "progress_metrics": dict(progress_metrics),
        "progress_recorded_at": None if progress_recorded_at is None else progress_recorded_at.isoformat(),
        "cycle_key": diagnostic.cycle_key,
        "snapshot_identifier": diagnostic.snapshot_identifier,
        "context_cycle_matches": cycle_matches,
        "context_attempt_state": str(attempt.get("state") or "unknown") if current_attempt else "not_current",
        "context_attempt_cycle_matches": bool(
            attempt_cycle and diagnostic.cycle_key and attempt_cycle == diagnostic.cycle_key
        ),
        "comprehensive_discovery_required": scope_required,
        "production_context_discovery_scope_state": operating_scope_state,
        "comprehensive_discovery_scope_state": certification_scope_state,
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
        "all_market_certification_context_matches": legacy_context_matches,
        "all_market_certification_v2_context_matches": v2_context_matches,
        "market_lanes": list(lanes),
        "public_live_requirement_progress": public_requirement_progress,
        "paper_only": True,
        "real_money_authorized": False,
        **certification,
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
    """Expose live progress without using readiness HTTP status as transport state."""

    return build_cio_diagnostic_audit(settings=request.app.state.settings)


__all__ = [
    "build_cio_diagnostic_audit",
    "cio_diagnostic_status",
    "cio_diagnostic_telemetry",
    "router",
]
