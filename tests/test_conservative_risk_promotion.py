from __future__ import annotations

from datetime import timedelta

from governance.analytical_promotion import (
    AnalyticalPromotionCertification,
    ConservativeAnalyticalPromotion,
    ConservativeRiskOverlay,
)
from portfolio.construction_api import PortfolioConstructionPolicy
from tests.cio_test_fixtures import AS_OF


def test_certified_dynamic_risk_can_only_tighten_construction_policy() -> None:
    policy = PortfolioConstructionPolicy(
        maximum_expected_shortfall=-0.12,
        maximum_stressed_drawdown=-0.20,
        maximum_liquidity_adjusted_loss=-0.22,
        maximum_position_weight=0.10,
        maximum_turnover=0.20,
    )
    overlay = ConservativeRiskOverlay(
        identifier="dynamic-risk:certified:v1",
        as_of=AS_OF - timedelta(minutes=5),
        maximum_expected_shortfall=-0.09,
        maximum_stressed_drawdown=-0.16,
        maximum_liquidity_adjusted_loss=-0.18,
        maximum_position_weight_ceiling=0.08,
        maximum_turnover_ceiling=0.15,
        evidence_identifiers=("risk:dynamic-covariance", "risk:stress-replay"),
    )
    certification = AnalyticalPromotionCertification(
        identifier="promotion:dynamic-risk:v1",
        artifact_identifier=overlay.identifier,
        certified_at=AS_OF - timedelta(minutes=1),
        valid_until=AS_OF + timedelta(days=1),
        knowledge_cutoff=AS_OF - timedelta(minutes=5),
        historical_replay_passed=True,
        point_in_time_passed=True,
        calibration_passed=True,
        decision_certified=True,
        evidence_identifiers=("certification:dynamic-risk",),
    )

    promoted = ConservativeAnalyticalPromotion.apply_construction_risk_overlay(
        policy,
        overlay,
        certification,
        as_of=AS_OF,
    )

    assert promoted.maximum_expected_shortfall == -0.09
    assert promoted.maximum_expected_shortfall >= policy.maximum_expected_shortfall
    assert promoted.maximum_stressed_drawdown == -0.16
    assert promoted.maximum_stressed_drawdown >= policy.maximum_stressed_drawdown
    assert promoted.maximum_liquidity_adjusted_loss == -0.18
    assert promoted.maximum_liquidity_adjusted_loss >= policy.maximum_liquidity_adjusted_loss
    assert promoted.maximum_position_weight == 0.08
    assert promoted.maximum_position_weight <= policy.maximum_position_weight
    assert promoted.maximum_turnover == 0.15
    assert promoted.maximum_turnover <= policy.maximum_turnover


def test_risk_promotion_never_relaxes_stricter_existing_policy() -> None:
    policy = PortfolioConstructionPolicy(
        maximum_expected_shortfall=-0.08,
        maximum_stressed_drawdown=-0.15,
        maximum_liquidity_adjusted_loss=-0.17,
        maximum_position_weight=0.06,
        maximum_turnover=0.12,
    )
    overlay = ConservativeRiskOverlay(
        identifier="dynamic-risk:looser:v1",
        as_of=AS_OF - timedelta(minutes=5),
        maximum_expected_shortfall=-0.12,
        maximum_stressed_drawdown=-0.20,
        maximum_liquidity_adjusted_loss=-0.22,
        maximum_position_weight_ceiling=0.10,
        maximum_turnover_ceiling=0.20,
        evidence_identifiers=("risk:looser-shadow",),
    )
    certification = AnalyticalPromotionCertification(
        identifier="promotion:dynamic-risk:looser:v1",
        artifact_identifier=overlay.identifier,
        certified_at=AS_OF - timedelta(minutes=1),
        valid_until=AS_OF + timedelta(days=1),
        knowledge_cutoff=AS_OF - timedelta(minutes=5),
        historical_replay_passed=True,
        point_in_time_passed=True,
        calibration_passed=True,
        decision_certified=True,
        evidence_identifiers=("certification:dynamic-risk:looser",),
    )

    promoted = ConservativeAnalyticalPromotion.apply_construction_risk_overlay(
        policy,
        overlay,
        certification,
        as_of=AS_OF,
    )

    assert promoted.maximum_expected_shortfall == policy.maximum_expected_shortfall
    assert promoted.maximum_stressed_drawdown == policy.maximum_stressed_drawdown
    assert promoted.maximum_liquidity_adjusted_loss == policy.maximum_liquidity_adjusted_loss
    assert promoted.maximum_position_weight == policy.maximum_position_weight
    assert promoted.maximum_turnover == policy.maximum_turnover
