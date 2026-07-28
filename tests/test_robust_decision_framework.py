"""Tests for compounding-aware candidate robustness and outcome learning."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    RobustCandidateAssessor,
)
from evaluation import (
    DecisionLearningEvaluator,
    DecisionLearningObservation,
    DecisionLearningState,
)
from opportunity import AlternativeKind, AlternativeUse, OpportunityEngine, OpportunitySetContext


AS_OF = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _candidate(
    symbol: str = "ROBUST",
    *,
    base: float = 0.12,
    bull: float = 0.30,
    bear: float = -0.15,
    base_probability: float = 0.55,
    bull_probability: float = 0.25,
    bear_probability: float = 0.20,
    stated_success: float = 0.68,
    evidence: float = 0.92,
    opportunity_cost: float = 0.04,
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=CandidateInstrument(
            instrument_id=f"instrument:{symbol.lower()}",
            symbol=symbol,
            name=f"{symbol} Corporation",
            asset_class=CandidateAssetClass.US_EQUITY,
            venue="NASDAQ",
            country_code="US",
            average_daily_dollar_volume=50_000_000,
            data_age_hours=1.0,
            analytical_coverage=0.95,
            security_master_snapshot_identifier="security-master:test:v1",
            security_master_record_identifiers=("security-master-record:test",),
        ),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=base,
        bull_case_return=bull,
        bear_case_return=bear,
        base_case_probability=base_probability,
        bull_case_probability=bull_probability,
        bear_case_probability=bear_probability,
        estimated_fair_value=120.0,
        expected_upside=bull,
        expected_downside=bear,
        probability_of_success=stated_success,
        primary_catalysts=("Earnings revisions improved",),
        key_risks=("Demand may weaken",),
        critical_assumptions=("Margins remain resilient",),
        invalidation_conditions=("Forward estimates decline",),
        supporting_evidence=("Cash flow accelerated",),
        contradictory_evidence=("Inventory remains elevated",),
        evidence_quality=EvidenceQuality(
            reliability=evidence,
            freshness=evidence,
            relevance=evidence,
            independence=evidence,
            completeness=evidence,
            point_in_time_integrity=evidence,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=opportunity_cost,
        expected_portfolio_contribution=0.012,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("Estimate revisions",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(f"evidence:{symbol.lower()}",),
        model_versions=("decision-model.v1",),
    )


def _context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-set:test",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:treasury-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )


def test_robust_candidate_clears_geometric_and_stress_controls() -> None:
    assessment = RobustCandidateAssessor().assess(
        _candidate(),
        alternative_return=0.04,
    )

    assert assessment.passed
    assert assessment.annualized_geometric_return > 0.04
    assert assessment.robust_edge > 0.0
    assert assessment.stressed_edge >= 0.0
    assert assessment.probability_of_loss == pytest.approx(0.20)


def test_inconsistent_success_probability_is_rejected_even_with_high_arithmetic_return() -> None:
    fragile = _candidate(
        "FRAGILE",
        base=0.30,
        bull=0.90,
        bear=-0.30,
        base_probability=0.35,
        bull_probability=0.25,
        bear_probability=0.40,
        stated_success=0.95,
    )

    qualification = OpportunityEngine().qualify(fragile, _context())

    assert not qualification.qualified
    assert any(
        "inconsistent with the disclosed scenarios" in reason
        for reason in qualification.reasons
    )


def test_malformed_scenario_order_is_fail_closed() -> None:
    malformed = _candidate(base=0.25, bull=0.10, bear=-0.10)

    assessment = RobustCandidateAssessor().assess(
        malformed,
        alternative_return=0.04,
    )

    assert not assessment.passed
    assert any("scenario ordering" in reason for reason in assessment.reasons)


def test_short_horizon_returns_are_compared_on_an_annualized_geometric_basis() -> None:
    candidate = replace(
        _candidate(base=0.04, bull=0.08, bear=-0.03),
        decision_horizon_days=90,
        review_at=AS_OF + timedelta(days=15),
    )

    assessment = RobustCandidateAssessor().assess(
        candidate,
        alternative_return=0.04,
    )

    assert assessment.annualized_geometric_return > candidate.net_expected_return


def _observation(index: int, *, negative: bool = False) -> DecisionLearningObservation:
    decision_at = AS_OF + timedelta(days=index * 10)
    success = index % 5 != 0
    value_added = -0.03 if negative else (0.02 if index % 2 else 0.03)
    return DecisionLearningObservation(
        identifier=f"learning-observation:{index}",
        decision_identifier=f"decision:{index}",
        evaluation_identifier=f"evaluation:{index}",
        model_version="decision-model.v1",
        decision_policy_version="cio-synthesis.v2",
        asset_class="us_equity" if index % 2 else "fixed_income",
        market_regime="expansion" if index % 3 else "contraction",
        decision_at=decision_at,
        evaluated_at=decision_at + timedelta(days=31),
        horizon_days=30,
        forecast_probability=0.70,
        realized_success=success,
        value_added_vs_best_alternative=value_added,
        value_added_vs_cash=value_added + 0.005,
        implementation_cost_return=0.003,
        maximum_drawdown=-0.15,
        candidate_count_considered=1,
        evidence_identifiers=(f"evidence:{index}",),
    )


def test_decision_learning_requires_sufficient_out_of_sample_breadth() -> None:
    report = DecisionLearningEvaluator().evaluate(
        tuple(_observation(index) for index in range(5)),
        generated_at=AS_OF + timedelta(days=500),
    )

    assert report.state is DecisionLearningState.INSUFFICIENT_EVIDENCE
    assert not report.automatic_model_change
    assert not report.real_money_authorized
    assert not report.performance_claims_permitted


def test_positive_calibrated_outcomes_become_eligible_only_for_human_review() -> None:
    report = DecisionLearningEvaluator().evaluate(
        tuple(_observation(index) for index in range(40)),
        generated_at=AS_OF + timedelta(days=800),
    )

    assert report.state is DecisionLearningState.ELIGIBLE_FOR_GOVERNANCE_REVIEW
    assert report.adjusted_lower_bound_value_added > 0.0
    assert report.posterior_success_lower_bound > 0.50
    assert report.mean_value_added_vs_best_alternative > 0.0
    assert not report.automatic_model_change


def test_material_negative_value_added_suspends_model_version() -> None:
    report = DecisionLearningEvaluator().evaluate(
        tuple(_observation(index, negative=True) for index in range(40)),
        generated_at=AS_OF + timedelta(days=800),
    )

    assert report.state is DecisionLearningState.SUSPEND
    assert report.mean_value_added_vs_best_alternative < 0.0


def test_learning_report_cannot_mix_model_versions() -> None:
    observations = list(_observation(index) for index in range(40))
    observations[-1] = replace(observations[-1], model_version="decision-model.v2")

    with pytest.raises(ValueError, match="mix model versions"):
        DecisionLearningEvaluator().evaluate(
            tuple(observations),
            generated_at=AS_OF + timedelta(days=800),
        )
