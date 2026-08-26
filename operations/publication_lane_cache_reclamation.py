"""Reclaim completed publication-lane clean cache without spawning another interpreter.

The stage-isolated reference boundary can afford a disposable reclaimer interpreter because
its coordinator is deliberately lightweight. Comprehensive discovery is different: its
parent already carries the discovery runtime working set, so starting another interpreter
at a high raw-cgroup watermark can add pressure before useful cache advice begins.

This module therefore invokes the same bounded data-root clean-cache reclaimer directly in
the existing serialized publication-lane coordinator after a child has exited and its
durable transaction state has been validated. Publication transactions are intrinsically
serial at this call site, so the helper must not depend on the later provider-facing DAG
worker override being present in the incoming environment. The returned ownership report
is accepted only when the same non-authoritative contract used by the reference boundary is
intact. Reclamation remains advisory and fail-soft and cannot certify evidence or alter any
memory, provider, market, CIO, construction, execution, or paper-only control.
"""

from __future__ import annotations

import json
from collections.abc import Mapping


_EVENT = "comprehensive_discovery_publication_lane_cache_reclamation"
_REPORT_SCHEMA = "pre-comprehensive-cache-reclamation.v1"

_AUTHORITY_CONTRACT = {
    "advisory_only": True,
    "evidence_certified": False,
    "decision_authority": False,
    "candidate_authority": False,
    "sizing_authority": False,
    "construction_authority": False,
    "execution_authority": False,
    "paper_only": True,
    "real_money_authorized": False,
    "credential_safe": True,
}


def _enabled(values: Mapping[str, str]) -> bool:
    # This wrapper is called only by the transactional publication coordinator, whose lane
    # loop is strictly serial independent of the later provider-facing DAG worker count.
    # Requiring that later scheduler override here can silently skip the exact boundary we
    # need to protect. Keep only the production-platform guard.
    return str(values.get("RENDER") or "").strip().lower() == "true"


def _validated_report(report: object) -> dict[str, object] | None:
    if not isinstance(report, Mapping):
        return None
    normalized = dict(report)
    if normalized.get("schema_version") != _REPORT_SCHEMA:
        return None
    if any(normalized.get(key) is not value for key, value in _AUTHORITY_CONTRACT.items()):
        return None
    return normalized


def run_publication_lane_cache_reclamation(
    values: Mapping[str, str],
    *,
    asset_class: str,
    index: int,
) -> dict[str, object]:
    """Run the bounded clean-cache helper in-process at one completed lane handoff."""

    status = "skipped"
    error_type: str | None = None
    report: dict[str, object] | None = None

    if _enabled(values):
        try:
            from operations.pre_comprehensive_cache_reclamation import (
                release_pre_comprehensive_completed_stage_file_cache,
            )

            report = _validated_report(
                release_pre_comprehensive_completed_stage_file_cache(values)
            )
            if report is None:
                status = "invalid_report"
                error_type = "CacheReclamationReportError"
            else:
                status = "completed"
        except Exception:  # noqa: BLE001 - cache hygiene is deliberately fail-soft.
            status = "failed"
            error_type = "CacheReclamationError"

    payload: dict[str, object] = {
        "event": _EVENT,
        "asset_class": str(asset_class)[:96],
        "lane_index": int(index),
        "status": status,
        "error_type": error_type,
        **_AUTHORITY_CONTRACT,
    }
    if report is not None:
        payload["cache_ownership"] = report
        for key in (
            "candidate_file_count",
            "candidate_bytes",
            "selected_file_count",
            "selected_bytes",
            "released_file_count",
            "released_bytes",
            "scan_truncated",
            "manifest_truncated",
            "raw_current_reclaimed_kib",
            "inactive_file_reclaimed_kib",
        ):
            payload[key] = report.get(key)

    print(json.dumps(payload, sort_keys=True), flush=True)
    return payload


__all__ = ["run_publication_lane_cache_reclamation"]
