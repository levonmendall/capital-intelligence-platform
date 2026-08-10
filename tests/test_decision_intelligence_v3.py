from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cio.models import CandidateAssetClass, CIOAction
from evaluation.decision_intelligence_v3 import (
    DecisionOutcomeObservation,
    SQLiteDecisionIntelligenceV3Store,
    build_cio_wealth_validation_report,
)
from governance.decision_readiness import CandidateDecisionReadinessPolicy
from intelligence.ask_cio import AskCIOService
from intelligence.asset_underwriting import UnderwritingCoverage, UnderwritingDimension
from intelligence.decision_intelligence_v3 import (
    CandidateDecisionIntelligencePacket,
    CompoundingObjectiveSnapshot,
    DecisionExplanationChain,
    DecisionIntelligenceState,
    GlobalOpportunityComparison,
    build_candidate_decision_intelligence_packet,
)
from intelligence.information_completeness import CandidateInformationCompleteness
from intelligence.value_of_information import ValueOfInformationEngine


NOW = datetime(2026, 8, 10, 4, 30, tzinfo=timezone.utc)


class _CompletenessEngine:
    def assess(self, candidate, evidence):
        del evidence
        available = (
            UnderwritingDimension.HISTORY,
            UnderwritingDimension.IDENTITY,
            UnderwritingDimension.LIQUIDITY,
            UnderwritingDimension.MACRO,
            UnderwritingDimension.MARKET_DATA,
            UnderwritingDimension.VALUATION,
        )
        coverage = UnderwritingCoverage(
            asset_class=CandidateAssetClass.US_ETF,
            required=available,
            available=available,
            missing=(),
            completeness=1.0,
            decision_complete=True,
        )
        return CandidateInformationCompleteness(
            candidate_identifier=candidate.identifier,
            coverage=coverage,
            available_reasons=("vehicle evidence complete",),
            missing_reasons=(),
        )


def _crypto_wrapper_readiness():
    candidate = SimpleNamespace(
        identifier="candidate:ibit",
        instrument=SimpleNamespace(
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
        ),
    )
    return CandidateDecisionReadinessPolicy(_CompletenessEngine()).assess(
        candidate, object()
    )


def test_wrapper_discloses_underlying_crypto_intelligence_gap_without_silent_reclassification():
    readiness = _crypto_wrapper_readiness()
    assert readiness.decision_ready is True
    assert readiness.asset_class is CandidateAssetClass.US_ETF
    assert readiness.economic_exposure_class is CandidateAssetClass.CRYPTO
    assert readiness.deep_intelligence_complete is False
    assert UnderwritingDimension.ONCHAIN in readiness.deep_missing
    assert UnderwritingDimension.POSITIONING in readiness.deep_missing
    assert readiness.investment_authority is False


def test_value_of_information_prioritizes_underlying_economic_gaps():
    priorities = ValueOfInformationEngine().prioritize(
        readiness=_crypto_wrapper_readiness()
    )
    dimensions = {item.dimension for item in priorities}
    assert UnderwritingDimension.ONCHAIN in dimensions
    assert UnderwritingDimension.POSITIONING in dimensions
    onchain = next(
        item for item in priorities if item.dimension is UnderwritingDimension.ONCHAIN
    )
    assert onchain.blocking is False
    assert any("economic-exposure" in item for item in onchain.rationale)
    assert onchain.authorizes_capital is False


def _packet() -> CandidateDecisionIntelligencePacket:
    objective = CompoundingObjectiveSnapshot(
        portfolio_value=250_000.0,
        cash_weight=0.40,
        cash_expected_return=0.04,
        expected_portfolio_return_after_cost=0.09,
        expected_portfolio_improvement=0.01,
        expected_dollar_value_added=2_500.0,
        expected_terminal_portfolio_value=272_500.0,
    )
    opportunity = GlobalOpportunityComparison(
        candidate_identifier="candidate:abc",
        symbol="ABC",
        current_weight=0.0,
        proposed_target_weight=0.10,
        candidate_expected_return=0.15,
        cash_expected_return=0.04,
        best_alternative_identifier="cash",
        best_alternative_expected_return=0.04,
        edge_over_cash=0.11,
        edge_over_best_alternative=0.11,
        marginal_portfolio_improvement=0.011,
        expected_dollar_value_added=2_750.0,
        changes_portfolio=True,
    )
    explanation = DecisionExplanationChain(
        what_changed=("Earnings expectations improved.",),
        why_it_matters=("Expected cash flow increased.",),
        market_expectation="5% growth",
        internal_expectation="8% growth",
        expected_surprise=0.03,
        priced_in_score=0.30,
        bull_case="bull",
        base_case="base",
        bear_case="bear",
        specialist_disagreements=(),
        key_risks=("valuation",),
        invalidation_conditions=("growth falls below 2%",),
        monitoring_indicators=("revisions",),
        evidence_identifiers=("evidence:1",),
    )
    return CandidateDecisionIntelligencePacket(
        identifier="decision-intelligence-v3:cycle-1:candidate:abc",
        cycle_identifier="cycle-1",
        candidate_identifier="candidate:abc",
        symbol="ABC",
        name="ABC Corp",
        as_of=NOW,
        vehicle_asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure_class=CandidateAssetClass.US_EQUITY,
        state=DecisionIntelligenceState.SELECTED,
        cio_action="buy",
        cio_confidence=0.80,
        cio_rationale=("Best use of capital after costs.",),
        objective=objective,
        opportunity=opportunity,
        explanation=explanation,
        risk_summary=("candidate_expected_shortfall=-0.10",),
        thesis_summary=("state: approved",),
        source_lineage=("evidence:1",),
    )


def test_append_only_packet_store_and_wealth_validation(tmp_path):
    store = SQLiteDecisionIntelligenceV3Store(tmp_path / "decision-intelligence.db")
    packet = _packet()
    first_hash = store.append_packet(packet)
    assert store.append_packet(packet) == first_hash
    assert store.latest_for_symbol("abc")["candidate_identifier"] == "candidate:abc"

    outcome = DecisionOutcomeObservation(
        packet_identifier=packet.identifier,
        observed_at=NOW,
        realized_candidate_return=0.12,
        realized_portfolio_return=0.08,
        realized_cash_return=0.04,
        realized_best_alternative_return=0.05,
        realized_benchmark_return=0.06,
        realized_max_drawdown=-0.07,
        evidence_identifiers=("outcome:1",),
    )
    store.append_outcome(outcome)
    report = build_cio_wealth_validation_report(store.validation_pairs(), as_of=NOW)
    assert report.observation_count == 1
    assert report.mean_portfolio_excess_return_vs_cash == pytest.approx(0.04)
    assert report.cumulative_diagnostic_dollar_value_added_vs_cash == pytest.approx(10_000.0)
    assert report.performance_claim_authorized is False
    assert report.policy_change_authorized is False


def test_ask_cio_is_read_only_and_answers_from_latest_packet(tmp_path):
    store = SQLiteDecisionIntelligenceV3Store(tmp_path / "ask-cio.db")
    store.append_packet(_packet())
    answer = AskCIOService(store).answer(
        "What is the best opportunity for the next dollar?"
    )
    assert answer.intent == "best_opportunity"
    assert "ABC" in answer.answer
    assert answer.investment_authority is False
    assert answer.construction_authority is False
    assert answer.execution_authority is False
    assert "evidence:1" in answer.evidence_identifiers


def test_packet_builder_separates_portfolio_and_candidate_dollar_value():
    instrument = SimpleNamespace(
        symbol="ABC",
        name="ABC Corp",
        asset_class=CandidateAssetClass.US_EQUITY,
        economic_exposure_class=CandidateAssetClass.US_EQUITY,
    )
    candidate = SimpleNamespace(
        identifier="candidate:abc",
        instrument=instrument,
        as_of=NOW,
        net_expected_return=0.15,
        opportunity_cost_return=0.04,
        primary_catalysts=("revision acceleration",),
        supporting_evidence=("cash flow improved",),
        key_risks=("valuation",),
        thesis_invalidation_conditions=("growth reverses",),
        monitoring_indicators=("revisions",),
        evidence_identifiers=("candidate-evidence",),
        bull_case=None,
        base_case=None,
        bear_case=None,
    )
    context = SimpleNamespace(forward_intelligence=None)
    portfolio = SimpleNamespace(
        portfolio_value=250_000.0,
        cash_weight=0.50,
        cash_expected_return=0.04,
        current_weight=lambda symbol: 0.0,
    )
    decision = SimpleNamespace(
        action=CIOAction.BUY,
        candidate_identifier="candidate:abc",
        as_of=NOW,
        confidence=0.75,
        rationale=("candidate improves portfolio after costs",),
        evidence_identifiers=("decision-evidence",),
    )
    construction = SimpleNamespace(
        target_weights=(("ABC", 0.10),),
        expected_return_after_cost=0.08,
        expected_return_improvement=0.01,
    )
    snapshot = SimpleNamespace(
        best_alternative_identifier="cash",
        effective_opportunity_cost=0.04,
        opportunity_edge=0.11,
        evidence_identifiers=("snapshot-evidence",),
    )
    packet = build_candidate_decision_intelligence_packet(
        cycle_identifier="cycle-1",
        candidate=candidate,
        specialist_context=context,
        portfolio=portfolio,
        decision=decision,
        construction=construction,
        evaluation_snapshot=snapshot,
    )
    assert packet.objective.portfolio_value == 250_000.0
    # Whole-portfolio construction improvement remains global.
    assert packet.objective.expected_dollar_value_added == pytest.approx(2_500.0)
    # Candidate attribution uses 10% weight change x 11% opportunity edge.
    assert packet.opportunity.marginal_portfolio_improvement == pytest.approx(0.011)
    assert packet.opportunity.expected_dollar_value_added == pytest.approx(2_750.0)
    assert packet.opportunity.best_alternative_identifier == "cash"
    assert packet.opportunity.proposed_target_weight == pytest.approx(0.10)
    assert packet.investment_authority is False
