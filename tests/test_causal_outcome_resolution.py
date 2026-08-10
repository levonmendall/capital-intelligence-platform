from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from evaluation.causal_intelligence_graph import (
    CausalTransmissionOutcome,
    SQLiteCausalIntelligenceGraphStore,
    build_causal_investment_graph,
)
from evaluation.causal_outcome_resolution import (
    CausalOutcomeResolutionError,
    append_point_in_time_causal_outcome,
)
from intelligence.event_market_forward import (
    CausalDriver,
    EventCausalState,
    EventMarketAssessment,
    MarketTransmission,
    RuleTransmission,
    TransmissionDirection,
)

NOW = datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc)


def _assessment() -> EventMarketAssessment:
    driver = CausalDriver(
        rule_identifier="test-rule",
        name="test driver",
        confidence=0.8,
        causal_chain=("cause", "effect"),
        transmissions=(
            RuleTransmission(
                target_identifier="broad_equities",
                direction=TransmissionDirection.POSITIVE,
                magnitude=0.4,
                mechanism="test mechanism",
                horizon="near_term",
            ),
        ),
        alternatives=("alternative",),
    )
    transmission = MarketTransmission(
        target_identifier="broad_equities",
        direction=TransmissionDirection.POSITIVE,
        magnitude=0.4,
        confidence=0.75,
        mechanism="test mechanism",
        horizon="near_term",
        contributing_driver_identifiers=("test-rule",),
        evidence_identifiers=("event:1", "market:1"),
    )
    return EventMarketAssessment(
        identifier="assessment:pit",
        information_identifier="information:pit",
        event_cluster_identifier="cluster:pit",
        assessed_at=NOW,
        state=EventCausalState.MAPPED,
        drivers=(driver,),
        causal_chain=driver.causal_chain,
        transmissions=(transmission,),
        market_confirmation=0.7,
        confirmation_coverage=1.0,
        confidence=0.75,
        major_event=True,
        requires_causal_review=False,
        contradictory_evidence=(),
        alternative_explanations=("alternative",),
        unresolved_questions=(),
        evidence_identifiers=("event:1", "market:1"),
        eligible_for_analysis=True,
        eligible_for_cio_context=True,
        policy_version="test-policy",
    )


def test_unknown_causal_edge_cannot_be_resolved(tmp_path):
    store = SQLiteCausalIntelligenceGraphStore(tmp_path / "causal.db")
    with pytest.raises(CausalOutcomeResolutionError, match="unknown predicted edge"):
        append_point_in_time_causal_outcome(
            store,
            CausalTransmissionOutcome(
                edge_identifier="edge:missing",
                observed_at=NOW + timedelta(days=1),
                realized_direction="positive",
                realized_magnitude=0.3,
                evidence_identifiers=("outcome:1",),
            ),
        )


def test_causal_outcome_must_be_later_than_prediction(tmp_path):
    store = SQLiteCausalIntelligenceGraphStore(tmp_path / "causal.db")
    graph = build_causal_investment_graph(_assessment())
    store.append_graph(graph)
    edge = next(item for item in graph.edges if item.relationship == "transmits_to")
    with pytest.raises(CausalOutcomeResolutionError, match="strictly after"):
        append_point_in_time_causal_outcome(
            store,
            CausalTransmissionOutcome(
                edge_identifier=edge.identifier,
                observed_at=NOW,
                realized_direction="positive",
                realized_magnitude=0.3,
                evidence_identifiers=("outcome:1",),
            ),
        )
    content_hash = append_point_in_time_causal_outcome(
        store,
        CausalTransmissionOutcome(
            edge_identifier=edge.identifier,
            observed_at=NOW + timedelta(days=1),
            realized_direction="positive",
            realized_magnitude=0.3,
            evidence_identifiers=("outcome:2",),
        ),
    )
    assert len(content_hash) == 64
