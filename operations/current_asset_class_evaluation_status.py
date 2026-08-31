"""Exact-release current asset-class state for read-only presentation.

The legacy asset-class reader is intentionally retained as the validator for durable DAG,
terminal certification, and completed-snapshot artifacts. This module only changes how
those already-validated read models are composed for the UI: a partial terminal aggregate
may enrich an active certification DAG, but it may never replace nonterminal current-lane
truth with synthetic ``Awaiting evaluation`` rows.

Lane telemetry is advisory timing evidence only. It may refine the human-readable phase of
an already governed lane, but it cannot certify evidence, create candidates, change a CIO
decision, size a portfolio, or authorize execution.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from operations import asset_class_evaluation_status as validated
from operations.comprehensive_discovery_lane_telemetry import load_public_lane_telemetry


_SCHEMA_VERSION = "current-asset-class-evaluation-status.v1"


def _phase_from_telemetry(row: Mapping[str, object]) -> tuple[str, str]:
    """Project operational lane timing into a non-authoritative current phase."""

    error_type = str(row.get("error_type") or "").strip()
    if row.get("lane_failed_at"):
        detail = "Current comprehensive lane failed"
        if error_type:
            detail += f" · {error_type}"
        return "Failed", detail
    if row.get("lane_completed_at"):
        return "In progress", "Discovery lane complete · terminal evaluation pending"
    if row.get("screening_completed_at"):
        return "In progress", "Screening complete · terminal evaluation pending"
    if row.get("screening_started_at"):
        return "In progress", "Screening in progress"
    if row.get("publication_completed_at"):
        return "In progress", "Provider publication complete · screening pending"
    if row.get("publication_started_at"):
        return "In progress", "Provider publication in progress"
    if row.get("structural_completed_at"):
        suffix = " · structural cache hit" if row.get("structural_cache_hit") is True else ""
        return "In progress", f"Structural preparation complete · provider publication pending{suffix}"
    if row.get("structural_started_at"):
        return "In progress", "Structural preparation in progress"
    if row.get("lane_started_at"):
        return "In progress", "Current comprehensive lane started"
    return "In progress", "Scheduled for the current comprehensive evaluation"


def _rows_by_lane(rows: object) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    if not isinstance(rows, (list, tuple)):
        return result
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        lane = str(raw.get("key") or raw.get("asset_class") or "").strip().lower()
        if lane not in validated._GOVERNED_ASSET_CLASSES:
            continue
        result[lane] = dict(raw)
        result[lane]["key"] = lane
        result[lane].setdefault("asset_class", validated._label(lane))
    return result


def _apply_exact_telemetry(
    rows: dict[str, dict[str, object]],
    telemetry: Mapping[str, object] | None,
    *,
    release_sha: str,
    decision_epoch: object,
) -> None:
    if not isinstance(telemetry, Mapping):
        return
    if str(telemetry.get("release") or "") != release_sha:
        return
    if decision_epoch not in (None, "") and telemetry.get("decision_epoch") != decision_epoch:
        return
    raw_lanes = telemetry.get("lanes")
    if not isinstance(raw_lanes, list):
        return
    for raw in raw_lanes:
        if not isinstance(raw, Mapping):
            continue
        lane = str(raw.get("asset_class") or "").strip().lower()
        if lane not in rows:
            continue
        current = rows[lane]
        # Valid terminal DAG evidence wins over advisory timing. Telemetry refines only a
        # nonterminal current lane.
        if str(current.get("status") or "") in {"Evaluated", "Failed"}:
            continue
        status, detail = _phase_from_telemetry(raw)
        current["status"] = status
        current["detail"] = detail


def _overlay_terminal(
    rows: dict[str, dict[str, object]],
    terminal: Mapping[str, object] | None,
) -> None:
    """Overlay genuine terminal rows while ignoring terminal-reader placeholder rows."""

    if not isinstance(terminal, Mapping):
        return
    for lane, row in _rows_by_lane(terminal.get("rows")).items():
        # The validated terminal reader pads missing lanes with Awaiting evaluation to
        # preserve a 13-lane denominator. Those placeholders are not current lane truth
        # when an exact-release DAG already says the lane is active.
        if str(row.get("status") or "") == validated._AWAITING_STATUS:
            continue
        rows[lane] = row


def _with_metadata(
    summary: Mapping[str, object],
    *,
    release_sha: str | None,
    decision_epoch: object,
    exact_release: bool,
    historical: bool,
    state_origin: str,
) -> dict[str, object]:
    result = dict(summary)
    result.update(
        {
            "schema_version": _SCHEMA_VERSION,
            "release_sha": release_sha,
            "decision_epoch": decision_epoch,
            "exact_release": bool(exact_release),
            "historical": bool(historical),
            "state_origin": state_origin,
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    return result


def _current_from_attempt(
    values: Mapping[str, str],
    attempt: Mapping[str, object],
    telemetry: Mapping[str, object] | None,
) -> dict[str, object]:
    release_sha = str(attempt.get("release_sha") or "").strip()
    decision_epoch = attempt.get("decision_epoch")
    rows = _rows_by_lane(attempt.get("rows"))
    _apply_exact_telemetry(
        rows,
        telemetry,
        release_sha=release_sha,
        decision_epoch=decision_epoch,
    )
    terminal = validated._terminal_evaluation_attempt(
        values,
        release_sha=release_sha,
        decision_epoch=decision_epoch,
    )
    _overlay_terminal(rows, terminal)

    terminal_source = (
        str(terminal.get("source") or "") if isinstance(terminal, Mapping) else ""
    )
    source = (
        "Current all-market certification"
        if terminal_source == "Current all-market certification"
        else "Current all-market evaluation"
        if terminal is not None
        else "Current comprehensive evaluation attempt"
    )
    summary = validated._summary(
        list(rows.values()),
        as_of=decision_epoch,
        source=source,
    )
    return _with_metadata(
        summary,
        release_sha=release_sha or None,
        decision_epoch=decision_epoch,
        exact_release=True,
        historical=False,
        state_origin="certification_dag_with_terminal_overlay",
    )


def _current_from_telemetry(
    telemetry: Mapping[str, object],
) -> dict[str, object] | None:
    release_sha = str(telemetry.get("release") or "").strip()
    decision_epoch = telemetry.get("decision_epoch")
    raw_lanes = telemetry.get("lanes")
    if not release_sha or not isinstance(raw_lanes, list):
        return None
    rows: list[dict[str, object]] = []
    for raw in raw_lanes:
        if not isinstance(raw, Mapping):
            continue
        lane = str(raw.get("asset_class") or "").strip().lower()
        if lane not in validated._GOVERNED_ASSET_CLASSES:
            continue
        status, detail = _phase_from_telemetry(raw)
        rows.append(
            {
                "key": lane,
                "asset_class": validated._label(lane),
                "status": status,
                "detail": detail,
            }
        )
    if not rows:
        return None
    summary = validated._summary(
        rows,
        as_of=decision_epoch,
        source="Current comprehensive evaluation telemetry",
    )
    return _with_metadata(
        summary,
        release_sha=release_sha,
        decision_epoch=decision_epoch,
        exact_release=True,
        historical=False,
        state_origin="lane_telemetry",
    )


def load_current_asset_class_evaluation_status(
    *, values: Mapping[str, str] | None = None
) -> dict[str, object]:
    """Return current exact-release lane truth, falling back to history only when needed."""

    resolved = dict(os.environ if values is None else values)
    telemetry = load_public_lane_telemetry(resolved)
    attempt = validated._latest_dag_attempt(resolved)
    if isinstance(attempt, Mapping):
        return _current_from_attempt(resolved, attempt, telemetry)

    telemetry_summary = (
        _current_from_telemetry(telemetry) if isinstance(telemetry, Mapping) else None
    )
    if telemetry_summary is not None:
        return telemetry_summary

    release_sha = validated._release(resolved)
    if release_sha and release_sha != "unknown":
        terminal = validated._terminal_evaluation_attempt(resolved, release_sha=release_sha)
        if terminal is not None:
            return _with_metadata(
                terminal,
                release_sha=release_sha,
                decision_epoch=terminal.get("as_of"),
                exact_release=True,
                historical=False,
                state_origin="terminal_aggregate_without_active_dag",
            )

    completed = validated._latest_completed_snapshot(resolved)
    if completed is not None:
        return _with_metadata(
            completed,
            release_sha=None,
            decision_epoch=completed.get("as_of"),
            exact_release=False,
            historical=True,
            state_origin="latest_completed_global_evaluation",
        )

    empty = validated._summary(
        [],
        as_of=None,
        source="No comprehensive asset-class evaluation recorded yet",
    )
    return _with_metadata(
        empty,
        release_sha=None,
        decision_epoch=None,
        exact_release=False,
        historical=False,
        state_origin="unavailable",
    )


def load_latest_completed_asset_class_evaluation(
    *, values: Mapping[str, str] | None = None
) -> dict[str, object] | None:
    """Return the completed historical evaluation separately from current production state."""

    resolved = dict(os.environ if values is None else values)
    completed = validated._latest_completed_snapshot(resolved)
    if completed is None:
        return None
    return _with_metadata(
        completed,
        release_sha=None,
        decision_epoch=completed.get("as_of"),
        exact_release=False,
        historical=True,
        state_origin="latest_completed_global_evaluation",
    )


__all__ = [
    "load_current_asset_class_evaluation_status",
    "load_latest_completed_asset_class_evaluation",
]
