"""Presentation adapter for last-successful opportunity scans and refresh attempts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

import operating_intelligence_ui as operating_ui
from production_context_state_resilience import latest_attempt

_ORIGINAL_LOADER = None


def _clean(value: object, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _attempt_time(payload: Mapping[str, Any]) -> datetime | None:
    return _parse_datetime(payload.get("completed_at")) or _parse_datetime(
        payload.get("started_at")
    )


def _attempt_is_relevant(snapshot: object, payload: Mapping[str, Any]) -> bool:
    attempt_at = _attempt_time(payload)
    scan_at = getattr(snapshot, "as_of", None)
    if attempt_at is None or not isinstance(scan_at, datetime):
        return True
    if scan_at.tzinfo is None or scan_at.utcoffset() is None:
        return True
    return attempt_at >= scan_at.astimezone(timezone.utc)


def _decorate_snapshot(snapshot: object) -> object:
    settings = operating_ui._runtime_settings()
    if settings is None:
        return snapshot
    payload = latest_attempt(settings)
    if not isinstance(payload, Mapping) or not _attempt_is_relevant(snapshot, payload):
        return snapshot

    state = _clean(payload.get("state"), 40).lower()
    if state not in {"running", "blocked", "failed"}:
        return snapshot

    scan_at = getattr(snapshot, "as_of", None)
    existing_detail = _clean(getattr(snapshot, "detail", ""))
    attempt_detail = _clean(payload.get("detail")) or "No additional failure detail was recorded."
    has_success = isinstance(scan_at, datetime)

    if state == "running":
        status = (
            "A new governed opportunity scan is in progress. "
            "The last successful scan remains visible until a complete replacement is published."
        )
    else:
        status = f"Latest governed opportunity-scan refresh did not complete: {attempt_detail}"

    if has_success:
        detail = (
            f"{status} Showing the last successful scan from "
            f"{scan_at.astimezone(timezone.utc).strftime('%b %d, %Y · %H:%M UTC')}. "
            "No counts were erased, replaced with zeros, or fabricated."
        )
        if existing_detail:
            detail += f" {existing_detail}"
        return replace(snapshot, state="stale" if state != "running" else "refreshing", detail=detail)

    detail = (
        f"{status} No prior successful production scan is available, so governed counts "
        "remain unavailable rather than being inferred."
    )
    return replace(
        snapshot,
        state=state,
        strongest_stage=(
            "First governed scan is in progress"
            if state == "running"
            else "Latest governed scan was blocked before publication"
        ),
        main_reason=(
            "The first governed opportunity scan is still in progress."
            if state == "running"
            else f"Latest scan did not complete: {attempt_detail}"
        ),
        decision_reference=_clean(payload.get("cycle_key"), 240) or getattr(snapshot, "decision_reference", "Unavailable"),
        detail=detail,
    )


def install() -> None:
    """Install the adapter once for both concise and full operating surfaces."""

    global _ORIGINAL_LOADER
    if getattr(operating_ui.load_opportunity_scan, "_preserves_last_successful_scan", False):
        return
    _ORIGINAL_LOADER = operating_ui.load_opportunity_scan

    def resilient_loader():
        return _decorate_snapshot(_ORIGINAL_LOADER())

    resilient_loader._preserves_last_successful_scan = True  # type: ignore[attr-defined]
    operating_ui.load_opportunity_scan = resilient_loader


__all__ = ["install"]
