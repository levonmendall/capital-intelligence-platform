from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from cio.models import CandidateAssetClass, CIOAction, ThesisState
from portfolio.active_investor import (
    PositionLifecycleEngine,
    PositionLifecycleStage,
    ReactiveMonitoringEngine,
    ReactiveTriggerKind,
    SQLiteActiveInvestorStore,
    ViewToExpressionEngine,
)
from portfolio.compounding_accountability import (
    ProspectiveCompoundingAccountabilityEngine,
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
            RegimeTransition(regime, 0.60, "base persists", ("breadth",)),
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
    current_weight: float = 0.0,
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
        opportunity_cost_return=0.04,
        implementation_cost_return=0.001,
        transaction_cost_bps=4.0,
        slippage_bps=3.0,
        liquidity_score=0.90,
        current_portfolio_weight=current_weight,
        maximum_position_weight=0.12,
        decision_horizon_days=365,
        evidence_quality=SimpleNamespace(score=0.84, ceiling=0.80),
        evidence_identifiers=(f"evidence:{symbol}",),
        primary_catalysts=("earnings and flow remain supportive",),
        invalidation_conditions=("expected return turns negative",),
        monitoring_indicators=(
            "signed_dollar_flow",
            "expected_market_surprise",
        ),
        review_at=NOW + timedelta(days=7),
    )


def _directive(identifier: str, sleeve: PortfolioSleeve):
    return CandidateAllocationDirective(
        candidate_identifier=identifier,
        sleeve=sleeve,
        posture_alignment=0.72,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
        rationale="preferred by the governed posture",
    )


def _context(identifier: str, flow: float = 0.04, expectations: float = 0.05):
    return SimpleNamespace(
        candidate_identifier=identifier,
        forward_intelligence=SimpleNamespace(
            signals=(
                SimpleNamespace(
                    identifier=f"signal:capital-flow:{identifier}",
                    name="accumulation capital-flow proxy",
                    expected_return_impact=flow,
                    confidence=0.72,
                ),
                SimpleNamespace(
                    identifier=f"signal:market-expectations:{identifier}",
                    name="market expectations gap",
                    expected_return_impact=expectations,
                    confidence=0.68,
                ),
            )
        ),
    )


def _expression_set(posture, candidates, directives):
    return ViewToExpressionEngine().build(
        posture=posture,
        candidates=candidates,
        specialist_contexts=tuple(_context(item.identifier) for item in candidates),
        directives=directives,
    )


def test_views_rank_only_certified_regime_consistent_candidates() -> None:
    equity = _candidate("candidate:ABC", "ABC", CandidateAssetClass.US_EQUITY)
    bond = _candidate(
        "candidate:IEF",
        "IEF",
        CandidateAssetClass.FIXED_INCOME,
        expected_return=0.07,
        treasury=True,
        duration=7.0,
    )
    result = _expression_set(
        _posture(),
        (equity, bond),
        (
            _directive(equity.identifier, PortfolioSleeve.PRODUCTIVE_RISK),
            _directive(bond.identifier, PortfolioSleeve.DEFENSIVE_INCOME),
        ),
    )

    assert {item.candidate_identifier for item in result.expressions} == {
        equity.identifier
    }
    assert result.expressions[0].rank == 1
    assert result.expressions[0].expression_score > 0.60
    assert result.expressions[0].to_dict()["investment_authority"] is False


def test_funding_stress_produces_dollar_expressions_without_trade_authority() -> None:
    cash = _candidate("candidate:BIL", "BIL", CandidateAssetClass.CASH_EQUIVALENT)
    treasury = _candidate(
        "candidate:SHY",
        "SHY",
        CandidateAssetClass.FIXED_INCOME,
        treasury=True,
        duration=1.8,
    )
    posture = _posture(
        PortfolioRegime.RISK_OFF_FUNDING_STRESS,
        (PortfolioSleeve.DOLLAR_LIQUIDITY,),
    )
    result = _expression_set(
        posture,
        (cash, treasury),
        (
            _directive(cash.identifier, PortfolioSleeve.DOLLAR_LIQUIDITY),
            _directive(treasury.identifier, PortfolioSleeve.DOLLAR_LIQUIDITY),
        ),
    )

    assert {item.kind.value for item in result.views}.issuperset(
        {"dollar_strength", "liquidity_reserve"}
    )
    assert {item.symbol for item in result.expressions} == {"BIL", "SHY"}
    assert result.to_dict()["cio_authority"] is False


def test_lifecycle_and_reactive_dependencies_cover_the_position_loop() -> None:
    candidates = (
        _candidate("candidate:NEW", "NEW", CandidateAssetClass.US_EQUITY),
        _candidate(
            "candidate:ADD",
            "ADD",
            CandidateAssetClass.US_EQUITY,
            current_weight=0.02,
        ),
        _candidate(
            "candidate:TRIM",
            "TRIM",
            CandidateAssetClass.US_EQUITY,
            current_weight=0.08,
        ),
        _candidate(
            "candidate:EXIT",
            "EXIT",
            CandidateAssetClass.US_EQUITY,
            current_weight=0.04,
        ),
    )
    posture = _posture()
    expressions = _expression_set(
        posture,
        candidates,
        tuple(
            _directive(item.identifier, PortfolioSleeve.PRODUCTIVE_RISK)
            for item in candidates
        ),
    )
    decisions = tuple(
        SimpleNamespace(
            candidate_identifier=item.identifier,
            action=action,
            recommended_position_weight=weight,
        )
        for item, action, weight in zip(
            candidates,
            (CIOAction.BUY, CIOAction.INCREASE, CIOAction.REDUCE, CIOAction.EXIT),
            (0.01, 0.05, 0.04, 0.0),
            strict=True,
        )
    )
    lifecycle = PositionLifecycleEngine().build(
        as_of=NOW,
        candidates=candidates,
        decisions=decisions,
        theses=(),
        expression_set=expressions,
        portfolio=SimpleNamespace(),
        construction=SimpleNamespace(
            target_weights=(("NEW", 0.01), ("ADD", 0.05), ("TRIM", 0.04), ("EXIT", 0.0))
        ),
    )
    assert {item.symbol: item.stage for item in lifecycle.directives} == {
        "NEW": PositionLifecycleStage.INITIATE,
        "ADD": PositionLifecycleStage.ADD,
        "TRIM": PositionLifecycleStage.TRIM,
        "EXIT": PositionLifecycleStage.EXIT,
    }

    reactive = ReactiveMonitoringEngine().build(
        posture=posture,
        expression_set=expressions,
        lifecycle=lifecycle,
    )
    kinds = {item.kind for item in reactive.dependencies}
    assert {
        ReactiveTriggerKind.FLOW_REVERSAL,
        ReactiveTriggerKind.EXPECTATIONS_GAP,
        ReactiveTriggerKind.REGIME_TRANSITION,
    }.issubset(kinds)
    regime = next(
        item
        for item in reactive.dependencies
        if item.kind is ReactiveTriggerKind.REGIME_TRANSITION
    )
    assert regime.full_cycle_required is True
    assert any(item.incremental_reassessment for item in reactive.dependencies)


def _accountability_fixture():
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
    accountability = ProspectiveCompoundingAccountabilityEngine().build(
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
    return candidate, posture, directive, alternatives, accountability


def test_accountability_separates_advisory_cash_cost_from_selection() -> None:
    candidate, _posture_value, _directive_value, alternatives, accountability = (
        _accountability_fixture()
    )

    assert alternatives.selected_alternative_identifier is None
    assert accountability.selected_alternative_identifier is None
    assert accountability.cash_opportunity_cost > 0.0
    assert accountability.positive_edge_nonownership_candidates == (
        candidate.identifier,
    )
    assert accountability.to_dict()["automatic_policy_change"] is False
    assert any(
        "does not represent CIO selection" in item
        for item in accountability.limitations
    )


def test_active_investor_store_is_idempotent_and_hash_chained(tmp_path: Path) -> None:
    candidate, posture, directive, alternatives, accountability = (
        _accountability_fixture()
    )
    expressions = _expression_set(
        posture,
        (candidate,),
        (directive,),
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
    store = SQLiteActiveInvestorStore(tmp_path / "journal.db")
    values = dict(
        cycle_identifier="cycle:test",
        expressions=expressions,
        lifecycle=lifecycle,
        reactive=reactive,
        accountability=accountability,
        code_version="test",
    )

    store.append_cycle(**values)
    store.append_cycle(**values)

    assert store.verify_integrity() is True
