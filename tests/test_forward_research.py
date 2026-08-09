from datetime import datetime, timezone

from cio.models import CandidateAssetClass
from intelligence.event_market_forward import (
    EventCausalState,
    EventMarketAssessment,
    MarketTransmission,
    TransmissionDirection,
)
from intelligence.forward_decision import (
    DecisionTimingPosture,
    EvidenceAvailability,
    ForwardDecisionDimension,
    build_forward_decision_context,
)
from intelligence.forward_research import (
    CertifiedExpectationObservation,
    ExpectationEvidenceKind,
    ExpectationsIntelligenceEngine,
    ForwardOpportunityDiscoveryEngine,
    ForwardResearchEvidence,
    GovernedNowcastingEngine,
    NowcastObservation,
    NowcastTarget,
    PositioningEvidenceKind,
    PositioningIntelligenceEngine,
    PositioningObservation,
    ResearchExposure,
    ValueOfWaitingEngine,
    ValueOfWaitingInputs,
    enrich_forward_decision_context,
)

AS_OF = datetime(2026, 8, 9, 18, 0, tzinfo=timezone.utc)


def test_certified_expectations_replace_proxy_only_reasoning():
    observations = (
        CertifiedExpectationObservation(
            identifier="consensus:cpi",
            subject_identifier="US-CPI",
            kind=ExpectationEvidenceKind.MACRO_CONSENSUS,
            as_of=AS_OF,
            market_expectation=2.8,
            internal_expectation=2.5,
            uncertainty=0.15,
            confidence=0.8,
            evidence_identifiers=("source:consensus:cpi",),
        ),
    )
    result = ExpectationsIntelligenceEngine().analyze(observations)
    assert result.proxy_fallback is False
    assert result.expected_surprise < 0
    assert result.evidence_identifiers == ("source:consensus:cpi",)


def test_positioning_combines_institutional_and_derivative_evidence():
    result = PositioningIntelligenceEngine().analyze((
        PositioningObservation("fund-flow", "SPY", PositioningEvidenceKind.ETF_FLOW, AS_OF, 0.5, 0.6, 0.8, ("flow:spy",)),
        PositioningObservation("gamma", "SPY", PositioningEvidenceKind.DEALER_GAMMA, AS_OF, -0.2, 0.8, 0.7, ("gamma:spy",)),
    ))
    assert result.derivative_coverage is True
    assert result.evidence_identifiers == ("flow:spy", "gamma:spy")
    assert 0 <= result.reversal_risk <= 1


def test_nowcast_is_probabilistic_and_point_in_time():
    result = GovernedNowcastingEngine().estimate((
        NowcastObservation("price", NowcastTarget.CPI, AS_OF, 2.45, 1.0, 0.8, ("leading:prices",)),
        NowcastObservation("wages", NowcastTarget.CPI, AS_OF, 2.60, 0.7, 0.7, ("leading:wages",)),
    ), consensus=2.8)
    assert result.estimate < 2.8
    assert result.probability_above_consensus is not None
    assert result.probability_above_consensus < 0.5


def test_value_of_waiting_can_prefer_information_resolution():
    result = ValueOfWaitingEngine().assess(ValueOfWaitingInputs(
        as_of=AS_OF,
        invest_now_expected_return=0.06,
        downside_if_unresolved=-0.18,
        probability_uncertainty_resolves=0.65,
        expected_upside_lost_by_waiting=0.02,
        expected_post_event_entry_drag=0.005,
        transaction_cost_return=0.001,
        alternative_return_while_waiting=0.002,
        thesis_decay_return=0.0,
        evidence_identifiers=("event:earnings",),
    ))
    assert result.posture is DecisionTimingPosture.WAIT_FOR_EVENT
    assert result.value_of_waiting > 0
    assert result.advisory_only is True


def test_forward_opportunity_discovery_maps_causal_exposure_to_research_only_candidate():
    transmission = MarketTransmission(
        target_identifier="commodity_consumers",
        direction=TransmissionDirection.POSITIVE,
        magnitude=0.45,
        confidence=0.8,
        mechanism="Lower input costs can improve margins.",
        horizon="near_to_medium_term",
        contributing_driver_identifiers=("geopolitical-deescalation",),
        evidence_identifiers=("event:ceasefire",),
    )
    assessment = EventMarketAssessment(
        identifier="event-assessment:1",
        information_identifier="news:1",
        event_cluster_identifier="cluster:1",
        assessed_at=AS_OF,
        state=EventCausalState.MAPPED,
        drivers=(),
        causal_chain=("risk premium falls", "input costs fall"),
        transmissions=(transmission,),
        market_confirmation=0.4,
        confirmation_coverage=0.8,
        confidence=0.8,
        major_event=True,
        requires_causal_review=False,
        contradictory_evidence=(),
        alternative_explanations=("demand weakness",),
        unresolved_questions=(),
        evidence_identifiers=("event:ceasefire",),
        eligible_for_analysis=True,
        eligible_for_cio_context=True,
        policy_version="event-market-forward.v1",
    )
    hypotheses = ForwardOpportunityDiscoveryEngine().discover(
        assessment,
        eligible_exposures=(ResearchExposure(
            exposure_identifier="commodity_consumers",
            instrument_identifier="instrument:AIRLINE",
            symbol="AIRLINE",
            asset_class=CandidateAssetClass.US_EQUITY,
            liquidity_score=0.9,
            evidence_identifiers=("universe:AIRLINE",),
        ),),
    )
    assert len(hypotheses) == 1
    assert hypotheses[0].research_only is True
    assert hypotheses[0].authorizes_capital is False


def test_research_enrichment_preserves_forward_decision_authority_boundary():
    context = build_forward_decision_context(
        identifier="fd:1",
        candidate_identifier="candidate:1",
        as_of=AS_OF,
        asset_class=CandidateAssetClass.US_EQUITY,
    )
    expectations = ExpectationsIntelligenceEngine().analyze((
        CertifiedExpectationObservation(
            "eps", "candidate:1", ExpectationEvidenceKind.ANALYST_EPS, AS_OF,
            5.0, 5.5, 0.25, 0.8, ("consensus:eps",),
        ),
    ))
    positioning = PositioningIntelligenceEngine().analyze((
        PositioningObservation("oi", "candidate:1", PositioningEvidenceKind.OPTIONS_OPEN_INTEREST, AS_OF, 0.2, 0.4, 0.7, ("options:oi",)),
    ))
    nowcast = GovernedNowcastingEngine().estimate((
        NowcastObservation("revenue", NowcastTarget.COMPANY_REVENUE, AS_OF, 101.0, 1.0, 0.75, ("leading:revenue",)),
    ), consensus=100.0)
    enriched = enrich_forward_decision_context(
        context,
        ForwardResearchEvidence(expectations=expectations, positioning=positioning, nowcasts=(nowcast,)),
    )
    by_dimension = {item.dimension: item for item in enriched.dimensions}
    assert by_dimension[ForwardDecisionDimension.EXPECTATIONS].availability is EvidenceAvailability.AVAILABLE
    assert by_dimension[ForwardDecisionDimension.DERIVATIVES].availability is EvidenceAvailability.AVAILABLE
    assert by_dimension[ForwardDecisionDimension.ALTERNATIVE_DATA].availability is EvidenceAvailability.AVAILABLE
    assert enriched.advisory_only is True
