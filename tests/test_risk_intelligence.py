from __future__ import annotations

from dataclasses import replace

import pytest

from application.cio_cycle import CandidateExposureProfile
from portfolio.risk_intelligence import (
    CandidateRiskIntelligenceEngine,
    CandidateRiskPolicy,
    JointCandidateIntelligenceEngine,
    JointCandidateRelation,
)
from tests.test_canonical_cio_cycle import _candidate


def test_candidate_risk_quantifies_failure_severity_and_expected_shortfall() -> None:
    candidate = _candidate("TAIL", base_return=0.12, bull_return=0.30, bear_return=-0.40)

    assessment = CandidateRiskIntelligenceEngine().assess(
        candidate,
        portfolio_value=250_000.0,
        proposed_weight=0.05,
        alternative_return=0.04,
        invalidation_clarity=0.80,
    )

    assert assessment.probability_of_loss == pytest.approx(
        candidate.bear_case_probability
    )
    assert assessment.conditional_loss_given_failure == pytest.approx(-0.40)
    assert assessment.expected_shortfall == pytest.approx(-0.40)
    assert assessment.expected_time_underwater_days > 0.0
    assert assessment.expected_recovery_days > assessment.expected_time_underwater_days
    assert assessment.upside_to_conditional_downside > 0.0


def test_stress_liquidity_blocks_only_when_exit_horizon_is_unacceptable() -> None:
    candidate = _candidate("ILLIQUID")
    candidate = replace(
        candidate,
        instrument=replace(
            candidate.instrument,
            average_daily_dollar_volume=50_000.0,
        ),
    )
    engine = CandidateRiskIntelligenceEngine(
        CandidateRiskPolicy(maximum_stressed_days_to_exit=5.0)
    )

    assessment = engine.assess(
        candidate,
        portfolio_value=250_000.0,
        proposed_weight=0.10,
        alternative_return=0.04,
    )

    assert assessment.stressed_days_to_exit > 5.0
    assert not assessment.liquid_under_stress
    assert any("Stress liquidity" in item for item in assessment.hard_blocks)


def test_ordinary_uncertainty_remains_a_sizing_and_monitoring_diagnostic() -> None:
    candidate = _candidate("UNCERTAIN", base_return=0.10, bull_return=0.22, bear_return=-0.18)
    candidate = replace(
        candidate,
        critical_assumptions=(
            "Demand persists",
            "Margins remain stable",
            "Valuation does not compress materially",
        ),
    )

    assessment = CandidateRiskIntelligenceEngine().assess(
        candidate,
        portfolio_value=250_000.0,
        proposed_weight=0.03,
        alternative_return=0.04,
        invalidation_clarity=0.30,
    )

    assert assessment.fragility_score > 0.0
    assert assessment.edge_half_life_days > 0.0
    assert not assessment.hard_blocks


def test_joint_engine_identifies_complementary_pair() -> None:
    first = _candidate("GROWTH")
    second = _candidate("DEFENSIVE")
    profiles = (
        CandidateExposureProfile(
            candidate_identifier=first.identifier,
            sector="Technology",
            factor_loadings=(("growth", 1.0), ("duration", 0.8)),
            correlation_bucket="GROWTH",
        ),
        CandidateExposureProfile(
            candidate_identifier=second.identifier,
            sector="Defensive",
            factor_loadings=(("growth", -0.8), ("duration", -0.6)),
            correlation_bucket="DEFENSIVE",
        ),
    )
    engine = CandidateRiskIntelligenceEngine()
    risks = tuple(
        engine.assess(
            item,
            portfolio_value=250_000.0,
            proposed_weight=0.04,
            alternative_return=0.04,
        )
        for item in (first, second)
    )

    relation = JointCandidateIntelligenceEngine().assess(
        (first, second),
        risks,
        profiles,
    )[0]

    assert relation.relation is JointCandidateRelation.COMPLEMENTARY
    assert relation.preferred_candidate_identifier is None
    assert relation.tail_dependence < 0.35


def test_joint_engine_identifies_dominated_same_bucket_candidate() -> None:
    strong = _candidate("STRONG", base_return=0.18, bull_return=0.35, bear_return=-0.12)
    weak = _candidate("WEAK", base_return=0.04, bull_return=0.10, bear_return=-0.35)
    profiles = (
        CandidateExposureProfile(
            candidate_identifier=strong.identifier,
            sector="Technology",
            factor_loadings=(("equity_beta", 1.0), ("growth", 0.8)),
            correlation_bucket="TECH",
        ),
        CandidateExposureProfile(
            candidate_identifier=weak.identifier,
            sector="Technology",
            factor_loadings=(("equity_beta", 0.95), ("growth", 0.75)),
            correlation_bucket="TECH",
        ),
    )
    engine = CandidateRiskIntelligenceEngine()
    risks = tuple(
        engine.assess(
            item,
            portfolio_value=250_000.0,
            proposed_weight=0.05,
            alternative_return=0.04,
        )
        for item in (strong, weak)
    )

    relation = JointCandidateIntelligenceEngine().assess(
        (strong, weak),
        risks,
        profiles,
    )[0]

    assert relation.relation in {
        JointCandidateRelation.MUTUALLY_EXCLUSIVE,
        JointCandidateRelation.DOMINATED,
    }
    assert relation.preferred_candidate_identifier == strong.identifier
