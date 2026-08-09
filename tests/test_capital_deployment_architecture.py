"""Regression coverage for research breadth and capital-deployment boundaries."""

from cio import CandidateAssetClass
from evaluation.persistent_cash import _capital_deployment_review
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryPolicy,
)
from opportunity.engine import OpportunityQualificationPolicy
from portfolio.construction_models import PortfolioConstructionPolicy


def test_research_attention_is_broader_than_final_conviction() -> None:
    policy = OpportunityQualificationPolicy()

    assert policy.research_return_shortfall_tolerance == 0.03
    assert policy.research_robust_edge_shortfall_tolerance == 0.03
    assert policy.minimum_research_probability_of_success == 0.30
    assert policy.minimum_research_probability_of_success < policy.minimum_probability_of_success
    assert policy.minimum_research_net_expected_return < policy.minimum_net_expected_return


def test_discovery_does_not_impose_tiny_routine_position_caps() -> None:
    policy = ComprehensiveMarketDiscoveryPolicy()

    assert policy.maximum_weight(CandidateAssetClass.INTERNATIONAL_EQUITY) == 0.10
    assert policy.maximum_weight(CandidateAssetClass.FX) == 0.10
    assert policy.maximum_weight(CandidateAssetClass.CRYPTO) == 0.05
    assert policy.maximum_weight(CandidateAssetClass.FIXED_INCOME) == 0.10
    assert policy.maximum_weight(CandidateAssetClass.OPTION) == 0.03
    assert policy.maximum_weight(CandidateAssetClass.FUTURE) == 0.05
    assert PortfolioConstructionPolicy().maximum_position_weight == 0.10


def test_high_cash_and_narrow_decision_funnel_triggers_review_only() -> None:
    decision_ratio, specialist_ratio, required, reason = _capital_deployment_review(
        cash_weight=0.92,
        eligible_count=500,
        decision_eligible_count=1,
        specialist_review_count=0,
    )

    assert decision_ratio == 0.002
    assert specialist_ratio == 0.0
    assert required is True
    assert reason is not None and "review discovery" in reason


def test_high_cash_and_weak_specialist_conversion_triggers_review_only() -> None:
    _, specialist_ratio, required, reason = _capital_deployment_review(
        cash_weight=0.88,
        eligible_count=100,
        decision_eligible_count=20,
        specialist_review_count=0,
    )

    assert specialist_ratio == 0.0
    assert required is True
    assert reason is not None and "six-specialist review" in reason


def test_cash_review_never_fires_from_cash_level_alone() -> None:
    _, _, required, reason = _capital_deployment_review(
        cash_weight=0.60,
        eligible_count=500,
        decision_eligible_count=1,
        specialist_review_count=0,
    )

    assert required is False
    assert reason is None
