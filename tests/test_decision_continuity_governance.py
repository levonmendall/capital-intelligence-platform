from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import (
    ChampionChallengerRegistry,
    ChiefInvestmentOfficer,
    PolicyPerformanceEvidence,
    PolicyVersionCandidate,
    PolicyVersionStatus,
)
from cio.persistence import SQLiteCIOJournal
from evaluation import (
    DecisionCalibrationSuiteBuilder,
    EvaluationOutcome,
    PointInTimeDecisionEvaluator,
)
from opportunity import OpportunityEngine
from portfolio.construction_api import (
    ConstructionMode,
    GovernedPortfolioScenario,
    GovernedPortfolioScenarioSet,
    PortfolioConstructionEngine,
    PortfolioScenarioAuthority,
)
from portfolio.derivative_lifecycle import (
    DerivativeLifecycleAuthority,
    DerivativeLifecycleProfile,
)
from tests.test_decision_quality_reconciliation import _candidate, _context, _packet
from tests.test_point_in_time_evaluation import _cycle, _realized
from tests.test_portfolio_construction_engine import _asset, _intent, _policy, _request
from thesis import (
    LivingThesis,
    MissingDataBehavior,
    StructuredThesisConditionScorer,
    ThesisCondition,
    ThesisConditionConsequence,
    ThesisConditionOperator,
)
from cio import CIOAction


AS_OF = datetime(2026, 7, 29, 16, tzinfo=timezone.utc)


def _performance(**overrides) -> PolicyPerformanceEvidence:
    values = {
        "sample_count": 80,
        "out_of_sample_count": 50,
        "regime_identifiers": ("growth", "inflation", "risk_off"),
        "mean_decision_brier": 0.14,
        "calibration_error": 0.05,
        "maximum_drawdown": -0.12,
        "mean_turnover": 0.12,
        "missed_opportunity_rate": 0.08,
        "integrity_failure_count": 0,
    }
    values.update(overrides)
    return PolicyPerformanceEvidence(**values)


def test_champion_challenger_requires_governed_independent_promotion() -> None:
    champion = PolicyVersionCandidate(
        identifier="policy:champion",
        component="cio",
        version="v1",
        status=PolicyVersionStatus.CHAMPION,
        evidence=_performance(mean_decision_brier=0.18),
        created_at=AS_OF,
    )
    challenger = PolicyVersionCandidate(
        identifier="policy:challenger",
        component="cio",
        version="v2",
        status=PolicyVersionStatus.CHALLENGER,
        evidence=_performance(),
        created_at=AS_OF,
        rollback_version="v1",
    )

    approved = ChampionChallengerRegistry().evaluate(
        champion, challenger, approver="investment-governance-committee"
    )
    self_promoted = ChampionChallengerRegistry().evaluate(
        champion, challenger, approver="challenger"
    )

    assert approved.permitted
    assert not self_promoted.permitted
    assert any("independent" in item for item in self_promoted.reasons)


def test_governed_scenario_authority_requires_exact_complete_coverage() -> None:
    scenario_set = GovernedPortfolioScenarioSet(
        identifier="scenario-set:1",
        as_of=AS_OF,
        knowledge_cutoff=AS_OF - timedelta(minutes=5),
        horizon_days=90,
        source_identifier="forecast-publication:1",
        model_versions=("cross-asset:v1",),
        evidence_identifiers=("evidence:macro", "evidence:market"),
        scenarios=(
            GovernedPortfolioScenario("risk-off", 0.25, 0.01, (("CORE", -0.12), ("NEW", -0.30))),
            GovernedPortfolioScenario("base", 0.50, 0.02, (("CORE", 0.04), ("NEW", 0.08))),
            GovernedPortfolioScenario("risk-on", 0.25, 0.03, (("CORE", 0.10), ("NEW", 0.25))),
        ),
    )

    scenarios = PortfolioScenarioAuthority().authorize(
        scenario_set, as_of=AS_OF, symbols=("CORE", "NEW")
    )
    assert len(scenarios) == 3
    with pytest.raises(ValueError, match="exactly cover"):
        PortfolioScenarioAuthority().authorize(
            scenario_set, as_of=AS_OF, symbols=("CORE", "NEW", "MISSING")
        )
    with pytest.raises(KeyError, match="MISSING"):
        scenarios[0].return_for("MISSING")


def test_structured_thesis_scoring_rewards_testable_fail_closed_conditions() -> None:
    condition = ThesisCondition(
        identifier="condition:margin",
        metric_identifier="company.operating_margin",
        operator=ThesisConditionOperator.AT_OR_ABOVE,
        threshold=0.20,
        observation_window_days=30,
        required_persistence=2,
        source_identifier="filing:10q",
        missing_data_behavior=MissingDataBehavior.FAIL_CLOSED,
        consequence=ThesisConditionConsequence.SUPPORT,
    )
    quality = StructuredThesisConditionScorer().score((condition,))

    assert condition.evaluate(0.22)
    assert not condition.evaluate(0.18)
    assert quality.score > 0.70
    assert quality.fail_closed_count == 1


def test_derivative_allocation_requires_complete_lifecycle_profile() -> None:
    authority = DerivativeLifecycleAuthority()
    missing = authority.assess(None, instrument_identifier="OPTION:1", as_of=AS_OF)
    profile = DerivativeLifecycleProfile(
        identifier="lifecycle:option:1",
        instrument_identifier="OPTION:1",
        contract_multiplier=100.0,
        notional_per_contract=5_000.0,
        delta=0.45,
        gamma=0.08,
        vega=0.30,
        theta=-0.02,
        expires_at=AS_OF + timedelta(days=60),
        roll_review_days=14,
        initial_margin_return=0.10,
        maintenance_margin_return=0.08,
        collateral_return=0.10,
        maximum_loss_return=-0.10,
        assignment_supported=True,
        exercise_style="american",
        settlement_type="physical",
        source_identifiers=("occ:contract", "broker:margin"),
        model_versions=("greeks:v1",),
    )
    complete = authority.assess(profile, instrument_identifier="OPTION:1", as_of=AS_OF)

    assert not missing.authorized
    assert complete.authorized


def test_emergency_derisking_relaxes_soft_turnover_and_reports_residuals() -> None:
    request = _request(
        cash=0.20,
        positions=(_asset("CORE", 0.80),),
        intents=(
            _intent(
                "CORE",
                action=CIOAction.EXIT,
                target=0.0,
                maximum_position_weight=0.80,
            ),
        ),
    )
    policy = _policy(maximum_turnover=0.20, emergency_maximum_turnover=1.0)
    normal = PortfolioConstructionEngine(policy).construct(request)
    emergency = PortfolioConstructionEngine(policy).construct(
        replace(request, mode=ConstructionMode.EMERGENCY_DE_RISKING)
    )

    assert normal.residual_exposures
    assert emergency.residual_exposures == ()
    assert dict(emergency.target_weights).get("CORE", 0.0) == pytest.approx(0.0)
    assert emergency.mode is ConstructionMode.EMERGENCY_DE_RISKING


def test_production_state_can_be_reconstructed_by_instrument_across_candidate_ids(tmp_path) -> None:
    journal = SQLiteCIOJournal(tmp_path / "cio.db")
    candidate = _candidate("CONTINUITY")
    qualification = OpportunityEngine().qualify(candidate, _context())
    decision = ChiefInvestmentOfficer().synthesize(
        candidate,
        qualification.universe,
        _packet(candidate, duplicate_origins=False),
        capital_comparison=qualification.capital_comparison,
    )
    assert decision.action in {CIOAction.BUY, CIOAction.INCREASE, CIOAction.HOLD}
    thesis = LivingThesis.from_decision(candidate, decision)
    journal.append_candidate(candidate)
    journal.append_decision(decision)
    journal.append_thesis_snapshot(thesis)

    later = replace(
        candidate,
        identifier="candidate:continuity:later",
        as_of=candidate.as_of + timedelta(days=1),
        review_at=candidate.review_at + timedelta(days=1),
    )
    contexts = journal.prior_decision_contexts((later,), as_of=later.as_of)
    theses = journal.active_theses((later,), as_of=later.as_of)

    assert contexts[0].candidate_identifier == later.identifier
    assert contexts[0].prior_decision_identifier == decision.identifier
    assert theses[0].ownership_episode_identifier == thesis.ownership_episode_identifier


def test_calibration_treats_correct_abstention_as_success() -> None:
    snapshot = SimpleNamespace(
        identifier="snapshot:1",
        action=CIOAction.NO_SUPERIOR_OPPORTUNITY,
        final_confidence=0.90,
        probability_of_success=0.20,
        evidence_vetoes=(),
        implementation_blocks=(),
    )
    evaluation = SimpleNamespace(
        snapshot_identifier="snapshot:1",
        outcome=EvaluationOutcome.CORRECT_ABSTENTION,
        candidate_return=0.01,
        best_original_alternative_return=0.05,
    )
    suite = DecisionCalibrationSuiteBuilder().build(
        ((snapshot, evaluation),), as_of=AS_OF
    )
    abstention = next(item for item in suite.metrics if item.dimension.value == "abstention")

    assert abstention.observed_success_rate == pytest.approx(1.0)
    assert abstention.mean_brier_score == pytest.approx(0.01)


def test_point_in_time_evaluation_reports_continuous_distribution_score(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(snapshot, candidate_return=0.12, implementation_return=0.11),
    )

    assert evaluation.scenario_crps >= 0.0
    assert evaluation.to_dict()["scenario_crps"] == pytest.approx(evaluation.scenario_crps)
