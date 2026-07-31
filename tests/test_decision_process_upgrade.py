from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from cio import (
    CIOAction,
    CandidateAssetClass,
    ChiefInvestmentOfficer,
    DecisionPolicyMatrix,
    EvidenceDependency,
    EvidenceVetoCategory,
    PriorDecisionContext,
    ScenarioAdjustment,
    SpecialistPosition,
    SpecialistRole,
    ThesisState,
)
from application.cio_cycle import (
    CandidateExposureProfile,
    CanonicalCIOCycle,
    CyclePortfolioState,
)
from cio.reconciliation import SpecialistReturnReconciler
from evaluation import EvaluationOutcome, PointInTimeDecisionEvaluator
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunityRankingInput,
)
from portfolio.construction_api import (
    PortfolioConstructionEngine,
    PortfolioConstructionPolicy,
    PortfolioScenario,
)
from tests.test_decision_quality_reconciliation import (
    _analysis,
    _candidate,
    _context,
    _packet,
)
from tests.test_point_in_time_evaluation import _cycle, _realized
from tests.test_portfolio_construction_engine import (
    _asset,
    _intent,
    _policy,
    _request,
)


def test_cio_uses_true_best_alternative_and_records_handoff() -> None:
    candidate = _candidate("TRUEALT")
    context = _context()
    context = replace(
        context,
        alternatives=context.alternatives
        + (
            AlternativeUse(
                identifier="candidate:materially-better",
                kind=AlternativeKind.QUALIFIED_CANDIDATE,
                expected_return=0.50,
                implementation_cost_return=0.0,
                evidence_quality=0.95,
                liquidity_score=0.95,
            ),
        ),
    )
    qualification = OpportunityEngine().qualify(candidate, context)
    packet = _packet(candidate, duplicate_origins=False)
    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        packet,
        capital_comparison=qualification.capital_comparison,
    )

    assert decision.best_alternative_identifier == "candidate:materially-better"
    assert decision.effective_opportunity_cost == pytest.approx(
        qualification.effective_opportunity_cost
    )
    assert decision.effective_opportunity_cost < 0.50
    assert "candidate:materially-better" in decision.opportunity_cost
    assert decision.action is not CIOAction.BUY


def test_scenario_reconciliation_preserves_bear_probability_and_path_risk() -> None:
    candidate = _candidate("SCENARIOS")
    packet = _packet(candidate, duplicate_origins=False)
    analyses = []
    for analysis in packet.analyses:
        if analysis.role is SpecialistRole.CROSS_ASSET_FORECAST:
            analysis = replace(
                analysis,
                position=SpecialistPosition.OPPOSED,
                confidence=0.90,
                expected_return_impact=-0.02,
                scenario_adjustments=(
                    ScenarioAdjustment("bear", -0.20, 0.10, -0.15),
                    ScenarioAdjustment("base", -0.02, -0.03, -0.03),
                    ScenarioAdjustment("bull", 0.0, -0.07, 0.0),
                ),
            )
        analyses.append(analysis)
    reconciler = SpecialistReturnReconciler()
    baseline = reconciler.reconcile(candidate, packet, alternative_return=0.04)
    reconciliation = reconciler.reconcile(
        candidate,
        replace(packet, analyses=tuple(analyses)),
        alternative_return=0.04,
    )
    outcomes = {item.label: item for item in reconciliation.outcomes}
    baseline_outcomes = {item.label: item for item in baseline.outcomes}

    assert outcomes["bear"].total_return < baseline_outcomes["bear"].total_return
    assert outcomes["bear"].probability > baseline_outcomes["bear"].probability
    assert outcomes["bull"].total_return != outcomes["bear"].total_return
    assert dict(reconciliation.path_drawdown_by_scenario)["bear"] < 0.0
    assert sum(item.probability for item in reconciliation.outcomes) == pytest.approx(1.0)


def test_dependency_graph_discounts_sources_with_shared_upstream_origin() -> None:
    candidate = replace(
        _candidate("DEPENDENCY"),
        evidence_identifiers=("candidate-derived",),
        evidence_dependencies=(
            EvidenceDependency("candidate-derived", ("raw-filing",)),
        ),
    )
    packet = _packet(candidate, duplicate_origins=False)
    linked = []
    for analysis in packet.analyses:
        if analysis.role is SpecialistRole.MACRO_ECONOMIC:
            analysis = replace(
                analysis,
                evidence_origin_identifiers=("macro-derived",),
                evidence_dependencies=(
                    EvidenceDependency("macro-derived", ("raw-filing",)),
                ),
            )
        linked.append(analysis)
    linked_result = SpecialistReturnReconciler().reconcile(
        candidate,
        replace(packet, analyses=tuple(linked)),
        alternative_return=0.04,
    )
    novel_result = SpecialistReturnReconciler().reconcile(
        candidate,
        packet,
        alternative_return=0.04,
    )
    linked_macro = next(
        item for item in linked_result.adjustments if item.role is SpecialistRole.MACRO_ECONOMIC
    )
    novel_macro = next(
        item for item in novel_result.adjustments if item.role is SpecialistRole.MACRO_ECONOMIC
    )

    assert linked_macro.overlap_discount < novel_macro.overlap_discount
    assert abs(linked_macro.applied_impact) < abs(novel_macro.applied_impact)


def test_forecast_abstention_lowers_coverage_without_creating_dissent() -> None:
    candidate = _candidate("ABSTAIN")
    packet = _packet(candidate, duplicate_origins=False)
    analyses = tuple(
        replace(
            item,
            position=SpecialistPosition.ABSTAIN,
            confidence=0.0,
            expected_return_impact=0.0,
        )
        if item.role is SpecialistRole.CROSS_ASSET_FORECAST
        else item
        for item in packet.analyses
    )
    packet = replace(packet, analyses=analyses)

    assert packet.coverage_ratio == pytest.approx(0.75)
    assert packet.strongest_dissent() is None
    assert packet.opposing == ()
    assert tuple(item.role for item in packet.abstentions) == (
        SpecialistRole.CROSS_ASSET_FORECAST,
    )


def test_hysteresis_defers_first_buy_but_emergency_reduction_bypasses() -> None:
    candidate = _candidate("PERSIST")
    qualification = OpportunityEngine().qualify(candidate, _context())
    packet = _packet(candidate, duplicate_origins=False)
    prior = PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier="decision:prior",
        prior_action=CIOAction.WATCH,
        prior_target_weight=None,
        decided_at=candidate.as_of,
        thesis_state=ThesisState.CANDIDATE,
        consecutive_supportive_cycles=0,
    )
    deferred = ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        packet,
        capital_comparison=qualification.capital_comparison,
        prior_context=prior,
    )
    assert deferred.action is CIOAction.WATCH
    assert deferred.hysteresis_applied

    holding = replace(
        candidate,
        identifier="candidate:persist-holding",
        current_portfolio_weight=0.05,
        base_case_return=-0.15,
        bull_case_return=0.02,
        bear_case_return=-0.50,
        estimated_fair_value=candidate.current_price * 0.85,
    )
    holding_packet = _packet(holding, duplicate_origins=False)
    holding_prior = replace(
        prior,
        candidate_identifier=holding.identifier,
        prior_action=CIOAction.HOLD,
        prior_target_weight=0.05,
        thesis_state=ThesisState.ACTIVE,
        consecutive_opposing_cycles=0,
    )
    holding_qualification = OpportunityEngine().qualify(holding, _context())
    reduced = ChiefInvestmentOfficer().synthesize(
        holding,
        holding_qualification.universe,
        holding_packet,
        capital_comparison=holding_qualification.capital_comparison,
        prior_context=holding_prior,
    )
    assert reduced.action in {CIOAction.REDUCE, CIOAction.EXIT}
    assert not reduced.hysteresis_applied


def test_wrapper_economic_exposure_uses_stricter_policy_profile() -> None:
    wrapper = _candidate("IBIT")
    wrapper = replace(
        wrapper,
        instrument=replace(
            wrapper.instrument,
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.CRYPTO,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )
    ordinary_etf = replace(
        _candidate("VTI"),
        instrument=replace(
            _candidate("VTI").instrument,
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.US_EQUITY,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )

    matrix = DecisionPolicyMatrix()
    wrapper_profile = matrix.resolve(wrapper)
    ordinary_profile = matrix.resolve(ordinary_etf)

    assert "speculative-intermediate" in wrapper_profile.identifier
    assert wrapper_profile.minimum_opportunity_edge > ordinary_profile.minimum_opportunity_edge
    assert wrapper_profile.minimum_probability_of_success > ordinary_profile.minimum_probability_of_success
    assert wrapper_profile.maximum_position_weight < ordinary_profile.maximum_position_weight


def test_persisted_wrapper_without_exposure_metadata_is_still_classified() -> None:
    persisted = _candidate("VIXY")
    persisted = replace(
        persisted,
        instrument=replace(
            persisted.instrument,
            asset_class=CandidateAssetClass.US_ETF,
            economic_exposure_class=CandidateAssetClass.US_ETF,
            replication_method="us-listed-economic-exposure-wrapper",
        ),
    )

    profile = DecisionPolicyMatrix().resolve(persisted)

    assert "speculative-intermediate" in profile.identifier
    assert profile.maximum_position_weight == pytest.approx(0.05)


def test_asset_class_and_horizon_matrix_is_stricter_for_tactical_crypto() -> None:
    equity = _candidate("EQUITY", horizon_days=180)
    crypto = replace(
        _candidate("CRYPTO", horizon_days=20),
        instrument=replace(
            _candidate("CRYPTO", horizon_days=20).instrument,
            asset_class=CandidateAssetClass.CRYPTO,
        ),
    )
    matrix = DecisionPolicyMatrix()
    equity_profile = matrix.resolve(equity)
    crypto_profile = matrix.resolve(crypto)

    assert crypto_profile.minimum_opportunity_edge > equity_profile.minimum_opportunity_edge
    assert crypto_profile.minimum_probability_of_success > equity_profile.minimum_probability_of_success
    assert crypto_profile.maximum_position_weight < equity_profile.maximum_position_weight
    assert crypto_profile.entry_persistence_cycles > equity_profile.entry_persistence_cycles


def test_real_ranking_inputs_affect_portfolio_component() -> None:
    candidate = _candidate("RANK")
    context = replace(
        _context(),
        ranking_inputs=(
            OpportunityRankingInput(
                candidate_identifier=candidate.identifier,
                marginal_portfolio_contribution=0.03,
                diversification_score=0.90,
                thesis_clarity_score=0.85,
                invalidation_clarity_score=0.80,
                forecast_durability_score=0.75,
            ),
        ),
    )
    ranked = OpportunityEngine().build_queue((candidate,), context).ranked[0]
    components = {item.name: item for item in ranked.components}

    assert components["portfolio_contribution"].raw_value == pytest.approx(0.03)
    assert components["portfolio_contribution"].normalized_score > 0.75
    assert components["thesis_clarity"].normalized_score == pytest.approx(0.85)


def test_inaction_is_scored_as_missed_opportunity_or_avoided_loss(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    abstention = replace(
        snapshot,
        action=CIOAction.NO_SUPERIOR_OPPORTUNITY,
        recommended_position_weight=None,
        implemented_position_weight=0.0,
        thesis_identifier=None,
        thesis_assumptions=(),
        thesis_invalidation_conditions=(),
        thesis_monitoring_indicators=(),
    )
    missed = PointInTimeDecisionEvaluator().evaluate(
        abstention,
        _realized(abstention, candidate_return=0.25, implementation_return=0.25),
    )
    avoided = PointInTimeDecisionEvaluator().evaluate(
        abstention,
        _realized(abstention, candidate_return=-0.20, implementation_return=-0.20),
    )

    assert missed.outcome is EvaluationOutcome.MISSED_OPPORTUNITY
    assert avoided.outcome is EvaluationOutcome.AVOIDED_LOSS
    assert missed.forecast_brier_score != missed.decision_confidence_brier_score
    assert missed.scenario_log_score >= 0.0


def test_joint_scenario_controls_remove_tail_worsening_allocation() -> None:
    scenarios = (
        PortfolioScenario(
            "bear", 0.30, 0.02, (("CORE", -0.05), ("TECH", -0.10), ("NEW", -1.0))
        ),
        PortfolioScenario(
            "base", 0.40, 0.03, (("CORE", 0.05), ("TECH", 0.08), ("NEW", 0.30))
        ),
        PortfolioScenario(
            "bull", 0.30, 0.04, (("CORE", 0.10), ("TECH", 0.15), ("NEW", 0.80))
        ),
    )
    request = replace(
        _request(
            intents=(
                _intent(
                    "NEW",
                    target=0.30,
                    maximum_position_weight=0.30,
                    expected_return=0.40,
                ),
            )
        ),
        scenarios=scenarios,
    )
    result = PortfolioConstructionEngine(
        _policy(
            maximum_stressed_drawdown=-0.08,
            maximum_expected_shortfall=-0.08,
            maximum_liquidity_adjusted_loss=-0.10,
        )
    ).construct(request)

    assert not result.trades
    assert any("joint portfolio scenario controls" in item for item in result.blocks)
    assert result.scenario_metrics_after == result.scenario_metrics_before


def test_multi_start_portfolio_search_selects_superior_candidate() -> None:
    request = _request(
        cash=0.10,
        positions=(_asset("CORE", 0.90, funding_eligible=False),),
        intents=(
            _intent("LOW", target=0.08, expected_return=0.12, opportunity_edge=0.08, rank=1),
            _intent("HIGH", target=0.08, expected_return=0.30, opportunity_edge=0.26, rank=2),
        ),
    )
    result = PortfolioConstructionEngine(
        _policy(maximum_turnover=0.08, minimum_cash_weight=0.02)
    ).construct(request)

    assert {item.symbol for item in result.trades} == {"HIGH"}


@pytest.mark.parametrize(
    ("category", "expected_action", "expected_hysteresis"),
    (
        (
            EvidenceVetoCategory.OPERATIONAL_UNAVAILABLE,
            CIOAction.HOLD,
            False,
        ),
        (
            EvidenceVetoCategory.MATERIAL_UNCERTAINTY,
            CIOAction.HOLD,
            True,
        ),
        (
            EvidenceVetoCategory.INTEGRITY_EMERGENCY,
            CIOAction.REDUCE,
            False,
        ),
    ),
)
def test_evidence_veto_severity_controls_holding_consequence(
    category: EvidenceVetoCategory,
    expected_action: CIOAction,
    expected_hysteresis: bool,
) -> None:
    holding = _candidate("VETO", current_weight=0.05)
    qualification = OpportunityEngine().qualify(holding, _context())
    packet = _packet(holding, duplicate_origins=False)
    analyses = tuple(
        replace(
            item,
            position=SpecialistPosition.OPPOSED,
            veto_reasons=("governed evidence condition",),
            veto_categories=(category,),
        )
        if item.role is SpecialistRole.EVIDENCE_GOVERNANCE
        else item
        for item in packet.analyses
    )
    prior = PriorDecisionContext(
        candidate_identifier=holding.identifier,
        prior_decision_identifier="decision:veto-prior",
        prior_action=CIOAction.HOLD,
        prior_target_weight=0.05,
        decided_at=holding.as_of,
        thesis_state=ThesisState.ACTIVE,
        consecutive_opposing_cycles=0,
    )

    decision = ChiefInvestmentOfficer().synthesize(
        holding,
        qualification.universe,
        replace(packet, analyses=analyses),
        capital_comparison=qualification.capital_comparison,
        prior_context=prior,
    )

    assert decision.action is expected_action
    assert decision.hysteresis_applied is expected_hysteresis
    if category is EvidenceVetoCategory.OPERATIONAL_UNAVAILABLE:
        assert decision.recommended_position_weight is None
        assert "operational evidence outage" in decision.rationale


def test_ranking_respects_versioned_construction_cash_reserve() -> None:
    candidate = _candidate("RESERVE")
    cycle = CanonicalCIOCycle(
        construction_policy=PortfolioConstructionPolicy(minimum_cash_weight=0.05)
    )
    portfolio = CyclePortfolioState(
        identifier="portfolio:reserve-test",
        as_of=candidate.as_of,
        portfolio_value=250_000.0,
        cash_weight=0.08,
        cash_expected_return=0.04,
        positions=(_asset("CORE", 0.92, funding_eligible=False),),
        exposure_profiles=(
            CandidateExposureProfile(
                candidate_identifier=candidate.identifier,
                sector="technology",
                factor_loadings=(("market", 1.0),),
                correlation_bucket="growth",
            ),
        ),
    )

    ranking = cycle._ranking_inputs(
        (candidate,),
        portfolio,
        minimum_cash_weight=cycle.construction_engine.policy.minimum_cash_weight,
    )[0]
    from portfolio.construction_api import ConstructionIntent

    annualized = ConstructionIntent.annualized_return(
        candidate.net_expected_return,
        horizon_days=candidate.decision_horizon_days,
    )
    expected = (
        (annualized - portfolio.cash_expected_return) * 0.03
        - candidate.implementation_cost_return * 0.03
    )

    assert ranking.marginal_portfolio_contribution == pytest.approx(expected)
