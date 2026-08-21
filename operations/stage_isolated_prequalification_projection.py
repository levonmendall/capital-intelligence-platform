"""Credential-safe projection of the exact stage-isolated evidence attempt.

Release telemetry previously inferred an active phase from legacy reference/public progress.
That inference is incomplete once evidence preparation is split into six durable stages and
can incorrectly report ``public_live`` while U.S.-equity discovery, comprehensive discovery,
paper evidence, or finalization is actually running. This module projects the authoritative
coordination journal and the newest archived failed attempt without granting either artifact
investment or evidence authority.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from operations import stage_isolated_evidence_pipeline as _pipeline


_SAFE_STAGES = frozenset(_pipeline._STAGES)


def _safe_text(value: object, *, limit: int) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def _state_progress(state: _pipeline.StageIsolatedEvidenceState) -> dict[str, object]:
    current = state.current_stage
    next_stage = state.next_stage
    active = current or next_stage or ("complete" if state.state == "completed" else None)
    return {
        "pipeline_id": state.pipeline_id,
        "state": state.state,
        "evidence_as_of": state.evidence_as_of.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "current_stage": current,
        "next_stage": next_stage,
        "active_stage": active,
        "stage_started_at": (
            None if state.stage_started_at is None else state.stage_started_at.isoformat()
        ),
        "completed_stages": list(state.completed_stages),
        "completed_stage_count": len(state.completed_stages),
        "required_stage_count": len(_pipeline._STAGES),
        "error_type": _safe_text(state.error_type, limit=160),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _latest_failed_attempt(
    values: Mapping[str, str],
    current: _pipeline.StageIsolatedEvidenceState | None,
) -> dict[str, object] | None:
    if current is not None:
        attempts = current.path.parent / "attempts"
    else:
        try:
            attempts = _pipeline._path(values).parent / "attempts"
        except (OSError, TypeError, ValueError, RuntimeError):
            return None
    try:
        paths = tuple(attempts.glob("*.json"))
    except OSError:
        return None

    newest: tuple[datetime, _pipeline.StageIsolatedEvidenceState] | None = None
    for path in paths:
        try:
            payload = _pipeline._validated_payload(path)
            if payload is None:
                continue
            state = _pipeline._state_from_payload(path, payload)
        except (OSError, TypeError, ValueError, RuntimeError):
            continue
        if state.release != _pipeline._release(values) or state.state != "failed":
            continue
        if newest is None or state.updated_at > newest[0]:
            newest = (state.updated_at, state)
    if newest is None:
        return None

    state = newest[1]
    stage = state.current_stage or state.next_stage
    if stage not in _SAFE_STAGES:
        stage = None
    # Never publish the archived error detail. Stage + error class are sufficient for
    # diagnosis and cannot expose provider payload fragments, symbols, or credentials.
    return {
        "pipeline_id": state.pipeline_id,
        "failed_stage": stage,
        "error_type": _safe_text(state.error_type, limit=160),
        "evidence_as_of": state.evidence_as_of.isoformat(),
        "updated_at": state.updated_at.isoformat(),
        "completed_stages": list(state.completed_stages),
        "completed_stage_count": len(state.completed_stages),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def project_stage_isolated_prequalification(
    payload: Mapping[str, object],
    *,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Overlay exact operational stage truth onto an already credential-safe audit."""

    resolved = dict(os.environ if values is None else values)
    published = dict(payload)
    if str(published.get("request_kind") or "") != "evidence_prequalification":
        return published
    if str(published.get("active_release") or "") != _pipeline._release(resolved):
        return published

    try:
        current = _pipeline.load_stage_isolated_evidence_state(resolved)
    except (OSError, TypeError, ValueError, RuntimeError):
        current = None
    if current is not None:
        progress = _state_progress(current)
        published["stage_isolated_evidence_progress"] = progress
        existing = published.get("prequalification_progress")
        prequalification = dict(existing) if isinstance(existing, Mapping) else {}
        prequalification["active_phase"] = progress.get("active_stage") or "unknown"
        prequalification["stage_isolated"] = progress
        published["prequalification_progress"] = prequalification

    failed = _latest_failed_attempt(resolved, current)
    if failed is not None:
        published["prequalification_last_retry_failure"] = failed
        published["prequalification_last_retry_failure_stage"] = failed.get("failed_stage")
        published["prequalification_last_retry_failure_error_type"] = failed.get("error_type")

    published["credential_safe"] = True
    published["paper_only"] = True
    published["real_money_authorized"] = False
    return published


__all__ = ["project_stage_isolated_prequalification"]
