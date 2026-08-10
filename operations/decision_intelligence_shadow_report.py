"""Read-only shadow report for the latest certified CIO production context.

The report makes candidate-level information completeness visible without changing
candidate qualification, specialist conclusions, CIO authority, construction, or
execution. Missing evidence remains explicit and cannot be converted into a neutral
signal by this reporting path.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from api.config import ApiSettings
from application.production_context import SQLiteProductionContextStore
from intelligence.information_completeness import CandidateInformationCompletenessEngine
from screening import SQLiteFullUniverseScreeningStore, candidate_from_payload


_STATE_FILENAME = "production-context-publication-state.json"


def _aware_timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def build_candidate_information_completeness_report(
    *,
    as_of: datetime,
    candidates: Sequence[object],
    candidate_evidence: Sequence[object],
) -> dict[str, object]:
    """Build one deterministic, authority-free candidate completeness report."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    evidence_by_identifier = {
        str(getattr(item, "candidate_identifier")): item for item in candidate_evidence
    }
    if len(evidence_by_identifier) != len(tuple(candidate_evidence)):
        raise ValueError("candidate evidence identifiers must be unique")
    engine = CandidateInformationCompletenessEngine()
    rows: list[dict[str, object]] = []
    for candidate in candidates:
        identifier = str(getattr(candidate, "identifier"))
        evidence = evidence_by_identifier.get(identifier)
        if evidence is None:
            rows.append(
                {
                    "candidate_identifier": identifier,
                    "symbol": str(getattr(getattr(candidate, "instrument"), "symbol")),
                    "asset_class": str(
                        getattr(getattr(candidate, "instrument"), "asset_class").value
                    ),
                    "decision_complete": False,
                    "completeness": 0.0,
                    "available_dimensions": [],
                    "missing_dimensions": ["governed_candidate_evidence"],
                    "missing_reasons": [
                        "governed candidate evidence is unavailable for the certified decision timestamp"
                    ],
                    "investment_authority": False,
                }
            )
            continue
        assessment = engine.assess(candidate, evidence)
        rows.append(
            {
                "candidate_identifier": identifier,
                "symbol": str(getattr(getattr(candidate, "instrument"), "symbol")),
                "asset_class": str(
                    getattr(getattr(candidate, "instrument"), "asset_class").value
                ),
                "decision_complete": assessment.coverage.decision_complete,
                "completeness": assessment.coverage.completeness,
                "available_dimensions": [
                    item.value for item in assessment.coverage.available
                ],
                "missing_dimensions": [
                    item.value for item in assessment.coverage.missing
                ],
                "available_reasons": list(assessment.available_reasons),
                "missing_reasons": list(assessment.missing_reasons),
                "investment_authority": False,
            }
        )
    complete = sum(bool(item["decision_complete"]) for item in rows)
    average = (
        1.0
        if not rows
        else round(
            sum(float(item["completeness"]) for item in rows) / len(rows),
            8,
        )
    )
    return {
        "schema_version": "candidate-information-completeness-report.v1",
        "as_of": as_of.isoformat(),
        "candidate_count": len(rows),
        "decision_complete_candidate_count": complete,
        "incomplete_candidate_count": len(rows) - complete,
        "average_information_completeness": average,
        "candidates": rows,
        "investment_authority": False,
        "ranking_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "real_money_authorized": False,
    }


def latest_candidate_information_completeness_report(
    settings: ApiSettings | None = None,
    *,
    state_path: str | Path | None = None,
) -> dict[str, object]:
    """Resolve the latest persisted exact-time production context and audit it."""

    resolved_settings = settings or ApiSettings.from_env()
    resolved_state = (
        Path(state_path).expanduser()
        if state_path is not None
        else resolved_settings.portfolio_database.parent / _STATE_FILENAME
    )
    payload = json.loads(resolved_state.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("production-context publication state must be an object")
    as_of = _aware_timestamp(payload.get("decision_as_of"), field_name="decision_as_of")

    context_store = SQLiteProductionContextStore(
        resolved_settings.portfolio_database.with_name("production_context.db")
    )
    context_store.verify_integrity()
    snapshot = context_store.snapshot_for_as_of(
        portfolio_code="COMPOUNDING",
        as_of=as_of,
    )
    if snapshot is None:
        raise RuntimeError("certified production context is unavailable for the latest decision timestamp")

    screening_store = SQLiteFullUniverseScreeningStore(
        resolved_settings.full_universe_screening_database
    )
    screening_store.verify_integrity()
    publication = screening_store.publication(snapshot.screening_cycle_identifier)
    if publication is None:
        raise RuntimeError("screening publication is unavailable for the latest production context")
    candidates = tuple(
        candidate_from_payload(payload)
        for payload in publication.candidate_payloads
    )
    report = build_candidate_information_completeness_report(
        as_of=as_of,
        candidates=candidates,
        candidate_evidence=snapshot.candidate_evidence,
    )
    return {
        **report,
        "production_context_identifier": snapshot.identifier,
        "screening_publication_identifier": publication.identifier,
    }


__all__ = [
    "build_candidate_information_completeness_report",
    "latest_candidate_information_completeness_report",
]
