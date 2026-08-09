from __future__ import annotations

from types import SimpleNamespace

from committee.specialists import MarketSpecialistContext
from intelligence.forward import ForwardIntelligenceBundle
from intelligence.forward_decision import DecisionTimingPosture, EvidenceAvailability, ForwardDecisionDimension
from intelligence.predictive_market import CapitalFlowEngine, CapitalFlowObservation, build_predictive_market_intelligence, merge_forward_intelligence
from intelligence.predictive_scenario_merge import reconcile_forward_intelligence
from tests.test_production_context_assembly import AS_OF, _candidate


def _market():
    return MarketSpecialistContext(as_of=AS_OF, market_regime="constructive", expected_return_impact=0.01, confidence=0.75, trend=0.30, momentum=0.25, breadth=0.20, liquidity=0.90, positioning=0.10, evidence=("governed quote/liquidity evidence",), risks=("Liquidity can deteriorate",), entry_conditions=("Price/volume confirmation remains intact",), evidence_identifiers=("evidence:market",))


def _flow_observation(candidate):
    return CapitalFlowObservation(identifier="derived-flow:test", symbol=candidate.instrument.symbol, as_of=AS_OF, recent_volume_impulse=0.20, signed_dollar_flow=0.25, accumulation_distribution=0.22, price_volume_confirmation=0.30, persistence=0.60, short_trend=0.08, medium_trend=0.12, volatility=0.24, crowding=0.45, short_covering_likelihood=0.25, evidence_identifiers=("evidence:flow",))


def _intelligence():
    candidate = _candidate()
    result = build_predictive_market_intelligence(candidate=candidate, features=SimpleNamespace(momentum=0.15, six_month_return=0.12, twelve_month_return=0.18, annualized_volatility=0.24, rolling_annual_median=0.10), flow_observation=_flow_observation(candidate), market=_market(), existing_forward_intelligence=None)
    return candidate, result


def test_active_predictive_builder_attaches_truthful_forward_decision_context():
    candidate, intelligence = _intelligence()
    context = intelligence.forward_intelligence.decision_context
    assert context is not None
    dimensions = {item.dimension: item for item in context.dimensions}
    assert dimensions[ForwardDecisionDimension.EXPECTATIONS].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.POSITIONING].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.MICROSTRUCTURE].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.REFLEXIVITY].availability is EvidenceAvailability.PARTIAL
    assert dimensions[ForwardDecisionDimension.PATH_RISK].availability is EvidenceAvailability.AVAILABLE
    assert dimensions[ForwardDecisionDimension.DERIVATIVES].availability is EvidenceAvailability.UNAVAILABLE
    assert dimensions[ForwardDecisionDimension.EARNINGS].availability is EvidenceAvailability.NOT_APPLICABLE
    assert context.timing is not None and context.timing.posture is DecisionTimingPosture.NO_TIMING_EDGE
    assert context.catalysts == ()
    assert context.thesis_monitor is not None
    assert context.thesis_monitor.invalidation_conditions == candidate.invalidation_conditions


def test_predictive_merge_paths_preserve_forward_decision_context():
    candidate, intelligence = _intelligence()
    predictive = intelligence.forward_intelligence
    existing = ForwardIntelligenceBundle(identifier="forward:existing", candidate_identifier=candidate.identifier, as_of=AS_OF, signals=(), scenarios=(), diagnostics=("existing",), model_versions=("existing.v1",))
    assert merge_forward_intelligence(existing, predictive).decision_context == predictive.decision_context
    assert reconcile_forward_intelligence(existing, predictive).decision_context == predictive.decision_context


def test_market_flow_proxy_does_not_claim_institutional_or_derivatives_coverage():
    candidate = _candidate()
    flow = CapitalFlowEngine().analyze(_flow_observation(candidate))
    assert "proxy" in flow.signal.name
    assert any("dealer inventory" in item for item in flow.signal.contradictory_evidence)
