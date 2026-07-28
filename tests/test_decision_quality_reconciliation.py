"""Regression coverage for cross-asset decision-quality reconciliation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from application import (
    AssetSpecificEvidencePacket,
    MetricDirection,
    OriginatingFactObservation,
)
from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    IndependentSpecialistPacket,
    PayoffDistributionPoint,
    RobustCandidateAssessor,
    SpecialistAnalysis,
    SpecialistPosition,
    SpecialistReturnReconciler,
    SpecialistRole,
)
from evaluation import (
    DecisionLearningEvaluator,
    DecisionLearningObservation,
    DecisionLearningSegmentReport,
    DecisionLearningState,
)
from opportunity import (
    AnalysisLane,
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
)

AS_OF = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _candidate(
    symbol: str = "QUALITY",
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.US_EQUITY,
    current_weight: float = 0.0,
    base: float = 0.12,
    bull: float = 0.30,
    bear: float = -0.15,
    horizon_days: int = 365,
    contribution: float = 0.01,
    payoff_distribution: tuple[PayoffDistributionPoint, ...] = (),
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier=f"candidate:{symbol.lower()}",
        as_of=AS_OF,
        schema_version="candidate-decision.v2",
        instrument=CandidateInstrument(
            instrument_id=f"instrument:{symbol.lower()}",
            symbol=symbol,
            name=f"{symbol} instrument",
            asset_class=asset_class,
            venue="CBOE" if asset_class is CandidateAssetClass.OPTION else "NASDAQ",
            country_code="US",
            average_daily_dollar_volume=50_000_000,
            data_age_hours=1.0,
            analytical_coverage=0.95,
            security_master_snapshot_identifier="security-master:test:v1",
            security_master_record_identifiers=("security-master-record:test",),
            instrument_type="option" if asset_class is CandidateAssetClass.OPTION else "common_stock",
            uses_derivatives=asset_class is CandidateAssetClass.OPTION,
        ),
        current_price=100.0,
        decision_horizon_days=horizon_days,
        base_case_return=base,
        bull_case_return=bull,
        bear_case_return=bear,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=120.0,
        expected_upside=bull,
        expected_downside=bear,
        probability_of_success=0.99,
        primary_catalysts=("Catalyst",),
        key_risks=("Risk",),
        critical_assumptions=("Assumption",),
        invalidation_conditions=("Invalidation",),
        supporting_evidence=("Evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(
            reliability=0.92,
            freshness=0.92,
            relevance=0.92,
            independence=0.92,
            completeness=0.92,
            point_in_time_integrity=0.92,
        ),
        liquidity_score=0.95,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=contribution,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.10,
        monitoring_indicators=("Indicator",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=("origin:candidate",),
        model_versions=("decision-model.v2",),
        payoff_distribution=payoff_distribution,
    )


def _context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity:test",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash:t-bills",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )


def _analysis(
    candidate: CandidateDecisionRecord,
    role: SpecialistRole,
    *,
    impact: float = 0.0,
    confidence: float = 0.8,
    origin: str | None = None,
    position: SpecialistPosition = SpecialistPosition.SUPPORTIVE,
) -> SpecialistAnalysis:
    kwargs: dict[str, object] = {}
    if role is SpecialistRole.PORTFOLIO_RISK:
        kwargs.update(recommended_position_weight=0.05, funding_source="cash")
    return SpecialistAnalysis(
        candidate_identifier=candidate.identifier,
        role=role,
        completed_at=AS_OF + timedelta(minutes=list(SpecialistRole).index(role) + 1),
        independent_first_pass=True,
        position=position,
        conclusion=f"{role.value} conclusion",
        expected_return_impact=impact,
        confidence=confidence,
        supporting_evidence=(f"support:{role.value}",),
        contradictory_evidence=(),
        critical_assumptions=("Assumption",),
        risks=("Risk",),
        limitations=(),
        change_conditions=("Review",),
        evidence_origin_identifiers=((origin,) if origin else (f"origin:{role.value}",)),
        **kwargs,
    )


def _packet(
    candidate: CandidateDecisionRecord,
    *,
    duplicate_origins: bool,
    baseline_origin: bool = False,
) -> IndependentSpecialistPacket:
    shared = (
        "origin:candidate"
        if baseline_origin
        else ("origin:shared" if duplicate_origins else None)
    )
    return IndependentSpecialistPacket(
        candidate_identifier=candidate.identifier,
        analyses=(
            _analysis(candidate, SpecialistRole.MACRO_ECONOMIC, impact=0.06, origin=shared),
            _analysis(candidate, SpecialistRole.MARKET, impact=0.06, origin=shared),
            _analysis(candidate, SpecialistRole.CROSS_ASSET_FORECAST, impact=0.0),
            _analysis(candidate, SpecialistRole.FUNDAMENTAL_VALUATION, impact=0.06, origin=shared),
            _analysis(candidate, SpecialistRole.PORTFOLIO_RISK),
            _analysis(candidate, SpecialistRole.EVIDENCE_GOVERNANCE),
        ),
    )


def test_current_holding_always_enters_mandatory_review_lane() -> None:
    holding = _candidate(
        "WEAKHOLD",
        current_weight=0.08,
        base=-0.08,
        bull=0.02,
        bear=-0.35,
        contribution=-0.02,
    )

    queue = OpportunityEngine().build_queue((holding,), _context())

    assert len(queue.ranked) == 1
    assert queue.ranked[0].qualification.analysis_lane is AnalysisLane.HOLDING_REVIEW
    assert queue.holding_reviews == queue.ranked
    assert not queue.has_qualified_opportunity
    assert any("mandatory" in reason for reason in queue.ranked[0].qualification.reasons)


def test_candidate_supplied_portfolio_contribution_has_no_screening_authority() -> None:
    positive = _candidate("SAMEA", contribution=0.50)
    negative = replace(
        positive,
        identifier="candidate:sameb",
        instrument=replace(
            positive.instrument,
            instrument_id="instrument:sameb",
            symbol="SAMEB",
            name="Same B",
        ),
        expected_portfolio_contribution=-0.50,
    )

    queue = OpportunityEngine().build_queue((positive, negative), _context())

    assert len(queue.ranked) == 2
    components = {
        item.candidate.instrument.symbol: next(
            component for component in item.components if component.name == "portfolio_contribution"
        )
        for item in queue.ranked
    }
    assert components["SAMEA"].raw_value == components["SAMEB"].raw_value == 0.0
    assert components["SAMEA"].normalized_score == components["SAMEB"].normalized_score == 0.5


def test_reconciliation_derives_probability_from_adjusted_distribution() -> None:
    candidate = _candidate("RECON", horizon_days=90)

    reconciliation = SpecialistReturnReconciler().reconcile(
        candidate,
        _packet(candidate, duplicate_origins=False),
        alternative_return=0.04,
    )

    expected = sum(point.total_return * point.probability for point in reconciliation.outcomes) - candidate.implementation_cost_return
    derived_probability = sum(
        point.probability
        for point in reconciliation.outcomes
        if point.total_return - candidate.implementation_cost_return
        > reconciliation.horizon_alternative_return
    )
    assert reconciliation.expected_return == pytest.approx(expected)
    assert reconciliation.probability_of_success == pytest.approx(derived_probability)
    assert reconciliation.probability_of_success != candidate.probability_of_success


def test_duplicate_evidence_origins_reduce_specialist_adjustments() -> None:
    candidate = _candidate("ORIGINS")

    independent = SpecialistReturnReconciler().reconcile(
        candidate,
        _packet(candidate, duplicate_origins=False),
        alternative_return=0.04,
    )
    duplicated = SpecialistReturnReconciler().reconcile(
        candidate,
        _packet(candidate, duplicate_origins=True),
        alternative_return=0.04,
    )

    assert sum(item.applied_impact for item in duplicated.adjustments) < sum(
        item.applied_impact for item in independent.adjustments
    )
    assert duplicated.evidence_origin_count < independent.evidence_origin_count


def test_specialist_evidence_already_used_by_baseline_is_discounted() -> None:
    candidate = _candidate("BASELINE")

    novel = SpecialistReturnReconciler().reconcile(
        candidate,
        _packet(candidate, duplicate_origins=False),
        alternative_return=0.04,
    )
    repeated = SpecialistReturnReconciler().reconcile(
        candidate,
        _packet(
            candidate,
            duplicate_origins=False,
            baseline_origin=True,
        ),
        alternative_return=0.04,
    )

    assert sum(item.applied_impact for item in repeated.adjustments) < sum(
        item.applied_impact for item in novel.adjustments
    )


def test_options_require_and_preserve_nonlinear_payoff_distribution() -> None:
    with pytest.raises(ValueError, match="simulated payoff distribution"):
        _candidate("OPT", asset_class=CandidateAssetClass.OPTION)

    distribution = (
        PayoffDistributionPoint("total_loss", -1.0, 0.35),
        PayoffDistributionPoint("small_gain", 0.20, 0.35),
        PayoffDistributionPoint("large_gain", 1.50, 0.30),
    )
    option = _candidate(
        "OPT",
        asset_class=CandidateAssetClass.OPTION,
        payoff_distribution=distribution,
    )

    reconciliation = SpecialistReturnReconciler().reconcile(
        option,
        _packet(option, duplicate_origins=False),
        alternative_return=0.04,
    )

    assert tuple(item.label for item in reconciliation.outcomes) == tuple(
        item.label for item in distribution
    )
    assert len(reconciliation.outcomes) == 3
    robustness = RobustCandidateAssessor().assess(option, alternative_return=0.04)
    assert robustness.probability_of_loss == pytest.approx(0.35)
    assert robustness.effective_probability_of_success == pytest.approx(0.65)


def test_asset_metrics_expose_units_direction_and_horizon() -> None:
    observation = OriginatingFactObservation(
        observation_identifier="obs:1",
        originating_fact_identifier="origin:1",
        source_family="primary",
        source_identifier="source:1",
        observed_at=AS_OF,
        available_at=AS_OF,
    )
    packet = AssetSpecificEvidencePacket(
        identifier="asset-evidence:fx:1",
        screening_cycle_identifier="screening:1",
        candidate_identifier="candidate:fx:1",
        instrument_identifier="instrument:fx:1",
        asset_class=CandidateAssetClass.FX,
        asset_class_approval_identifier="approval:fx:1",
        as_of=AS_OF,
        knowledge_cutoff=AS_OF,
        fresh_until=AS_OF + timedelta(hours=1),
        metrics=(
            ("rate_differential", 0.02),
            ("valuation_signal", 0.10),
            ("liquidity_score", 0.95),
            ("implementation_cost_return", 0.001),
        ),
        valuation_basis=("rate and valuation model",),
        return_drivers=("rate differential",),
        risks=("policy reversal",),
        invalidation_conditions=("rate differential closes",),
        observations=(observation,),
        provider_certification_identifiers=("cert:1",),
        source_versions=(("source", "v1"),),
        model_versions=(("fx-model", "v1"),),
        limitations=("paper only",),
    )

    typed = {item.definition.name: item for item in packet.typed_metrics}
    assert typed["rate_differential"].definition.unit == "annual_return_fraction"
    assert typed["rate_differential"].definition.direction is MetricDirection.CONTEXTUAL
    assert typed["rate_differential"].definition.applicable_horizon == "annual"
    assert typed["valuation_signal"].definition.direction is MetricDirection.HIGHER_IS_BETTER


def _learning_observation(index: int, *, asset_class: str, regime: str) -> DecisionLearningObservation:
    decision_at = AS_OF + timedelta(days=index * 5)
    horizon_days = 30 if asset_class == "us_equity" else 180
    return DecisionLearningObservation(
        identifier=f"observation:{asset_class}:{regime}:{index}",
        decision_identifier=f"decision:{asset_class}:{regime}:{index}",
        evaluation_identifier=f"evaluation:{asset_class}:{regime}:{index}",
        model_version="decision-model.v2",
        decision_policy_version="cio-synthesis.v3",
        asset_class=asset_class,
        market_regime=regime,
        decision_at=decision_at,
        evaluated_at=decision_at + timedelta(days=horizon_days + 1),
        horizon_days=horizon_days,
        forecast_probability=0.90,
        realized_success=True,
        value_added_vs_best_alternative=0.02,
        value_added_vs_cash=0.025,
        implementation_cost_return=0.002,
        maximum_drawdown=-0.10,
        candidate_count_considered=2,
        evidence_identifiers=(f"evidence:{index}",),
    )


def test_learning_reports_keep_asset_horizon_and_regime_segments_separate() -> None:
    observations = tuple(
        _learning_observation(index, asset_class="us_equity", regime="expansion")
        for index in range(12)
    ) + tuple(
        _learning_observation(index + 20, asset_class="fixed_income", regime="contraction")
        for index in range(4)
    )

    reports = DecisionLearningEvaluator().evaluate_segments(
        observations,
        generated_at=AS_OF + timedelta(days=500),
    )

    assert all(isinstance(item, DecisionLearningSegmentReport) for item in reports)
    by_key = {(item.dimension, item.segment): item for item in reports}
    assert by_key[("asset_class", "us_equity")].state is DecisionLearningState.RETAIN
    assert by_key[("asset_class", "fixed_income")].state is DecisionLearningState.INSUFFICIENT_EVIDENCE
    assert ("horizon_bucket", "1-30_days") in by_key
    assert ("horizon_bucket", "91-365_days") in by_key


def test_forecast_specialist_adjustment_is_conservatively_capped() -> None:
    candidate = _candidate("FORECASTCAP")
    packet = IndependentSpecialistPacket(
        candidate_identifier=candidate.identifier,
        analyses=tuple(
            _analysis(
                candidate,
                role,
                impact=(0.50 if role is SpecialistRole.CROSS_ASSET_FORECAST else 0.0),
            )
            for role in SpecialistRole
        ),
    )

    result = SpecialistReturnReconciler().reconcile(
        candidate,
        packet,
        alternative_return=0.04,
    )
    adjustment = next(
        item
        for item in result.adjustments
        if item.role is SpecialistRole.CROSS_ASSET_FORECAST
    )

    assert adjustment.applied_impact == pytest.approx(0.04)
    assert adjustment.applied_impact < adjustment.raw_impact
