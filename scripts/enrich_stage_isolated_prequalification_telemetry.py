"""Promote exact stage-isolated evidence progress into Render telemetry.

This read-only enrichment consumes only the already-public credential-safe audit. It copies
operational stage names, timestamps, counts, and sanitized failure classifications; it never
copies market symbols, holdings, recommendations, provider payloads, or credentials.
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

    enriched["diagnostic"] = updated
    enriched["enriched_from_stage_isolated_prequalification"] = progress is not None
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
