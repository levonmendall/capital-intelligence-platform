"""Tests for layered mature all-market screening admission."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    UniverseDisposition,
)
from opportunity import (
    AnalysisLane,
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
)
from screening import (
    FullUniverseScreeningOrchestrator,
    FullUniverseScreeningRequest,
    MatureMarketUniverseBuilder,
)
from screening.admission import (
    ResearchReviewOpportunityEngine,
    ScreeningAdmissionPolicy,
)
from screening.orchestration import (
    FullUniverseScreeningOrchestrator as StrictFullUniverseScreeningOrchestrator,
)


AS_OF = datetime(2026, 8, 1, 18, tzinfo=timezone.utc)


def _instrument(
    symbol: str,
    *,
    asset_class: CandidateAssetClass,
) -> CandidateInstrument:
    return CandidateInstrument(
        instrument_id=f"instrument:{symbol.lower()}",
        symbol=symbol,
        name=f"{symbol} instrument",
        asset_class=asset_class,
        venue=("COINBASE" if asset_class is CandidateAssetClass.CRYPTO else "NASDAQ"),
        country_code="US",
        average_daily_dollar_volume=50_000_000.0,
        data_age_hours=1.0,
        analytical_coverage=0.95,
        security_master_snapshot_identifier="security-master:mature-market:test",
        security_master_record_identifiers=("record:mature-market:test",),
        instrument_type=("spot" if asset_class is CandidateAssetClass.CRYPTO else "common_stock"),
    )


def _candidate(
    symbol: str,
    *,
    asset_class: CandidateAssetClass,
) -> CandidateDecisionRecord:
    evidence = EvidenceQuality(
        reliability=0.92,
        freshness=0.92,
        relevance=0.92,
        independence=0.92,
        completeness=0.92,
        point_in_time_integrity=0.92,
    )
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}:2026-08-01",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=_instrument(symbol, asset_class=asset_class),
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=0.12,
        bull_case_return=0.30,
        bear_case_return=-0.15,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=120.0,
        expected_upside=0.30,
        expected_downside=-0.15,
        probability_of_success=0.68,
        primary_catalysts=("Forward conditions improved",),
        key_risks=("Demand could weaken",),
        critical_assumptions=("Market structure remains orderly",),
        invalidation_conditions=("Expected return falls below cash",),
        supporting_evidence=("Point-in-time evidence supports the scenario",),
        contradictory_evidence=("Volatility remains elevated",),
        evidence_quality=evidence,
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.012,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("Expected-return revision",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=(f"evidence:{symbol.lower()}",),
        model_versions=("mature-market-test.v1",),
    )


def _context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-set:mature-market:2026-08-01",
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


def test_public_screening_path_uses_mature_market_wrappers() -> None:
    assert issubclass(
        FullUniverseScreeningOrchestrator,
        StrictFullUniverseScreeningOrchestrator,
    )
    assert FullUniverseScreeningRequest.__dataclass_fields__[
        "require_complete_metric_coverage"
    ].default is False
    assert isinstance(MatureMarketUniverseBuilder().policy, ScreeningAdmissionPolicy)


def test_screening_admission_is_broad_but_not_investment_authority() -> None:
    assessment = ScreeningAdmissionPolicy().evaluate(
        _instrument("BTC", asset_class=CandidateAssetClass.CRYPTO),
        as_of=AS_OF,
    )

    assert assessment.disposition is UniverseDisposition.DIRECT_RECOMMENDATION
    assert assessment.policy_version == "screening-admission.v1"
    assert any("screening only" in reason for reason in assessment.reasons)
    assert any("no committee" in reason for reason in assessment.reasons)


def test_strict_engine_still_rejects_unapproved_market_for_investment() -> None:
    queue = OpportunityEngine().build_queue(
        (_candidate("BTC", asset_class=CandidateAssetClass.CRYPTO),),
        _context(),
    )

    assert not queue.ranked
    assert queue.rejected
    assert not queue.rejected[0].universe.direct_recommendation_allowed


def test_research_engine_routes_strong_unapproved_market_to_exploration() -> None:
    queue = ResearchReviewOpportunityEngine().build_queue(
        (_candidate("BTC", asset_class=CandidateAssetClass.CRYPTO),),
        _context(),
    )

    assert len(queue.ranked) == 1
    qualification = queue.ranked[0].qualification
    assert qualification.analysis_lane is AnalysisLane.EXPLORATION
    assert not qualification.universe.direct_recommendation_allowed
    assert any("research-only" in reason for reason in qualification.reasons)
    assert any("allocation remains prohibited" in reason for reason in qualification.reasons)


def test_unclassified_instruments_remain_fail_closed() -> None:
    assessment = ScreeningAdmissionPolicy().evaluate(
        _instrument("UNKNOWN", asset_class=CandidateAssetClass.OTHER),
        as_of=AS_OF,
    )

    assert assessment.disposition is UniverseDisposition.INELIGIBLE
