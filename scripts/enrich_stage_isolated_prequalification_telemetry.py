"""Promote exact stage-isolated evidence progress into Render telemetry.

This read-only enrichment consumes only the already-public credential-safe audit. It copies
operational stage names, timestamps, counts, and sanitized failure classifications; it never
copies market symbols, holdings, recommendations, provider payloads, or credentials.

Telemetry #716 also proved that the generic telemetry collector's historical progress-metric
allowlist can discard newly governed memory/lane diagnostics. This final enrichment step
therefore copies only the explicit non-authoritative resource fields emitted by the signed
release-prequalification record.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:
    import enrich_render_production_telemetry as _base
except ImportError:
    from scripts import enrich_render_production_telemetry as _base


_ALLOWED_STAGES = frozenset(
    {
        "reference",
        "public_live",
        "us_equity_discovery",
        "comprehensive_discovery",
        "paper_evidence",
        "finalize",
        "complete",
    }
)
_RESOURCE_CONTEXT_KEYS = (
    "failure_progress_kind",
    "failure_substage",
    "failure_asset_class",
    "failure_component",
    "last_durable_progress_component",
    "memory_trigger_reason",
    "memory_accounting_source",
    "memory_reclaim_error_type",
)
_RESOURCE_BOOL_KEYS = (
    "memory_reclaim_attempted",
    "memory_reclaim_supported",
    "memory_reclaim_effective",
    "memory_reclaim_ever_effective",
)
_RESOURCE_METRIC_KEYS = (
    "failure_lane_index",
    "failure_progress_active",
    "failure_progress_completed",
    "memory_process_peak_rss_kib",
    "memory_working_set_peak_kib",
    "memory_raw_peak_kib",
    "memory_inactive_file_peak_kib",
    "memory_anon_peak_kib",
    "memory_file_peak_kib",
    "memory_kernel_peak_kib",
    "memory_working_set_boundary_kib",
    "memory_raw_hard_boundary_kib",
    "memory_trigger_working_set",
    "memory_trigger_raw_hard_ceiling",
    "memory_trigger_other",
    "memory_reclaim_requested_kib",
    "memory_reclaim_raw_before_kib",
    "memory_reclaim_raw_after_kib",
    "memory_reclaim_working_set_before_kib",
    "memory_reclaim_working_set_after_kib",
    "memory_reclaim_delta_kib",
    "memory_reclaim_reclaimed_kib",
    "memory_reclaim_attempt_count",
    "memory_reclaim_success_count",
    "memory_reclaim_max_attempts",
    # Keep the terminal exporter contract aligned with the exact credential-safe numeric
    # attribution emitted by comprehensive_discovery_memory_attribution. These values are
    # advisory-only resource accounting; paths, provider payloads, symbols, and arbitrary
    # free-form details remain outside the allowlist.
    "memory_raw_current_kib",
    "memory_working_set_current_kib",
    "memory_cgroup_anon_kib",
    "memory_cgroup_file_kib",
    "memory_cgroup_shmem_kib",
    "memory_cgroup_file_mapped_kib",
    "memory_cgroup_file_dirty_kib",
    "memory_cgroup_file_writeback_kib",
    "memory_cgroup_inactive_file_kib",
    "memory_cgroup_active_file_kib",
    "memory_cgroup_kernel_kib",
    "memory_cgroup_sock_kib",
    "memory_cgroup_pagetables_kib",
    "memory_cgroup_slab_reclaimable_kib",
    "memory_cgroup_slab_unreclaimable_kib",
    "memory_cgroup_file_unmapped_kib",
    "memory_store_data_total_kib",
    "memory_store_data_file_count",
    "memory_store_historical_kib",
    "memory_store_historical_file_count",
    "memory_store_historical_sqlite_kib",
    "memory_store_historical_wal_kib",
    "memory_store_historical_shm_kib",
    "memory_store_discovery_spool_kib",
    "memory_store_discovery_spool_file_count",
    "memory_store_reference_kib",
    "memory_store_reference_file_count",
    "memory_store_continuous_evidence_kib",
    "memory_store_continuous_evidence_file_count",
    "memory_store_other_kib",
    "memory_store_other_file_count",
    "memory_store_scan_truncated",
    "memory_store_scan_entries",
    "lane_active_lane_index",
    "lane_candidate_lanes",
    "lane_completed_catalog_lanes",
    "lane_completed_publication_lanes",
    "lane_completed_screening_lanes",
    "lane_scheduled_lanes",
    "lane_catalog_records",
    "lane_decision_eligible_records",
    "lane_peak_rss_bytes",
    "lane_bounded_provider_publication",
)
_AUTHORITY_FIELDS = (
    "decision_authority",
    "candidate_authority",
    "sizing_authority",
    "construction_authority",
    "execution_authority",
)


def _safe_stage(value: object) -> str | None:
    stage = _base._safe_identifier(value)
    return stage if stage in _ALLOWED_STAGES else None


def _safe_timestamp(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 64:
        return None
    if not all(character.isdigit() or character in {"-", ":", ".", "+", "T", "Z"} for character in text):
        return None
    return text


def _safe_stage_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [stage for item in value if (stage := _safe_stage(item)) not in {None, "complete"}]


def _safe_progress(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    completed = _safe_stage_list(value.get("completed_stages"))
    completed_count = _base._nonnegative_int(value.get("completed_stage_count"))
    required_count = _base._nonnegative_int(value.get("required_stage_count"))
    return {
        "pipeline_id": _base._safe_identifier(value.get("pipeline_id")),
        "state": _base._safe_identifier(value.get("state")),
        "evidence_as_of": _safe_timestamp(value.get("evidence_as_of")),
        "updated_at": _safe_timestamp(value.get("updated_at")),
        "current_stage": _safe_stage(value.get("current_stage")),
        "next_stage": _safe_stage(value.get("next_stage")),
        "active_stage": _safe_stage(value.get("active_stage")),
        "stage_started_at": _safe_timestamp(value.get("stage_started_at")),
        "completed_stages": completed,
        "completed_stage_count": completed_count if completed_count is not None else len(completed),
        "required_stage_count": required_count if required_count is not None else 6,
        "error_type": _base._safe_identifier(value.get("error_type")),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _safe_retry_failure(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    completed = _safe_stage_list(value.get("completed_stages"))
    completed_count = _base._nonnegative_int(value.get("completed_stage_count"))
    return {
        "pipeline_id": _base._safe_identifier(value.get("pipeline_id")),
        "failed_stage": _safe_stage(value.get("failed_stage")),
        "error_type": _base._safe_identifier(value.get("error_type")),
        "evidence_as_of": _safe_timestamp(value.get("evidence_as_of")),
        "updated_at": _safe_timestamp(value.get("updated_at")),
        "completed_stages": completed,
        "completed_stage_count": completed_count if completed_count is not None else len(completed),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _safe_resource_failure_context(value: object) -> dict[str, object] | None:
    """Return only explicitly non-authoritative resource-failure identifiers."""

    if not isinstance(value, Mapping):
        return None
    if value.get("credential_safe") is not True:
        return None
    if value.get("paper_only") is not True or value.get("real_money_authorized") is not False:
        return None
    if any(value.get(field) is not False for field in _AUTHORITY_FIELDS):
        return None

    safe: dict[str, object] = {
        "credential_safe": True,
        **{field: False for field in _AUTHORITY_FIELDS},
        "paper_only": True,
        "real_money_authorized": False,
    }
    for key in _RESOURCE_CONTEXT_KEYS:
        parsed = _base._safe_identifier(value.get(key))
        if parsed is not None:
            safe[key] = parsed
    for key in _RESOURCE_BOOL_KEYS:
        raw = value.get(key)
        if isinstance(raw, bool):
            safe[key] = raw
    lane_index = _base._nonnegative_int(value.get("failure_lane_index"))
    if lane_index is not None:
        safe["failure_lane_index"] = lane_index
    for key in _RESOURCE_METRIC_KEYS:
        parsed = _base._nonnegative_int(value.get(key))
        if parsed is not None:
            safe[key] = parsed
    return safe


def _safe_resource_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, int] = {}
    for key in _RESOURCE_METRIC_KEYS:
        parsed = _base._nonnegative_int(value.get(key))
        if parsed is not None:
            safe[key] = parsed
    return safe


def enrich_snapshot(
    snapshot: Mapping[str, Any],
    public_payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> dict[str, object]:
    _base._assert_safe(public_payload)
    enriched = dict(snapshot)
    diagnostic = enriched.get("diagnostic")
    if not isinstance(diagnostic, Mapping):
        return enriched
    if str(public_payload.get("active_release") or "") != expected_release:
        return enriched
    if diagnostic.get("release_matches_expected") is not True:
        return enriched

    updated = dict(diagnostic)
    progress = _safe_progress(public_payload.get("stage_isolated_evidence_progress"))
    if progress is not None:
        updated["stage_isolated_evidence_progress"] = progress
        active_stage = progress.get("active_stage")
        existing = updated.get("prequalification_progress")
        prequalification = dict(existing) if isinstance(existing, Mapping) else {}
        prequalification["active_phase"] = active_stage or "unknown"
        prequalification["stage_isolated"] = progress
        updated["prequalification_progress"] = prequalification

    retry_failure = _safe_retry_failure(
        public_payload.get("prequalification_last_retry_failure")
    )
    if retry_failure is not None:
        updated["prequalification_last_retry_failure"] = retry_failure
        failed_stage = retry_failure.get("failed_stage")
        error_type = retry_failure.get("error_type")
        if failed_stage is not None:
            updated["prequalification_last_retry_failure_stage"] = failed_stage
        if error_type is not None:
            updated["prequalification_last_retry_failure_error_type"] = error_type

    resource_context = _safe_resource_failure_context(
        public_payload.get("prequalification_failure_context")
    )
    if resource_context is not None:
        updated["prequalification_resource_failure_context"] = resource_context
        for key in _RESOURCE_CONTEXT_KEYS:
            value = resource_context.get(key)
            if value is not None:
                updated[f"prequalification_{key}"] = value
        lane_index = resource_context.get("failure_lane_index")
        if lane_index is not None:
            updated["prequalification_failure_lane_index"] = lane_index

    metrics = dict(updated.get("progress_metrics") or {})
    metrics.update(_safe_resource_metrics(public_payload.get("progress_metrics")))
    updated["progress_metrics"] = metrics

    enriched["diagnostic"] = updated
    enriched["enriched_from_stage_isolated_prequalification"] = progress is not None
    enriched["enriched_from_resource_failure_context"] = bool(
        resource_context is not None or _safe_resource_metrics(public_payload.get("progress_metrics"))
    )
    return enriched


def _write(path: Path, payload: object) -> None:
    _base._write_json(path, payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeline-output", type=Path)
    args = parser.parse_args(argv)

    snapshot = json.loads(args.output.read_text(encoding="utf-8"))
    if not isinstance(snapshot, Mapping):
        raise SystemExit("telemetry output must encode a JSON object")
    public_payload = _base._fetch_json(args.url)
    enriched = enrich_snapshot(
        snapshot,
        public_payload,
        expected_release=args.expected_release,
    )
    _write(args.output, enriched)

    if args.timeline_output is not None and args.timeline_output.exists():
        timeline = json.loads(args.timeline_output.read_text(encoding="utf-8"))
        if isinstance(timeline, list) and timeline:
            timeline[-1] = enriched
            _write(args.timeline_output, timeline)
    print(json.dumps(enriched, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
