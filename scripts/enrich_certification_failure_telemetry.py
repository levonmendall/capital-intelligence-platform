"""Preserve bounded certification DAG failure cause in the safe production artifact.

The runtime already projects credential-safe, paper-only certification failure metadata.
This helper copies only that bounded projection into the final telemetry artifact after the
legacy enrichers run. It is observability-only and changes no scheduling, evidence,
provider, market, strategy, authority, construction, or execution behavior.
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
_FAILURE_TEXT_LIMIT = 240


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


def _safe_identifier(value: object, *, limit: int = 160) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        return None
    if not all(character.isalnum() or character in {"_", "-", ".", ":"} for character in text):
        return None
    return text


def _bounded_text(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text[:_FAILURE_TEXT_LIMIT]


def _retry_after(value: object) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed >= 0.0 else None
    text = str(value).strip()
    if not text or len(text) > 64:
        return None
    if not all(character.isalnum() or character in {"-", ":", ".", "+", "T", "Z"} for character in text):
        return None
    return text


def _safe_node_state(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    state = _safe_identifier(value.get("state"))
    safe: dict[str, object] = {
        "state": state,
        "asset_class": _safe_identifier(value.get("asset_class")),
        "failure_type": _safe_identifier(value.get("failure_type")),
        "retryable": value.get("retryable") is True,
        "retry_after": _retry_after(value.get("retry_after")),
    }
    if state == "failed":
        safe.update(
            {
                "failure_message": _bounded_text(value.get("failure_message")),
                "failure_cause_type": _safe_identifier(value.get("failure_cause_type")),
                "failure_cause_message": _bounded_text(value.get("failure_cause_message")),
            }
        )
    return safe


def _safe_dag_progress(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("paper_only") is not True or value.get("real_money_authorized") is not False:
        return None
    safe: dict[str, object] = {
        "state": _safe_identifier(value.get("state")),
        "focus_node": _safe_identifier(value.get("focus_node")),
        "blocking_node": _safe_identifier(value.get("blocking_node")),
        "failure_type": _safe_identifier(value.get("failure_type")),
        "retryable": value.get("retryable") is True,
        "retry_after": _retry_after(value.get("retry_after")),
        "paper_only": True,
        "real_money_authorized": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
    }
    if safe["state"] == "failed":
        safe.update(
            {
                "failure_message": _bounded_text(value.get("failure_message")),
                "failure_cause_type": _safe_identifier(value.get("failure_cause_type")),
                "failure_cause_message": _bounded_text(value.get("failure_cause_message")),
            }
        )

    raw_states = value.get("node_states")
    node_states: dict[str, object] = {}
    if isinstance(raw_states, Mapping):
        for raw_node_id, raw_state in raw_states.items():
            node_id = _safe_identifier(raw_node_id)
            state = _safe_node_state(raw_state)
            if node_id is not None and state is not None:
                node_states[node_id] = state
    safe["node_states"] = node_states
    return safe


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
    public_id = str(public_payload.get("diagnostic_id") or public_payload.get("request_id") or "").strip()
    if existing_id and public_id and existing_id != public_id:
        return enriched

    prequalification = public_payload.get("prequalification_progress")
    if not isinstance(prequalification, Mapping):
        return enriched
    dag_progress = _safe_dag_progress(prequalification.get("dag_progress"))
    if dag_progress is None:
        return enriched

    enriched_diagnostic = dict(diagnostic)
    current_progress = enriched_diagnostic.get("prequalification_progress")
    safe_progress = dict(current_progress) if isinstance(current_progress, Mapping) else {}
    safe_progress["dag_progress"] = dag_progress
    enriched_diagnostic["prequalification_progress"] = safe_progress
    enriched["diagnostic"] = enriched_diagnostic
    enriched["certification_failure_telemetry_enriched"] = True
    return enriched


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "capital-intelligence-certification-telemetry/1.0"},
    )
    with urllib.request.urlopen(request, timeout=15.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("public diagnostic must encode a JSON object")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    enriched = enrich_snapshot(snapshot, public_payload, expected_release=args.expected_release)
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
