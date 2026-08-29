"""Promote credential-safe comprehensive-discovery failure detail into Render telemetry.

The production diagnostic already exposes a redacted ``detail`` string. PR #687 emits
bounded node/finalizer tokens there, but the generic Render collector does not understand
them. This read-only pass extracts only operational identifiers and non-negative counts;
it never copies symbols, holdings, recommendations, provider payloads, or credentials.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:  # Direct script execution places ``scripts`` on sys.path.
    import enrich_render_production_telemetry as _base
except ImportError:  # Test/import path from the repository root.
    from scripts import enrich_render_production_telemetry as _base


_NODE_PATTERN = re.compile(
    r"(?:^|[;\s,])node\s*[=:]\s*(deep-market-evidence:[A-Za-z0-9_.-]+)",
    flags=re.IGNORECASE,
)
_FINALIZER_PATTERN = re.compile(r"provider-free-finalizer", flags=re.IGNORECASE)
_FIELD_PATTERN = re.compile(
    r"(?:^|[;\s,])(?P<name>asset_class|failure_type|decision_eligible_count|"
    r"completed_nodes|required_nodes|reused_nodes|retry_after)\s*[=:]\s*"
    r"(?P<value>[A-Za-z0-9_.:+-]+)",
    flags=re.IGNORECASE,
)
_SAFE_FAILURE_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,119}$")
_GOVERNED_DEADLINE_FAILURE_TYPES = frozenset(
    {
        "supervisedcomponenttimeout",
        "parentstalltimeout",
        "nodestalltimeout",
        "deadline_exceeded",
        "deadlineexceeded",
    }
)
_LANE_TELEMETRY_SCHEMA = "comprehensive-discovery-lane-telemetry.v1"
_LANE_FALSE_AUTHORITY_FIELDS = (
    "evidence_certified",
    "decision_authority",
    "candidate_authority",
    "sizing_authority",
    "construction_authority",
    "execution_authority",
    "real_money_authorized",
    "watchdog_progress_authority",
)


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _detail_fields(detail: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _FIELD_PATTERN.finditer(detail):
        fields[match.group("name").lower()] = match.group("value")
    return fields


def _safe_failure_type(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _SAFE_FAILURE_TYPE.fullmatch(text) else None


def _safe_lane(value: object) -> str | None:
    return _base._safe_identifier(value)


def _safe_lane_telemetry(
    value: object,
    *,
    expected_release: str,
) -> dict[str, object] | None:
    """Accept only the producer's advisory exact-release lane telemetry envelope."""

    if not isinstance(value, Mapping):
        return None
    if value.get("schema_version") != _LANE_TELEMETRY_SCHEMA:
        return None
    if str(value.get("release") or "") != expected_release:
        return None
    if value.get("credential_safe") is not True:
        return None
    if value.get("advisory_only") is not True:
        return None
    if value.get("paper_only") is not True:
        return None
    if any(value.get(field) is not False for field in _LANE_FALSE_AUTHORITY_FIELDS):
        return None
    if not isinstance(value.get("lanes"), list):
        return None

    # ``_base._assert_safe`` has already recursively rejected forbidden keys from the
    # complete public diagnostic. Preserve the producer's validated operational shape
    # without teaching this capture layer to reinterpret timing semantics.
    return dict(value)


def _failure_reason(*, unit: str, failure_type: str | None) -> str:
    """Classify redacted scheduler failures without conflating provider timeouts.

    A provider-level ``TimeoutError`` is evidence that one lane operation failed and stays
    ``discovery_lane_failure``. Only the certification supervisor's own bounded stall/
    deadline classes are promoted to ``deadline_exceeded``.
    """

    if unit == "provider-free-finalizer":
        return "finalizer_failure"
    normalized = str(failure_type or "").strip().lower()
    if normalized in _GOVERNED_DEADLINE_FAILURE_TYPES or normalized.endswith("stalltimeout"):
        return "deadline_exceeded"
    return "discovery_lane_failure"


def discovery_progress(public_payload: Mapping[str, Any]) -> dict[str, object] | None:
    """Return only bounded operational discovery state from the public redacted detail."""

    detail = str(public_payload.get("detail") or "")[:1600]
    fields = _detail_fields(detail)
    node_match = _NODE_PATTERN.search(detail)
    finalizer = _FINALIZER_PATTERN.search(detail) is not None
    if node_match is None and not finalizer:
        return None

    blocking_unit = (
        node_match.group(1).lower() if node_match is not None else "provider-free-finalizer"
    )
    failure_type = _safe_failure_type(fields.get("failure_type"))
    asset_class = _safe_lane(fields.get("asset_class"))

    result: dict[str, object] = {
        "state": "failed",
        "blocking_unit": blocking_unit,
        "asset_class": asset_class,
        "failure_type": failure_type,
        "decision_eligible_count": _nonnegative_int(fields.get("decision_eligible_count")),
        "completed_nodes": _nonnegative_int(fields.get("completed_nodes")),
        "required_nodes": _nonnegative_int(fields.get("required_nodes")),
        "reused_nodes": _nonnegative_int(fields.get("reused_nodes")),
        "retry_after": _base._safe_identifier(fields.get("retry_after")),
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    return result


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

    updated = dict(diagnostic)
    lane_telemetry = _safe_lane_telemetry(
        public_payload.get("comprehensive_discovery_lane_telemetry"),
        expected_release=expected_release,
    )
    if lane_telemetry is not None:
        updated["comprehensive_discovery_lane_telemetry"] = lane_telemetry
        enriched["diagnostic"] = updated
        enriched["enriched_from_comprehensive_discovery_lane_telemetry"] = True

    # Lane timing is independent of the legacy failure-detail parser. Production can be
    # actively prequalifying with no legacy node/finalizer token, and the exact timing
    # envelope must still survive into the saved telemetry artifact in that case.
    progress = discovery_progress(public_payload)
    if progress is None:
        return enriched

    updated["comprehensive_discovery_progress"] = progress
    unit = str(progress.get("blocking_unit") or "")
    failure_type = _safe_failure_type(progress.get("failure_type"))
    asset_class = _safe_lane(progress.get("asset_class"))
    if unit:
        updated["prequalification_failure_unit"] = unit
    if asset_class:
        updated["prequalification_failure_asset_class"] = asset_class
    if failure_type:
        updated["prequalification_failure_type"] = failure_type
    if updated.get("prequalification_failure_reason") in {None, "internal_error"}:
        updated["prequalification_failure_reason"] = _failure_reason(
            unit=unit,
            failure_type=failure_type,
        )
    enriched["diagnostic"] = updated
    enriched["enriched_from_comprehensive_discovery"] = True
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
