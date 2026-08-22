"""Preserve credential-safe comprehensive-discovery resource context end to end.

Telemetry #712 showed that the bounded evidence worker emitted a rich, credential-safe
``ResourceBoundaryExceeded`` record, but the Render release-prequalification wrapper kept
only the generic error type, stage, and text detail. The public audit consequently lost the
lane/substage and governed memory measurements needed to repair the actual hotspot.

This compatibility bridge is observability-only. It patches the Render bootstrap's local
failure parser and prequalification writer so the already-produced safe fields survive in
the integrity-protected prequalification record. It changes no memory boundary, timeout,
market/candidate scope, evidence rule, CIO authority, construction/execution behavior, or
paper-only control.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


_EVENT = "continuous_evidence_plane_failure_context"
_INSTALLED_ATTR = "_telemetry_712_failure_context_bridge_v1"
_SAFE_STRING_FIELDS = (
    "error_type",
    "failure_stage",
    "error_detail",
    "failure_progress_kind",
    "failure_substage",
    "failure_asset_class",
    "failure_component",
    "last_durable_progress_component",
    "memory_trigger_reason",
    "memory_accounting_source",
)
_SAFE_INT_FIELDS = (
    "failure_lane_index",
    "memory_process_peak_rss_kib",
    "memory_working_set_peak_kib",
    "memory_raw_peak_kib",
    "memory_inactive_file_peak_kib",
    "memory_anon_peak_kib",
    "memory_file_peak_kib",
    "memory_kernel_peak_kib",
    "memory_working_set_boundary_kib",
    "memory_raw_hard_boundary_kib",
)
_SAFE_LANE_METRICS = frozenset(
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
_AUTHORITY_FIELDS = (
    "decision_authority",
    "candidate_authority",
    "sizing_authority",
    "construction_authority",
    "execution_authority",
)
_latest_context: dict[str, object] | None = None


def _safe_text(value: object, *, limit: int) -> str | None:
    text = str(value or "").strip()[:limit]
    return text or None


def _safe_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


def _safe_lane_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, int] = {}
    for name in _SAFE_LANE_METRICS:
        parsed = _safe_nonnegative_int(value.get(name))
        if parsed is not None:
            safe[name] = parsed
    return safe


def extract_failure_context(stderr: object) -> dict[str, object] | None:
    """Extract one explicitly non-authoritative child resource event.

    Unknown fields are discarded rather than transported. All authority flags must prove
    non-authority before the record is accepted.
    """

    if not isinstance(stderr, str) or not stderr.strip():
        return None
    for raw_line in reversed(stderr.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        if payload.get("event") != _EVENT:
            continue
        if payload.get("credential_safe") is not True:
            continue
        if payload.get("paper_only") is not True:
            continue
        if payload.get("real_money_authorized") is not False:
            continue
        if any(payload.get(field) is not False for field in _AUTHORITY_FIELDS):
            continue

        error_type = _safe_text(payload.get("error_type"), limit=120)
        detail = _safe_text(payload.get("error_detail"), limit=1600)
        if not error_type or not detail:
            continue

        safe: dict[str, object] = {
            "error_type": error_type,
            "failure_stage": _safe_text(payload.get("failure_stage"), limit=300)
            or "continuous_evidence_plane",
            "error_detail": detail,
            "credential_safe": True,
            **{field: False for field in _AUTHORITY_FIELDS},
            "paper_only": True,
            "real_money_authorized": False,
        }
        for field in _SAFE_STRING_FIELDS:
            if field in {"error_type", "failure_stage", "error_detail"}:
                continue
            value = _safe_text(payload.get(field), limit=300)
            if value is not None:
                safe[field] = value
        for field in _SAFE_INT_FIELDS:
            value = _safe_nonnegative_int(payload.get(field))
            if value is not None:
                safe[field] = value
        lane_metrics = _safe_lane_metrics(payload.get("lane_progress_metrics"))
        if lane_metrics:
            safe["lane_progress_metrics"] = lane_metrics
        return safe
    return None


def _context_matches_failure(context: Mapping[str, object], detail: object) -> bool:
    text = str(detail or "")
    error_type = str(context.get("error_type") or "")
    failure_stage = str(context.get("failure_stage") or "")
    return bool(
        error_type
        and failure_stage
        and f"child_error_type={error_type}" in text
        and f"child_stage={failure_stage}" in text
    )


def _metric_projection(context: Mapping[str, object]) -> dict[str, int]:
    metrics: dict[str, int] = {}
    for field in _SAFE_INT_FIELDS:
        value = _safe_nonnegative_int(context.get(field))
        if value is not None:
            metrics[field] = value
    lane_metrics = context.get("lane_progress_metrics")
    if isinstance(lane_metrics, Mapping):
        for name, value in _safe_lane_metrics(lane_metrics).items():
            metrics[f"lane_{name}"] = value

    progress_kind = str(context.get("failure_progress_kind") or "").strip().lower()
    if progress_kind == "active":
        metrics["failure_progress_active"] = 1
    elif progress_kind == "completed":
        metrics["failure_progress_completed"] = 1

    trigger = str(context.get("memory_trigger_reason") or "").strip().lower()
    if trigger == "working_set":
        metrics["memory_trigger_working_set"] = 1
    elif trigger == "raw_hard_ceiling":
        metrics["memory_trigger_raw_hard_ceiling"] = 1
    elif trigger:
        metrics["memory_trigger_other"] = 1
    return metrics


def _diagnostic_failure_stage(context: Mapping[str, object]) -> str:
    stage = str(context.get("failure_stage") or "").strip()[:300]
    progress_kind = str(context.get("failure_progress_kind") or "").strip().lower()
    last_durable = str(context.get("last_durable_progress_component") or "").strip()[:240]
    if progress_kind == "completed" and last_durable and ":last_durable:" not in stage:
        return f"{stage}:last_durable:{last_durable}"[:600]
    return stage or "continuous_evidence_plane"


def _persist_enriched_payload(
    payload: Mapping[str, object],
    *,
    values: Mapping[str, str],
    context: Mapping[str, object],
) -> Mapping[str, object]:
    """Rewrite only the signed operational failure record with safe extra context."""

    from operations import release_evidence_prequalification as release_state

    material = dict(payload)
    material.pop("integrity_sha256", None)
    raw_failure = material.get("failure_context")
    failure = dict(raw_failure) if isinstance(raw_failure, Mapping) else {}
    failure.update(context)
    failure["failure_stage"] = _diagnostic_failure_stage(context)
    failure.update(
        {
            "credential_safe": True,
            **{field: False for field in _AUTHORITY_FIELDS},
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    material["failure_context"] = failure

    raw_metrics = material.get("metrics")
    metrics = dict(raw_metrics) if isinstance(raw_metrics, Mapping) else {}
    metrics.update(_metric_projection(context))
    material["metrics"] = metrics

    enriched = {**material, "integrity_sha256": release_state._digest(material)}
    path = release_state._path(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(enriched, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return enriched


def install(memory_safe_module) -> None:
    """Install the telemetry #712 bridge on the Render bootstrap module."""

    global _latest_context
    if getattr(memory_safe_module, _INSTALLED_ATTR, False):
        return

    original_parser = memory_safe_module._qualifier_failure_context
    original_writer = memory_safe_module.write_release_evidence_prequalification

    def parse(stderr: object):
        global _latest_context
        context = extract_failure_context(stderr)
        _latest_context = context
        if context is None:
            return original_parser(stderr)
        return context

    def write(values: Mapping[str, str], **kwargs):
        payload = original_writer(values, **kwargs)
        context = _latest_context
        if (
            str(kwargs.get("state") or "").strip().lower() == "failed"
            and context is not None
            and _context_matches_failure(context, kwargs.get("detail"))
        ):
            return _persist_enriched_payload(payload, values=values, context=context)
        return payload

    memory_safe_module._qualifier_failure_context = parse
    memory_safe_module.write_release_evidence_prequalification = write
    setattr(memory_safe_module, _INSTALLED_ATTR, True)


__all__ = ["extract_failure_context", "install"]
