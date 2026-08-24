"""Enrich Render telemetry with a fixed credential-safe production-context failure code.

The public CIO diagnostic already carries a redacted fail-closed detail for operators. GitHub
telemetry deliberately does not copy that free-form text. This helper classifies only known
failure phrases into fixed identifiers, preserving the no-secrets/no-portfolio-details
artifact contract while making the exact blocked boundary actionable.
"""

from __future__ import annotations

import argparse
import json
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

# Most-specific rules must precede their broader enclosing failure boundary.
_FAILURE_RULES: tuple[tuple[str, str], ...] = (
    (
        "mandatory holding evidence is unavailable while the instrument's market is scheduled closed",
        "mandatory_holding_market_scheduled_closed",
    ),
    ("mandatory holding evidence failed for", "mandatory_holding_evidence_failed"),
    ("vti benchmark evidence is mandatory", "vti_benchmark_evidence_missing"),
    (
        "point-in-time capital-flow evidence is unavailable",
        "capital_flow_evidence_missing",
    ),
    (
        "portfolio and paper evidence must share the exact decision timestamp",
        "portfolio_evidence_timestamp_mismatch",
    ),
    (
        "live paper evidence payload is missing the alpaca market clock",
        "paper_market_clock_missing",
    ),
    (
        "alpaca market clock differs from the collection-complete decision timestamp",
        "paper_market_clock_mismatch",
    ),
    ("canonical portfolio nav must be positive", "canonical_portfolio_nav_invalid"),
    (
        "required holding evidence is outside the governed paper universe",
        "required_holding_outside_governed_universe",
    ),
    (
        "canonical holdings are outside the governed paper universe",
        "canonical_holding_outside_governed_universe",
    ),
    (
        "candidate and exclusion evidence do not reconcile the active universe",
        "candidate_exclusion_reconciliation_failed",
    ),
    (
        "persisted exact-time portfolio marks conflict with current evidence",
        "persisted_portfolio_mark_conflict",
    ),
    (
        "certified holding marks are invalid",
        "certified_holding_marks_invalid",
    ),
    (
        "current marks are unavailable for canonical holdings",
        "canonical_holding_marks_missing",
    ),
    (
        "candidate and mandatory holding marks disagree",
        "candidate_holding_mark_conflict",
    ),
    (
        "cross-market evidence collection failed",
        "cross_market_evidence_collection_failed",
    ),
    (
        "candidate or holding evidence failed closed",
        "candidate_or_holding_evidence_failed",
    ),
    (
        "canonical portfolio finalization failed",
        "canonical_portfolio_finalization_failed",
    ),
)


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


def classify_context_failure(detail: object) -> str | None:
    """Map redacted free-form context detail to a fixed non-sensitive identifier."""

    text = str(detail or "").strip().lower()
    if not text:
        return None
    for phrase, code in _FAILURE_RULES:
        if phrase in text:
            return code
    return None


def _fetch_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-context-failure-enricher/1.0",
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
    """Attach only a fixed failure code when release and diagnostic identity still match."""

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

    failure_code = classify_context_failure(public_payload.get("detail"))
    if failure_code is None:
        return enriched

    enriched_diagnostic = dict(diagnostic)
    enriched_diagnostic["context_failure_code"] = failure_code
    enriched["diagnostic"] = enriched_diagnostic
    enriched["enriched_from_context_failure"] = True
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
            last = timeline[-1]
            if isinstance(last, Mapping):
                timeline[-1] = enrich_snapshot(
                    last,
                    public_payload,
                    expected_release=args.expected_release,
                )
                _write_json(args.timeline_output, timeline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
