from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from cio.models import CandidateAssetClass, CIOAction, ThesisState
from portfolio.active_investor import (
    CompoundingAccountabilityEngine,
    PositionLifecycleEngine,
    PositionLifecycleStage,
    ReactiveMonitoringEngine,
    ReactiveTriggerKind,
    SQLiteActiveInvestorStore,
    ViewToExpressionEngine,
)
from portfolio.compounding_allocation import (
    AllocationRange,
    CandidateAllocationDirective,
    CompoundingPortfolioAlternativeEngine,
    PortfolioPosture,
    PortfolioRegime,
    PortfolioSleeve,
    RegimeTransition,
)


NOW = datetime(2026, 8, 4, 1, 30, tzinfo=timezone.utc)


def _posture(
    *,
    regime: PortfolioRegime = PortfolioRegime.RISK_ON_GROWTH,
    preferred: tuple[PortfolioSleeve, ...] = (PortfolioSleeve.PRODUCTIVE_RISK,),
) -> PortfolioPosture:
    return PortfolioPosture(
        identifier=f"posture:{regime.value}",
        as_of=NOW,
        regime=regime,
        confidence=0.78,
        risk_score=0.42,
        productive_risk=AllocationRange(0.50, 0.80),
        defensive_income=AllocationRange(0.05, 0.30),
        dollar_liquidity=AllocationRange(0.10, 0.35),
        inflation_real_assets=AllocationRange(0.00, 0.25),
        diversifiers=AllocationRange(0.00, 0.20),
        preferred_sleeves=preferred,
        discouraged_sleeves=(),
        transitions=(
            RegimeTransition(regime, 0.60, "base regime persists", ("breadth",)),
            RegimeTransition(
                PortfolioRegime.BALANCED_TRANSITION,
                0.25,
                "conditions become mixed",
                ("credit",),
            ),
            RegimeTransition(
                PortfolioRegime.RISK_OFF_RECESSION,
                0.15,
                "growth deteriorates",
                ("growth",),
            ),
        ),
        evidence=("macro:growth", "market:breadth"),
        contradictory_evidence=("policy uncertainty",),
        change_conditions=("growth or liquidity changes materially",),
    )


def _candidate(
    identifier: str,
    symbol: str,
    asset_class: CandidateAssetClass,
    *,
    expected_return: float = 0.14,
    opportunity_cost: float = 0.04,
    current_weight: float = 0.0,
    liquidity: float = 0.90,
    treasury: bool = False,
    duration: float | None = None,
):
    return SimpleNamespace(
        identifier=identifier,
        as_of=NOW,
        instrument=SimpleNamespace(
            symbol=symbol,
            name=f"{symbol} governed instrument",
            asset_class=asset_class,
            economic_exposure_class=None,
            is_us_treasury=treasury,
            effective_duration_years=duration,
        ),
        net_expected_return=expected_return,
        opportunity_cost_return=opportunity_cost,
        implementation_cost_return=0.001,
        transaction_cost_bps=4.0,
        slippage_bps=3.0,
        liquidity_score=liquidity,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.12,
        evidence_identifiers=(f"evidence:{symbol}",),
        primary_catalysts=("earnings and flow remain supportive",),
        invalidation_conditions=("expected return turns negative",),
        monitoring_indicators=(
            "signed_dollar_flow",
            "expected_market_surprise",
        ),
        review_at=NOW + timedelta(days=7),
    )


def _directive(candidate_identifier: str, sleeve: PortfolioSleeve) -> CandidateAllocationDirective:
    return CandidateAllocationDirective(
        candidate_identifier=candidate_identifier,
        sleeve=sleeve,
        posture_alignment=0.72,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
        rationale="preferred by the governed posture",
    )


def _context(candidate_identifier: str, *, flow: float, expectations: float):
    signals = (
        SimpleNamespace(
            identifier=f"signal:capital-flow:{candidate_identifier}",
            name="accumulation capital-flow proxy",
            expected_return_impact=flow,
            confidence=0.72,
        ),
        SimpleNamespace(
            identifier=f"signal:market-expectations:{candidate_identifier}",
            name="market expectations gap",
            expected_return_impact=expectations,
            confidence=0.68,
        ),
    )
    return SimpleNamespace(
        candidate_identifier=candidate_identifier,
        forward_intelligence=SimpleNamespace(signals=signals),
    )


def test_risk_on_view_ranks_only_certified_candidates() -> None:
    equity = _candidate("candidate:ABC", "ABC", CandidateAssetClass.US_EQUITY)
    bond = _candidate(
        "candidate:IEF",
        "IEF",
        CandidateAssetClass.FIXED_INCOME,
        expected_return=0.07,
        treasury=True,
        duration=7.0,
    )
    engine = ViewToExpressionEngine()
    result = engine.build(
        posture=_posture(),
        candidates=(equity, bond),
        specialist_contexts=(
            _context(equity.identifier, flow=0.04, expectations=0.05),
            _context(bond.identifier, flow=-0.01, expectations=0.01),
        ),
        directives=(
            _directive(equity.identifier, PortfolioSleeve.PRODUCTIVE_RISK),
            _directive(bond.identifier, PortfolioSleeve.DEFENSIVE_INCOME),
        ),
    )

    assert {item.candidate_identifier for item in result.expressions} == {
        equity.identifier
    }
    assert result.expressions[0].rank == 1
    assert result.expressions[0].expression_score > 0.60
    assert result.expressions[0].symbol == "ABC"
    assert result.uncovered_views == ()


def test_funding_stress_originates_dollar_expressions_without_forcing_a_trade() -> None:
    cash = _candidate(
        "candidate:BIL",
        "BIL",
        CandidateAssetClass.CASH_EQUIVALENT,
        expected_return=0.05,
    )
    treasury = _candidate(
        "candidate:SHY",
        "SHY",
        CandidateAssetClass.FIXED_INCOME,
        expected_return=0.055,
        treasury=True,
        duration=1.8,
    )
    posture = _posture(
        regime=PortfolioRegime.RISK_OFF_FUNDING_STRESS,
        preferred=(PortfolioSleeve.DOLLAR_LIQUIDITY,),
    )
    result = ViewToExpressionEngine().build(
        posture=posture,
        candidates=(cash, treasury),
        specialist_contexts=(
            _context(cash.identifier, flow=0.02, expectations=0.01),
            _context(treasury.identifier, flow=0.03, expectations=0.02),
        ),
        directives=(
            _directive(cash.identifier, PortfolioSleeve.DOLLAR_LIQUIDITY),
            _directive(treasury.identifier, PortfolioSleeve.DOLLAR_LIQUIDITY),
        ),
    )

    kinds = {item.kind.value for item in result.views}
    assert "dollar_strength" in kinds
    assert "liquidity_reserve" in kinds
    assert {item.symbol for item in result.expressions} == {"BIL", "SHY"}
    assert all(
        item.to_dict()["investment_authority"] is False
        for item in result.expressions
    )


def test_lifecycle_maps_cio_and_construction_state_to_investor_stages() -> None:
    initiate = _candidate("candidate:NEW", "NEW", CandidateAssetClass.US_EQUITY)
    add = _candidate(
        "candidate:ADD",
        "ADD",
        CandidateAssetClass.US_EQUITY,
        current_weight=0.02,
    )
    trim = _candidate(
        "candidate:TRIM",
        "TRIM",
        CandidateAssetClass.US_EQUITY,
        current_weight=0.08,
    )
    exit_candidate = _candidate(
        "candidate:EXIT",
        "EXIT",
        CandidateAssetClass.US_EQUITY,
        current_weight=0.04,
    )
    candidates = (initiate, add, trim, exit_candidate)
    expressions = ViewToExpressionEngine().build(
        posture=_posture(),
        candidates=candidates,
        specialist_contexts=tuple(
            _context(item.identifier, flow=0.03, expectations=0.04)
            for item in candidates
        ),
        directives=tuple(
            _directive(item.identifier, PortfolioSleeve.PRODUCTIVE_RISK)
            for item in candidates
        ),
    )
    decisions = (
        SimpleNamespace(
            candidate_identifier=initiate.identifier,
            action=CIOAction.BUY,
            recommended_position_weight=0.01,
        ),
        SimpleNamespace(
            candidate_identifier=add.identifier,
            action=CIOAction.INCREASE,
            recommended_position_weight=0.05,
        ),
        SimpleNamespace(
            candidate_identifier=trim.identifier,
            action=CIOAction.REDUCE,
            recommended_position_weight=0.04,
        ),
        SimpleNamespace(
            candidate_identifier=exit_candidate.identifier,
            action=CIOAction.EXIT,
            recommended_position_weight=0.0,
        ),
    )
    construction = SimpleNamespace(
        target_weights=(
            ("NEW", 0.01),
            ("ADD", 0.05),
            ("TRIM", 0.04),
            ("EXIT", 0.0),
        )
    )
    lifecycle = PositionLifecycleEngine().build(
        as_of=NOW,
        candidates=candidates,
        decisions=decisions,
        theses=(),
        expression_set=expressions,
        portfolio=SimpleNamespace(),
        construction=construction,
    )
    stage_by_symbol = {item.symbol: item.stage for item in lifecycle.directives}

    assert stage_by_symbol == {
        "NEW": PositionLifecycleStage.INITIATE,
        "ADD": PositionLifecycleStage.ADD,
        "TRIM": PositionLifecycleStage.TRIM,
        "EXIT": PositionLifecycleStage.EXIT,
    }
    assert all(item.validation_milestones for item in lifecycle.directives)


def test_reactive_plan_targets_dependencies_and_reserves_full_cycle_for_regime() -> None:
    candidate = _candidate("candidate:ABC", "ABC", CandidateAssetClass.US_EQUITY)
    posture = _posture()
    expressions = ViewToExpressionEngine().build(
        posture=posture,
        candidates=(candidate,),
        specialist_contexts=(
            _context(candidate.identifier, flow=0.04, expectations=0.04),
        ),
        directives=(
            _directive(candidate.identifier, PortfolioSleeve.PRODUCTIVE_RISK),
        ),
    )
    lifecycle = PositionLifecycleEngine().build(
        as_of=NOW,
        candidates=(candidate,),
        decisions=(
            SimpleNamespace(
                candidate_identifier=candidate.identifier,
                action=CIOAction.BUY,
                recommended_position_weight=0.01,
            ),
        ),
        theses=(),
        expression_set=expressions,
        portfolio=SimpleNamespace(),
        construction=SimpleNamespace(target_weights=(("ABC", 0.01),)),
    )
    reactive = ReactiveMonitoringEngine().build(
        posture=posture,
        expression_set=expressions,
        lifecycle=lifecycle,
    )

    kinds = {item.kind for item in reactive.dependencies}
    assert ReactiveTriggerKind.FLOW_REVERSAL in kinds
    assert ReactiveTriggerKind.EXPECTATIONS_GAP in kinds
    assert ReactiveTriggerKind.REGIME_TRANSITION in kinds
    regime = next(
        item
        for item in reactive.dependencies
        if item.kind is ReactiveTriggerKind.REGIME_TRANSITION
    )
    assert regime.full_cycle_required is True
    assert any(item.incremental_reassessment for item in reactive.dependencies)


def test_accountability_exposes_cash_cost_and_positive_edge_nonownership() -> None:
    candidate = _candidate("candidate:ABC", "ABC", CandidateAssetClass.US_EQUITY)
    posture = _posture()
    directive = _directive(candidate.identifier, PortfolioSleeve.PRODUCTIVE_RISK)
    alternatives = CompoundingPortfolioAlternativeEngine().build(
        cycle_identifier="cycle:test",
        posture=posture,
        candidates=(candidate,),
        directives=(directive,),
        portfolio=SimpleNamespace(
            positions=(),
            cash_weight=1.0,
            cash_expected_return=0.04,
        ),
        construction=None,
    )
    accountability = CompoundingAccountabilityEngine().build(
        posture=posture,
        alternatives=alternatives,
        candidates=(candidate,),
        decisions=(
            SimpleNamespace(
                candidate_identifier=candidate.identifier,
                action=CIOAction.WATCH,
            ),
        ),
        construction=SimpleNamespace(
            estimated_cost_return=0.001,
            expected_return_improvement=0.02,
        ),
    )

    assert accountability.cash_opportunity_cost > 0.0
    assert accountability.positive_edge_nonownership_count == 1
    assert accountability.positive_edge_nonownership_candidates == (
        candidate.identifier,
    )
    assert accountability.to_dict()["automatic_policy_change"] is False


def test_active_investor_store_is_idempotent_and_hash_chained(tmp_path: Path) -> None:
    candidate = _candidate("candidate:ABC", "ABC", CandidateAssetClass.US_EQUITY)
    posture = _posture()
    directive = _directive(candidate.identifier, PortfolioSleeve.PRODUCTIVE_RISK)
    expressions = ViewToExpressionEngine().build(
        posture=posture,
        candidates=(candidate,),
        specialist_contexts=(
            _context(candidate.identifier, flow=0.03, expectations=0.04),
        ),
        directives=(directive,),
    )
    lifecycle = PositionLifecycleEngine().build(
        as_of=NOW,
        candidates=(candidate,),
        decisions=(
            SimpleNamespace(
                candidate_identifier=candidate.identifier,
                action=CIOAction.BUY,
                recommended_position_weight=0.01,
            ),
        ),
        theses=(
            SimpleNamespace(
                candidate_identifier=candidate.identifier,
                state=ThesisState.ACTIVE,
            ),
        ),
        expression_set=expressions,
        portfolio=SimpleNamespace(),
        construction=SimpleNamespace(target_weights=(("ABC", 0.01),)),
    )
    reactive = ReactiveMonitoringEngine().build(
        posture=posture,
        expression_set=expressions,
        lifecycle=lifecycle,
    )
    alternatives = CompoundingPortfolioAlternativeEngine().build(
        cycle_identifier="cycle:test",
        posture=posture,
        candidates=(candidate,),
        directives=(directive,),
        portfolio=SimpleNamespace(
            positions=(),
            cash_weight=1.0,
            cash_expected_return=0.04,
        ),
        construction=None,
    )
    accountability = CompoundingAccountabilityEngine().build(
        posture=posture,
        alternatives=alternatives,
        candidates=(candidate,),
        decisions=(
            SimpleNamespace(
                candidate_identifier=candidate.identifier,
                action=CIOAction.BUY,
            ),
        ),
        construction=SimpleNamespace(
            estimated_cost_return=0.001,
            expected_return_improvement=0.02,
        ),
    )
    store = SQLiteActiveInvestorStore(tmp_path / "journal.db")

    store.append_cycle(
        cycle_identifier="cycle:test",
        expressions=expressions,
        lifecycle=lifecycle,
        reactive=reactive,
        accountability=accountability,
        code_version="test",
    )
    store.append_cycle(
        cycle_identifier="cycle:test",
        expressions=expressions,
        lifecycle=lifecycle,
        reactive=reactive,
        accountability=accountability,
        code_version="test",
    )

    assert store.verify_integrity() is True
