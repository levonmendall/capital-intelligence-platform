"""Latest-production adapter for portfolio-value-ranked information depth."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

from api.config import ApiSettings
from application.production_context import SQLiteProductionContextStore
from evaluation.decision_intelligence_v3 import SQLiteDecisionIntelligenceV3Store
from operations.decision_information_depth import (
    DecisionInformationDepthProgram,
    build_decision_information_depth_program,
)
from screening import SQLiteFullUniverseScreeningStore, candidate_from_payload


_STATE_FILENAME = "production-context-publication-state.json"


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _latest_packet_opportunity_map(
    *,
    decision_as_of: datetime,
    decision_store: SQLiteDecisionIntelligenceV3Store,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for packet in decision_store.latest_cycle_packets():
        raw_as_of = packet.get("as_of")
        if not isinstance(raw_as_of, str):
            continue
        packet_as_of = datetime.fromisoformat(raw_as_of.replace("Z", "+00:00"))
        if packet_as_of != decision_as_of:
            # Never borrow opportunity economics from a different decision timestamp.
            continue
        candidate_identifier = str(packet.get("candidate_identifier", "")).strip()
        opportunity = packet.get("opportunity", {})
        if not candidate_identifier or not isinstance(opportunity, Mapping):
            continue
        value = opportunity.get("expected_dollar_value_added")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[candidate_identifier] = float(value)
    return result


def latest_decision_information_depth_program(
    settings: ApiSettings | None = None,
    *,
    state_path: str | Path | None = None,
    decision_intelligence_path: str | Path | None = None,
    runtime_information_report_path: str | Path | None = None,
) -> DecisionInformationDepthProgram:
    """Rank latest production-context gaps by portfolio-dollar opportunity at stake."""

    resolved_settings = settings or ApiSettings.from_env()
    resolved_state = (
        Path(state_path).expanduser()
        if state_path is not None
        else resolved_settings.portfolio_database.parent / _STATE_FILENAME
    )
    state = json.loads(resolved_state.read_text(encoding="utf-8"))
    if not isinstance(state, Mapping):
        raise ValueError("production-context publication state must be an object")
    as_of = _aware(state.get("decision_as_of"), field_name="decision_as_of")

    context_store = SQLiteProductionContextStore(
        resolved_settings.portfolio_database.with_name("production_context.db")
    )
    context_store.verify_integrity()
    snapshot = context_store.snapshot_for_as_of(
        portfolio_code="COMPOUNDING",
        as_of=as_of,
    )
    if snapshot is None:
        raise RuntimeError(
            "certified production context is unavailable for the latest decision timestamp"
        )

    screening_store = SQLiteFullUniverseScreeningStore(
        resolved_settings.full_universe_screening_database
    )
    screening_store.verify_integrity()
    publication = screening_store.publication(snapshot.screening_cycle_identifier)
    if publication is None:
        raise RuntimeError(
            "screening publication is unavailable for the latest production context"
        )
    candidates = tuple(
        candidate_from_payload(payload)
        for payload in publication.candidate_payloads
    )
    evidence_by_identifier = {
        str(item.candidate_identifier): item for item in snapshot.candidate_evidence
    }
    candidate_pairs = tuple(
        (candidate, evidence_by_identifier[candidate.identifier])
        for candidate in candidates
        if candidate.identifier in evidence_by_identifier
    )

    decision_store = SQLiteDecisionIntelligenceV3Store(
        decision_intelligence_path
        or resolved_settings.portfolio_database.parent / "decision-intelligence-v3.db"
    )
    expected_dollars = _latest_packet_opportunity_map(
        decision_as_of=as_of,
        decision_store=decision_store,
    )
    return build_decision_information_depth_program(
        candidate_evidence_pairs=candidate_pairs,
        portfolio_value=float(snapshot.portfolio.portfolio_value),
        expected_dollar_opportunity_by_candidate=expected_dollars,
        runtime_report_path=runtime_information_report_path,
    )


__all__ = ["latest_decision_information_depth_program"]
