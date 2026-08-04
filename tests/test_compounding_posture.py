from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from cio.models import CandidateAssetClass
from portfolio.compounding_allocation import (
    AllocationRange,
    CandidateAllocationDirective,
    CompoundingPortfolioAlternativeEngine,
    PortfolioAlternativeKind,
    PortfolioPosture,
    PortfolioPostureEngine,
    PortfolioRegime,
    PortfolioSleeve,
    RegimeTransition,
    SQLiteCompoundingAllocationStore,
)


NOW = datetime(2026, 8, 3, 16, 0, tzinfo=timezone.utc)


def _context(*, macro_impact, market_impact, trend, breadth, liquidity, regime, market_regime):
    return SimpleNamespace(
        macro=SimpleNamespace(
            expected_return_impact=macro_impact,
            confidence=0.80,
            regime=regime,
            tailwinds=("earnings growth",),
            headwinds=(),
            systemic_risks=("policy error",),
            evidence_identifiers=("fred:growth", "fred:inflation"),
        ),
        market=SimpleNamespace(
            expected_return_impact=market_impact,
            confidence=0.75,
            market_regime=market_regime,
            trend=trend,
            momentum=trend,
            breadth=breadth,
            liquidity=liquidity,
            positioning=0.20,
            evidence=("broad participation",),
            risks=("crowding can reverse",),
            entry_conditions=("breadth remains positive",),
            evidence_identifiers=("market:breadth", "market:liquidity"),
        ),
        forward_intelligence=None,
    )


def _posture() -> PortfolioPosture:
    return PortfolioPosture(
        identifier="posture:test",
        as_of=NOW,
        regime=PortfolioRegime.RISK_ON_GROWTH,
        confidence=0.80,
        risk_score=0.45,
        productive_risk=AllocationRange(0.50, 0.85),
        defensive_income=AllocationRange(0.05, 0.25),
        dollar_liquidity=AllocationRange(0.05, 0.25),
        inflation_real_assets=AllocationRange(0.00, 0.20),
        diversifiers=AllocationRange(0.00, 0.15),
        preferred_sleeves=(PortfolioSleeve.PRODUCTIVE_RISK,),
        discouraged_sleeves=(),
        transitions=(
            RegimeTransition(PortfolioRegime.RISK_ON_GROWTH, 0.60, "growth persists", ("breadth",)),
            RegimeTransition(PortfolioRegime.RISK_ON_DISINFLATION, 0.25, "inflation cools", ("real yields",)),
            RegimeTransition(PortfolioRegime.RISK_OFF_RECESSION, 0.15, "growth fails", ("credit spreads",)),
        ),
        evidence=("test evidence",),
        contradictory_evidence=(),
        change_conditions=("reassess on material change",),
    )


def _candidate():
    return SimpleNamespace(
        identifier="candidate:ABC",
        net_expected_return=0.12,
        decision_horizon_days=365,
        implementation_cost_return=0.001,
        maximum_position_weight=0.10,
        evidence_quality=SimpleNamespace(score=0.82, ceiling=0.78),
        instrument=SimpleNamespace(
            symbol="ABC",
            name="ABC Corporation",
            asset_class=CandidateAssetClass.US_EQUITY,
            economic_exposure_class=None,
            is_us_treasury=False,
        ),
    )


def test_supportive_environment_creates_productive_risk_posture() -> None:
    posture = PortfolioPostureEngine().assess(
        as_of=NOW,
        specialist_contexts=(
            _context(
                macro_impact=0.55,
                market_impact=0.45,
                trend=0.60,
                breadth=0.55,
                liquidity=0.30,
                regime="growth expansion",
                market_regime="broad risk-on",
            ),
        ),
    )
    assert posture.regime is PortfolioRegime.RISK_ON_GROWTH
    assert PortfolioSleeve.PRODUCTIVE_RISK in posture.preferred_sleeves
    assert posture.productive_risk.minimum >= 0.50
    assert abs(sum(item.probability for item in posture.transitions) - 1.0) < 1e-8


def test_inflationary_risk_off_is_not_treated_as_recession() -> None:
    posture = PortfolioPostureEngine().assess(
        as_of=NOW,
        specialist_contexts=(
            _context(
                macro_impact=-0.35,
                market_impact=-0.20,
                trend=-0.25,
                breadth=-0.30,
                liquidity=-0.10,
                regime="inflation shock and stagflation",
                market_regime="risk-off",
            ),
        ),
    )
    assert posture.regime is PortfolioRegime.RISK_OFF_INFLATION
    assert PortfolioSleeve.INFLATION_REAL_ASSETS in posture.preferred_sleeves
    assert PortfolioSleeve.DEFENSIVE_INCOME in posture.discouraged_sleeves


def test_cash_competes_with_complete_portfolio_alternatives(tmp_path: Path) -> None:
    candidate = _candidate()
    posture = _posture()
    directive = CandidateAllocationDirective(
        candidate_identifier=candidate.identifier,
        sleeve=PortfolioSleeve.PRODUCTIVE_RISK,
        posture_alignment=0.85,
        preferred=True,
        discouraged=False,
        maximum_staged_weight=0.01,
        rationale="preferred productive-risk sleeve",
    )
    alternatives = CompoundingPortfolioAlternativeEngine().build(
        cycle_identifier="cycle:test",
        posture=posture,
        candidates=(candidate,),
        directives=(directive,),
        portfolio=SimpleNamespace(positions=(), cash_weight=1.0, cash_expected_return=0.04),
        construction=None,
    )
    kinds = {item.kind for item in alternatives.alternatives}
    assert PortfolioAlternativeKind.ALL_CASH in kinds
    assert PortfolioAlternativeKind.PRODUCTIVE_RISK in kinds
    assert PortfolioAlternativeKind.POSTURE_CONSISTENT in kinds
    assert alternatives.cash_is_best_estimate is False

    store = SQLiteCompoundingAllocationStore(tmp_path / "journal.db")
    first = store.append(
        cycle_identifier="cycle:test",
        posture=posture,
        alternatives=alternatives,
        code_version="test",
    )
    second = store.append(
        cycle_identifier="cycle:test",
        posture=posture,
        alternatives=alternatives,
        code_version="test",
    )
    assert first == second
    assert store.verify_integrity() is True


def test_scheduler_binds_compounding_cycle() -> None:
    source = Path("run_scheduler.py").read_text(encoding="utf-8")
    assert "CompoundingCanonicalCIOCycle" in source
    assert "CompoundingProductionCanonicalCIOExecutor" in source
