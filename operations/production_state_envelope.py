"""Canonical read-only production state for the Portfolio Command Center.

The command center previously sampled operating health, asset-class evaluation, and
certification independently. Each source could be individually valid while describing a
different release or decision epoch. This envelope composes the same durable sources used
by production diagnostics into one presentation contract and records alignment explicitly.

It has no provider, evidence-certification, candidate, CIO, construction, sizing, paper
execution, or live-money authority.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from operations.all_market_certification_envelope import (
    load_all_market_certification_envelope,
)
from operations.comprehensive_discovery_lane_telemetry import load_public_lane_telemetry
from operations.current_asset_class_evaluation_status import (
    load_current_asset_class_evaluation_status,
    load_latest_completed_asset_class_evaluation,
)
from operations.manual_cio_diagnostic import latest_manual_cio_diagnostic


_SCHEMA_VERSION = "production-state-envelope.v1"


def _release(values: Mapping[str, str]) -> str:
    return str(
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _iso(value: object) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _production_status(
    values: Mapping[str, str],
    *,
    observed_at: datetime,
) -> dict[str, object]:
    release = _release(values)
    diagnostic = latest_manual_cio_diagnostic(values=values)
    if diagnostic is None:
        return {
            "state": "not_recorded",
            "stage": None,
            "detail": "No exact-release production diagnostic has been recorded yet.",
            "request_id": None,
            "cycle_key": None,
            "started_at": None,
            "completed_at": None,
            "progress_recorded_at": None,
            "release_matches": False,
            "observed_at": observed_at.isoformat(),
        }

    expected_requester = f"render-release:{release}"
    release_matches = release != "unknown" and diagnostic.requested_by == expected_requester
    if not release_matches:
        return {
            "state": "stale_release",
            "stage": None,
            "detail": "The latest durable diagnostic belongs to a different release.",
            "request_id": diagnostic.request_id,
            "cycle_key": diagnostic.cycle_key,
            "started_at": _iso(diagnostic.started_at),
            "completed_at": _iso(diagnostic.completed_at),
            "progress_recorded_at": _iso(getattr(diagnostic, "progress_recorded_at", None)),
            "release_matches": False,
            "observed_at": observed_at.isoformat(),
        }

    stage = str(getattr(diagnostic, "progress_stage", None) or "").strip() or None
    detail = str(getattr(diagnostic, "detail", None) or "").strip()
    if not detail:
        detail = "Exact-release production diagnostic is active." if diagnostic.state in {"pending", "in_progress"} else "Exact-release production diagnostic state recorded."
    return {
        "state": str(diagnostic.state),
        "stage": stage,
        "detail": detail,
        "request_id": diagnostic.request_id,
        "cycle_key": diagnostic.cycle_key,
        "started_at": _iso(diagnostic.started_at),
        "completed_at": _iso(diagnostic.completed_at),
        "progress_recorded_at": _iso(getattr(diagnostic, "progress_recorded_at", None)),
        "release_matches": True,
        "observed_at": observed_at.isoformat(),
    }


def _alignment(
    *,
    release: str,
    current: Mapping[str, object],
    telemetry: Mapping[str, object] | None,
    certification: Mapping[str, object],
    production: Mapping[str, object],
) -> dict[str, object]:
    current_exact = current.get("exact_release") is True and current.get("historical") is not True
    asset_release_matches = bool(
        current_exact and str(current.get("release_sha") or "") == release
    )
    telemetry_release_matches = bool(
        isinstance(telemetry, Mapping)
        and str(telemetry.get("release") or "") == release
    )
    certification_release_matches = bool(
        str(certification.get("release_sha") or "") == release and release != "unknown"
    )

    asset_epoch = str(current.get("decision_epoch") or "").strip()
    telemetry_epoch = (
        str(telemetry.get("decision_epoch") or "").strip()
        if isinstance(telemetry, Mapping)
        else ""
    )
    epoch_matches = bool(
        asset_epoch
        and telemetry_epoch
        and asset_epoch == telemetry_epoch
    )
    # Telemetry is optional after a terminal aggregate has been published. Do not make a
    # missing advisory timing file invalidate otherwise exact current evaluation truth.
    current_epoch_coherent = bool(
        asset_release_matches
        and (
            not isinstance(telemetry, Mapping)
            or (telemetry_release_matches and (not asset_epoch or not telemetry_epoch or epoch_matches))
        )
    )
    return {
        "asset_release_matches": asset_release_matches,
        "diagnostic_release_matches": production.get("release_matches") is True,
        "telemetry_release_matches": telemetry_release_matches,
        "certification_release_matches": certification_release_matches,
        "asset_telemetry_decision_epoch_matches": epoch_matches,
        "current_asset_state_exact_release": current_exact,
        "current_asset_state_coherent": current_epoch_coherent,
    }


def load_production_state_envelope(
    *,
    values: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read one current production-state projection for all command-center surfaces."""

    resolved = dict(os.environ if values is None else values)
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    release = _release(resolved)

    try:
        current = load_current_asset_class_evaluation_status(values=resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        current = {
            "schema_version": "current-asset-class-evaluation-status.v1",
            "successful": 0,
            "attempted": 0,
            "total": 0,
            "reached": 0,
            "as_of": None,
            "source": "Current exact-release asset-class state unavailable",
            "rows": [],
            "release_sha": None,
            "decision_epoch": None,
            "exact_release": False,
            "historical": False,
            "state_origin": "unavailable",
            "paper_only": True,
            "real_money_authorized": False,
        }
    try:
        previous = load_latest_completed_asset_class_evaluation(values=resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        previous = None
    try:
        telemetry = load_public_lane_telemetry(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        telemetry = None
    try:
        certification = load_all_market_certification_envelope(values=resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        certification = {
            "schema_version": "all-market-certification-envelope.v1",
            "certified": False,
            "blocker": "certification_state_unavailable",
            "release_sha": release,
            "coverage": {"certified_count": 0, "represented_count": 0, "required_count": 13, "complete": False},
            "paper_only": True,
            "real_money_authorized": False,
        }
    production = _production_status(resolved, observed_at=observed_at)
    alignment = _alignment(
        release=release,
        current=current,
        telemetry=telemetry,
        certification=certification,
        production=production,
    )

    return {
        "schema_version": _SCHEMA_VERSION,
        "release_sha": release,
        "decision_epoch": current.get("decision_epoch"),
        "observed_at": observed_at.isoformat(),
        "production": production,
        "asset_class_evaluation": current,
        "previous_completed_asset_class_evaluation": previous,
        "certification": certification,
        "lane_telemetry": telemetry,
        "alignment": alignment,
        "paper_only": True,
        "real_money_authorized": False,
        "decision_authority": False,
        "construction_authority": False,
        "execution_authority": False,
    }


__all__ = ["load_production_state_envelope"]
