from datetime import datetime, timezone

import pytest

from intelligence.causal_investment_reasoning import GroundedCausalReasoningEngine
from intelligence.event_market_forward import (
    CausalDriver,
    EventCausalState,
    EventMarketAssessment,
    MarketTransmission,
    TransmissionDirection,
)


def _assessment(state=EventCausalState.MAPPED):
    now = datetime(2026, 8, 3, 20, tzinfo=timezone.utc)
    return EventMarketAssessment(
        identifier="event-1",
        information_identifier="info-1",
        event_cluster_identifier="cluster-1",
        assessed_at=now,
        state=state,
        drivers=(CausalDriver("oil", "oil supply", 0.8, ("supply rises",), (), ("demand fell",)),),
        causal_chain=("supply rises", "oil risk premium falls"),
        transmissions=(
            MarketTransmission(
                "airlines",
                TransmissionDirection.POSITIVE,
                0.4,
                0.7,
                "lower fuel costs support margins",
                "near_term",
                ("oil",),
                ("source-1",),
            ),
        ),
        market_confirmation=0.5,
        confirmation_coverage=1.0,
        confidence=0.65,
        major_event=True,
        requires_causal_review=False,
        contradictory_evidence=("demand may also be weakening",),
        alternative_explanations=("macro slowdown",),
        unresolved_questions=(),
        evidence_identifiers=("source-1",),
        eligible_for_analysis=True,
        eligible_for_cio_context=True,
        policy_version="event-policy.v1",
    )


def test_builds_grounded_claim_with_authority_boundaries():
    assessment = _assessment()
    package = GroundedCausalReasoningEngine().build(
        assessment,
        source_timestamps={"source-1": (assessment.assessed_at, assessment.assessed_at)},
        priced_in_assessment="partially reflected in oil futures",
    )
    assert package.resolved
    assert package.claims[0].direction.value == "positive"
    assert package.claims[0].contradictory_evidence
    assert package.claims[0].invalidation_conditions
    payload = package.to_dict()
    assert payload["authorizes_portfolio_change"] is False
    assert payload["authorizes_specialist_vote"] is False


def test_unresolved_major_event_stays_unresolved():
    assessment = _assessment(EventCausalState.UNRESOLVED_MAJOR_EVENT)
    package = GroundedCausalReasoningEngine().build(
        assessment,
        source_timestamps={"source-1": (assessment.assessed_at, assessment.assessed_at)},
    )
    assert not package.resolved
    assert package.claims == ()


def test_missing_source_timestamp_fails_closed():
    with pytest.raises(ValueError, match="missing source timestamps"):
        GroundedCausalReasoningEngine().build(_assessment(), source_timestamps={})
