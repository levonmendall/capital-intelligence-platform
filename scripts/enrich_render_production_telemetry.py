"""Enrich the final Render telemetry artifact with credential-safe failure evidence.

This helper is intentionally read-only. It re-reads the public redacted CIO diagnostic
surface after the primary telemetry watcher stops, validates the safety envelope, and
copies only explicitly allowlisted prequalification state plus the sanitized futures
reference certification DAG emitted by the governed reference adapter.
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_FORBIDDEN_KEYS = frozenset(
    {
        "holdings",
        "positions",
        "target_weights",
        "candidate_symbols",
        "recommendations",
        "provider_payloads",
        "provider_records",
        "api_key",
        "api_token",
        "access_token",
        "authorization",
        "cookie",
        "password",
        "secret",
    }
)
_REFERENCE_METRIC_KEYS = (
    "configured_exchanges",
    "configured_futures_roots",
    "catalog_records",
    "reused",
)
_FUTURES_ROW_KEYS = (
    "root",
    "status",
    "raw",
    "parsed",
    "matched",
    "valid",
    "usable",
    "reason",
)
_FUTURES_TELEMETRY_TOKEN = "massive_futures_telemetry="


def _walk_keys(value: object) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key).strip().lower())
            keys.extend(_walk_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            keys.extend(_walk_keys(item))
    return tuple(keys)


def _assert_safe(payload: Mapping[str, Any]) -> None:
    if _FORBIDDEN_KEYS.intersection(_walk_keys(payload)):
        raise ValueError("public diagnostic contains forbidden fields")
    if payload.get("credential_safe") is not True:
        raise ValueError("public diagnostic is not credential-safe")
    if payload.get("paper_only") is not True:
        raise ValueError("public diagnostic is not paper-only")
    if payload.get("real_money_authorized") is not False:
        raise ValueError("public diagnostic does not deny real-money authority")


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _safe_identifier(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 128:
        return None
    if not all(character.isalnum() or character in {"_", "-", ".", ":"} for character in text):
        return None
    return text


def _safe_root(value: object) -> str | None:
    root = str(value or "").strip().upper()
    if not root or len(root) > 16:
        return None
    if not all(character.isalnum() or character in {"-", "_"} for character in root):
        return None
    return root


def _safe_reference_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    safe: dict[str, int] = {}
    for key in _REFERENCE_METRIC_KEYS:
        parsed = _nonnegative_int(value.get(key))
        if parsed is not None:
            safe[key] = parsed
    return safe


def _safe_reference_prequalification(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    safe: dict[str, object] = {
        "state": _safe_identifier(value.get("state")),
        "updated_at": str(value.get("updated_at") or "") or None,
        "active_component": _safe_identifier(value.get("active_component")),
    }
    for key in (
        "required_count",
        "qualified_count",
        "reused_count",
        "newly_qualified_count",
        "failed_count",
        "pending_count",
    ):
        parsed = _nonnegative_int(value.get(key))
        safe[key] = parsed if parsed is not None else 0

    components: list[dict[str, object]] = []
    raw_components = value.get("components")
    if isinstance(raw_components, list):
        for item in raw_components:
            if not isinstance(item, Mapping):
                continue
            components.append(
                {
                    "component": _safe_identifier(item.get("component")),
                    "provider": _safe_identifier(item.get("provider")),
                    "state": _safe_identifier(item.get("state")),
                    "required": item.get("required") is True,
                    "failure_type": _safe_identifier(item.get("failure_type")),
                }
            )
    safe["components"] = components
    safe["failures"] = [
        {
            "component": item.get("component"),
            "provider": item.get("provider"),
            "failure_type": item.get("failure_type"),
        }
        for item in components
        if item.get("state") in {"failed", "timed-out", "invalid"}
    ]
    return safe


def _safe_futures_reference_progress(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None

    required_roots = [
        root
        for item in value.get("required_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(value.get("required_roots"), list) else []
    qualified_roots = [
        root
        for item in value.get("qualified_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(value.get("qualified_roots"), list) else []
    unresolved_roots = [
        root
        for item in value.get("unresolved_roots", [])
        if (root := _safe_root(item)) is not None
    ] if isinstance(value.get("unresolved_roots"), list) else []

    nodes: list[dict[str, object]] = []
    raw_nodes = value.get("nodes")
    if isinstance(raw_nodes, list):
        for item in raw_nodes:
            if not isinstance(item, Mapping):
                continue
            root = _safe_root(item.get("root"))
            if root is None:
                continue
            duration_ms = _nonnegative_int(item.get("duration_ms"))
            http_status = _nonnegative_int(item.get("http_status"))
            if http_status is not None and not 100 <= http_status <= 599:
                http_status = None
            retryable = item.get("retryable")
            nodes.append(
                {
                    "root": root,
                    "state": _safe_identifier(item.get("state")),
                    "unit": _safe_identifier(item.get("unit")),
                    "provider": _safe_identifier(item.get("provider")),
                    "venue": _safe_identifier(item.get("venue")),
                    "failure_type": _safe_identifier(item.get("failure_type")),
                    "duration_ms": duration_ms if duration_ms is not None else 0,
                    "fallback": item.get("fallback") is True,
                    "provider_error_type": _safe_identifier(
                        item.get("provider_error_type")
                    ),
                    "http_status": http_status,
                    "retryable": retryable if isinstance(retryable, bool) else None,
                }
            )

    units: list[dict[str, object]] = []
    raw_units = value.get("units")
    if isinstance(raw_units, list):
        for item in raw_units:
            if not isinstance(item, Mapping):
                continue
            roots = [
                root
                for raw_root in item.get("roots", [])
                if (root := _safe_root(raw_root)) is not None
            ] if isinstance(item.get("roots"), list) else []
            duration_ms = _nonnegative_int(item.get("duration_ms"))
            http_status = _nonnegative_int(item.get("http_status"))
            if http_status is not None and not 100 <= http_status <= 599:
                http_status = None
            retryable = item.get("retryable")
            units.append(
                {
                    "unit": _safe_identifier(item.get("unit")),
                    "provider": _safe_identifier(item.get("provider")),
                    "state": _safe_identifier(item.get("state")),
                    "venue": _safe_identifier(item.get("venue")),
                    "root": _safe_root(item.get("root")),
                    "roots": roots,
                    "duration_ms": duration_ms if duration_ms is not None else 0,
                    "failure_type": _safe_identifier(item.get("failure_type")),
                    "fallback": item.get("fallback") is True,
                    "provider_error_type": _safe_identifier(
                        item.get("provider_error_type")
                    ),
                    "http_status": http_status,
                    "retryable": retryable if isinstance(retryable, bool) else None,
                }
            )

    active_units = [
        identifier
        for item in value.get("active_units", [])
        if (identifier := _safe_identifier(item)) is not None
    ] if isinstance(value.get("active_units"), list) else []
    fallback_max_workers = _nonnegative_int(value.get("fallback_max_workers"))
    if fallback_max_workers is not None and not 1 <= fallback_max_workers <= 4:
        fallback_max_workers = None

    try:
        timeout_seconds = float(value.get("unit_timeout_seconds", 0.0))
    except (TypeError, ValueError):
        timeout_seconds = 0.0
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
        timeout_seconds = 0.0

    return {
        "state": _safe_identifier(value.get("state")),
        "updated_at": str(value.get("updated_at") or "") or None,
        "cutoff": str(value.get("cutoff") or "") or None,
        "required_root_count": len(required_roots),
        "qualified_root_count": len(qualified_roots),
        "unresolved_root_count": len(unresolved_roots),
        "required_roots": required_roots,
        "qualified_roots": qualified_roots,
        "unresolved_roots": unresolved_roots,
        "active_unit": _safe_identifier(value.get("active_unit")),
        "active_units": active_units,
        "fallback_max_workers": fallback_max_workers,
        "unit_timeout_seconds": timeout_seconds,
        "blocking_unit": _safe_identifier(value.get("blocking_unit")),
        "blocking_provider": _safe_identifier(value.get("blocking_provider")),
        "blocking_venue": _safe_identifier(value.get("blocking_venue")),
        "blocking_root": _safe_root(value.get("blocking_root")),
        "blocking_failure_type": _safe_identifier(value.get("blocking_failure_type")),
        "blocking_provider_error_type": _safe_identifier(
            value.get("blocking_provider_error_type")
        ),
        "blocking_http_status": (
            status
            if (status := _nonnegative_int(value.get("blocking_http_status"))) is not None
            and 100 <= status <= 599
            else None
        ),
        "blocking_retryable": (
            value.get("blocking_retryable")
            if isinstance(value.get("blocking_retryable"), bool)
            else None
        ),
        "nodes": nodes,
        "units": units,
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _safe_futures_rows(detail: object) -> list[dict[str, object]]:
    raw = str(detail or "")
    token_index = raw.find(_FUTURES_TELEMETRY_TOKEN)
    if token_index < 0:
        return []
    encoded = raw[token_index + len(_FUTURES_TELEMETRY_TOKEN) :].lstrip()
    try:
        decoded, _ = json.JSONDecoder().raw_decode(encoded)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []

    rows: list[dict[str, object]] = []
    for item in decoded:
        if not isinstance(item, Mapping):
            continue
        root = str(item.get("root") or "").strip().upper()
        reason = str(item.get("reason") or "unknown").strip().lower()
        if not root or len(root) > 16 or not root.replace("-", "").isalnum():
            continue
        if not reason or len(reason) > 64 or not all(
            character.isalnum() or character in {"_", "-"}
            for character in reason
        ):
            reason = "unknown"
        row: dict[str, object] = {"root": root, "reason": reason}
        status = _nonnegative_int(item.get("status"))
        row["status"] = status
        for key in ("raw", "parsed", "matched", "valid", "usable"):
            parsed = _nonnegative_int(item.get(key))
            row[key] = parsed if parsed is not None else 0
        rows.append({key: row.get(key) for key in _FUTURES_ROW_KEYS})
    return rows


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-render-telemetry-enricher/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=15.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("public diagnostic must encode a JSON object")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def enrich_snapshot(
    snapshot: Mapping[str, Any],
    public_payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> dict[str, object]:
    _assert_safe(public_payload)
    enriched = dict(snapshot)
    diagnostic = enriched.get("diagnostic")
    if not isinstance(diagnostic, Mapping):
        return enriched
    if str(public_payload.get("active_release") or "") != expected_release:
        return enriched
    existing_id = str(diagnostic.get("diagnostic_id") or "").strip()
    public_id = str(
        public_payload.get("diagnostic_id") or public_payload.get("request_id") or ""
    ).strip()
    if existing_id and public_id and existing_id != public_id:
        return enriched

    enriched_diagnostic = dict(diagnostic)
    metrics = dict(enriched_diagnostic.get("progress_metrics") or {})
    metrics.update(_safe_reference_metrics(public_payload.get("progress_metrics")))
    enriched_diagnostic["progress_metrics"] = metrics

    reference_progress = _safe_reference_prequalification(
        public_payload.get("reference_prequalification_progress")
    )
    if reference_progress is not None:
        enriched_diagnostic["reference_prequalification_progress"] = reference_progress

    futures_progress = _safe_futures_reference_progress(
        public_payload.get("futures_reference_progress")
    )
    if futures_progress is not None:
        enriched_diagnostic["futures_reference_progress"] = futures_progress
        enriched_diagnostic["futures_reference_qualified_roots"] = futures_progress.get(
            "qualified_root_count", 0
        )
        enriched_diagnostic["futures_reference_unresolved_roots"] = futures_progress.get(
            "unresolved_root_count", 0
        )

    for key in (
        "prequalification_failure_reason",
        "prequalification_failure_capability",
        "prequalification_failure_stage",
        "prequalification_failure_provider",
        "prequalification_failure_error_type",
        "prequalification_failure_unit",
        "prequalification_failure_venue",
        "prequalification_failure_root",
    ):
        value = _safe_identifier(public_payload.get(key))
        if value is not None:
            enriched_diagnostic[key] = value

    unresolved = public_payload.get("prequalification_unresolved_futures_roots")
    if isinstance(unresolved, list):
        enriched_diagnostic["prequalification_unresolved_futures_roots"] = [
            root
            for item in unresolved
            if (root := _safe_root(item)) is not None
        ]

    prequalification = public_payload.get("prequalification_progress")
    if isinstance(prequalification, Mapping):
        active_phase = _safe_identifier(prequalification.get("active_phase"))
        enriched_diagnostic["prequalification_progress"] = {
            "active_phase": active_phase,
            "reference": reference_progress,
            "futures_reference": futures_progress,
        }

    futures_rows = _safe_futures_rows(public_payload.get("detail"))
    if futures_rows:
        enriched_diagnostic["futures_reference_telemetry"] = futures_rows
        enriched_diagnostic["futures_reference_failure_roots"] = sum(
            1 for row in futures_rows if row.get("reason") != "ok"
        )

    enriched["diagnostic"] = enriched_diagnostic
    enriched["enriched_from_public_diagnostic"] = True
    return enriched


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
    public_payload = _fetch_json(args.url)
    enriched = enrich_snapshot(
        snapshot,
        public_payload,
        expected_release=args.expected_release,
    )
    _write_json(args.output, enriched)

    if args.timeline_output is not None and args.timeline_output.exists():
        timeline = json.loads(args.timeline_output.read_text(encoding="utf-8"))
        if isinstance(timeline, list) and timeline:
            timeline[-1] = enriched
            _write_json(args.timeline_output, timeline)
    print(json.dumps(enriched, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
