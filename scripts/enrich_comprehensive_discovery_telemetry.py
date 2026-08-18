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

    progress = discovery_progress(public_payload)
    if progress is None:
        return enriched

    updated = dict(diagnostic)
    updated["comprehensive_discovery_progress"] = progress
    unit = str(progress.get("blocking_unit") or "")
    if unit:
        updated["prequalification_failure_unit"] = unit
    if updated.get("prequalification_failure_reason") in {None, "internal_error"}:
        updated["prequalification_failure_reason"] = (
            "finalizer_failure"
            if unit == "provider-free-finalizer"
            else "discovery_lane_failure"
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
