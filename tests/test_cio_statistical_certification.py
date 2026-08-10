from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from evaluation.cio_statistical_certification import (
    CIOStatisticalCertificationPolicy,
    WalkForwardObservation,
    build_cio_statistical_certification,
    certify_walk_forward,
)
from operations.comprehensive_decision_intelligence_certification import (
    CertificationState,
    build_comprehensive_decision_intelligence_certification,
)


NOW = datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc)


def _pair(index: int, *, good: bool = True):
    decision = NOW - timedelta(days=90 - index)
    packet = {
        "identifier": f"packet:{index}",
        "as_of": decision.isoformat(),
        "vehicle_asset_class": "US_EQUITY" if index % 2 == 0 else "US_ETF",
        "economic_exposure_class": "US_EQUITY" if index % 2 == 0 else "COMMODITY",
        "cio_confidence": 0.80,
        "source_lineage": [f"evidence:{index}"],
        "explanation": {
            "evidence_identifiers": [f"evidence:{index}"],
            "invalidation_conditions": ["thesis breaks"],
            "bear_case": "bear",
            "base_case": "base",
            "bull_case": "bull",
        },
        "objective": {"portfolio_value": 250_000.0},
        "opportunity": {
            "candidate_expected_return": 0.10,
            "marginal_portfolio_improvement": 0.01,
            "expected_dollar_value_added": 2_500.0,
            "current_weight": 0.0,
            "proposed_target_weight": 0.10,
            "best_alternative_identifier": "cash",
        },
    }
    portfolio_return = 0.06 if good else 0.01
    outcome = {
        "observed_at": (decision + timedelta(days=30)).isoformat(),
        "realized_candidate_return": 0.09 if good else -0.02,
        "realized_portfolio_return": portfolio_return,
        "realized_cash_return": 0.03,
        "realized_best_alternative_return": 0.04,
        "evidence_identifiers": [f"outcome:{index}"],
    }
    return packet, outcome


def _walk(index: int, *, leak: bool = False):
    decision = NOW - timedelta(days=90 - index)
    return WalkForwardObservation(
        identifier=f"walk:{index}",
        decision_as_of=decision,
        knowledge_cutoff=(decision + timedelta(minutes=1) if leak else decision),
        training_window_end=decision - timedelta(days=1),
        provider_available_from=decision - timedelta(days=365),
        outcome_observed_at=decision + timedelta(days=30),
        asset_class="US_EQUITY" if index % 2 == 0 else "US_ETF",
        regime="expansion" if index % 3 else "slowdown",
        confidence_bucket="high",
        horizon_days=30,
        information_completeness=1.0,
    )


def test_walk_forward_fails_closed_on_future_knowledge():
    report = certify_walk_forward((_walk(1), _walk(2, leak=True)))
    assert report.point_in_time_passed is False
    assert report.future_knowledge_violations == ("walk:2",)
    assert report.survivorship_claim_authorized is False


def test_statistical_certification_measures_dollar_value_and_never_promotes_policy():
    pairs = tuple(_pair(index) for index in range(12))
    walks = tuple(_walk(index) for index in range(12))
    report = build_cio_statistical_certification(
        decision_outcome_pairs=pairs,
        walk_forward_observations=walks,
        as_of=NOW,
        policy=CIOStatisticalCertificationPolicy(
            minimum_resolved_decisions=10,
            minimum_distinct_decision_dates=10,
            minimum_asset_classes=2,
            minimum_regimes=2,
            minimum_positive_dollar_value_rate=0.50,
            maximum_candidate_expected_return_mae=0.15,
            maximum_portfolio_improvement_mae=0.10,
        ),
    )
    assert report.statistically_certified is True
    assert report.mean_excess_return_vs_cash > 0.0
    assert report.mean_excess_return_vs_best_alternative > 0.0
    assert report.cumulative_dollar_value_added_vs_best_alternative > 0.0
    assert report.expected_realized_rank_correlation is not None
    assert report.performance_claim_authorized is False
    assert report.policy_change_authorized is False
    assert report.investment_authority is False


def test_small_sample_cannot_claim_statistical_edge():
    report = build_cio_statistical_certification(
        decision_outcome_pairs=(_pair(1),),
        walk_forward_observations=(_walk(1),),
        as_of=NOW,
    )
    assert report.statistically_certified is False
    assert dict(report.gates)["resolved_decision_count"] is False
    assert report.performance_claim_authorized is False


def test_comprehensive_certification_separates_structural_and_empirical_readiness():
    report = build_comprehensive_decision_intelligence_certification(
        as_of=NOW,
        statistical_report=None,
        information_gap_audit={
            "unresolved_domains": ["analyst_estimates_revisions"],
            "decision_certified_domains": ["filings_corporate_disclosures"],
        },
        all_market_runtime_certified=True,
        six_specialist_path_certified=True,
        cio_only_authority_certified=True,
        construction_certified=True,
        paper_execution_reconciliation_certified=True,
        decision_explanation_certified=True,
        causal_resolution_available=True,
        expectations_resolution_available=True,
        portfolio_risk_synthesis_available=True,
        atomic_relative_value_execution_certified=False,
    )
    assert report.state is CertificationState.EMPIRICAL_EVIDENCE_PENDING
    assert report.blocking_failures == ()
    assert "statistical_edge" in report.empirical_pending
    assert "decision_information_depth" in report.empirical_pending
    assert report.public_performance_claim_authorized is False
    assert report.automatic_policy_promotion_authorized is False
    assert report.investment_authority is False


def test_structural_failure_blocks_certification_even_with_empirical_components():
    report = build_comprehensive_decision_intelligence_certification(
        as_of=NOW,
        statistical_report=None,
        information_gap_audit={"unresolved_domains": [], "decision_certified_domains": ["all"]},
        all_market_runtime_certified=False,
        six_specialist_path_certified=True,
        cio_only_authority_certified=True,
        construction_certified=True,
        paper_execution_reconciliation_certified=True,
        decision_explanation_certified=True,
        causal_resolution_available=True,
        expectations_resolution_available=True,
        portfolio_risk_synthesis_available=True,
        atomic_relative_value_execution_certified=True,
    )
    assert report.state is CertificationState.BLOCKED
    assert "all_market_runtime" in report.blocking_failures
