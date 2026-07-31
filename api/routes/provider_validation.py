"""Credential-safe live provider validation status route."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Response, status

from operations.provider_validation import load_provider_validation_report

router = APIRouter(tags=["operations"])


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


@router.get(
    "/v1/operations/provider-validation",
    responses={503: {"description": "Required provider validation is absent or failed"}},
)
def provider_validation_status(response: Response) -> dict[str, object]:
    payload = load_provider_validation_report()
    release = (
        os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown"
    ).strip()
    maximum_age_hours = int(
        os.getenv("CAPITAL_INTELLIGENCE_PROVIDER_VALIDATION_MAX_AGE_HOURS", "24")
    )
    now = datetime.now(timezone.utc)
    if payload is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "ready": False,
            "state": "missing",
            "detail": "no credential-safe live provider validation report is available",
            "release": release,
            "real_money_authorized": False,
        }
    generated_at = _timestamp(payload.get("generated_at"))
    fresh = (
        generated_at is not None
        and generated_at >= now - timedelta(hours=max(1, maximum_age_hours))
        and generated_at <= now + timedelta(minutes=2)
    )
    report_release = str(payload.get("release") or "unknown").strip()
    release_matches = release == "unknown" or report_release == release
    report_ready = payload.get("ready") is True
    ready = report_ready and fresh and release_matches
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    detail_parts: list[str] = []
    if not report_ready:
        detail_parts.append("one or more required provider checks failed")
    if not fresh:
        detail_parts.append("the provider report is stale or has an invalid timestamp")
    if not release_matches:
        detail_parts.append("the provider report belongs to a different release")
    if not detail_parts:
        detail_parts.append("required live providers were validated for the active release")
    return {
        **payload,
        "ready": ready,
        "state": "ready" if ready else "blocked",
        "detail": "; ".join(detail_parts),
        "active_release": release,
        "report_release": report_release,
        "fresh": fresh,
        "release_matches": release_matches,
        "real_money_authorized": False,
    }


__all__ = ["router", "provider_validation_status"]
