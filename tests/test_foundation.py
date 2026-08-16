"""Foundation tests for the Capital Intelligence Platform."""

from datetime import datetime, timezone

from core.portfolio import get_mandates, get_portfolio_totals, initialize_portfolios
from intelligence.pipeline import build_allocation, run_intelligence
from intelligence.provider import load_sample_snapshot
from intelligence.regime import determine_regime
from portfolio.constants import CANONICAL_CONSTRAINT_PROFILE, CANONICAL_PORTFOLIO_NAME
from portfolio.state import (
    CanonicalImplementationEvent,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)


def test_platform_seeds_only_the_canonical_portfolio(tmp_path, monkeypatch) -> None:
    path = tmp_path / "canonical.db"
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", str(path))
    initialize_portfolios()
    mandates = get_mandates()
    assert len(mandates) == 1
    assert mandates[0]["code"] == "COMPOUNDING"
    assert mandates[0]["starting_capital"] == 250000


def test_total_virtual_capital_comes_from_canonical_state(tmp_path, monkeypatch) -> None:
    path = tmp_path / "canonical.db"
    as_of = datetime(2026, 7, 27, tzinfo=timezone.utc)
    SQLiteCanonicalPortfolioStore(path).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:COMPOUNDING:1", portfolio_code="COMPOUNDING",
            display_name=CANONICAL_PORTFOLIO_NAME,
            constraint_profile=CANONICAL_CONSTRAINT_PROFILE,
            as_of=as_of,
            starting_capital=250000, cash_amount=200000, positions=(),
            implementation_events=(
                CanonicalImplementationEvent(
                    identifier="test:non-trade-loss",
                    occurred_at=as_of,
                    action="NON_TRADE_PNL",
                    symbol=None,
                    quantity=0,
                    price=0,
                    gross_amount=0,
                    non_trade_pnl_base=-50000,
                    rationale="Reconciled fixture loss",
                    source_identifier="test",
                ),
            ),
            source_identifiers=("test",),
        )
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", str(path))
    totals = get_portfolio_totals()
    assert totals["starting_capital"] == 250000
    assert totals["cash"] == 200000
    assert totals["nav"] == 200000
    assert totals["accounting_residual"] == 0


def test_sample_snapshot_loads() -> None:
    snapshot = load_sample_snapshot()
    assert snapshot.growth == 0.55
    assert snapshot.inflation == 0.20
    assert snapshot.trend == 0.60


def test_regime_engine_returns_valid_result() -> None:
    snapshot = load_sample_snapshot()
    regime, confidence = determine_regime(snapshot)
    assert regime in {"Expansion", "Recovery", "Slowdown", "Recession", "Inflation Shock"}
    assert 0 <= confidence <= 1


def test_allocations_total_one_hundred_percent() -> None:
    for regime in ["Expansion", "Recovery", "Slowdown", "Recession", "Inflation Shock"]:
        _, allocation = build_allocation(regime)
        assert abs(sum(allocation.values()) - 1.0) < 0.000001


def test_intelligence_pipeline_returns_decision() -> None:
    decision = run_intelligence(save=False)
    assert decision.regime
    assert decision.risk_posture
    assert decision.rationale
    assert 0 <= decision.confidence <= 1
    assert abs(decision.equities + decision.bonds + decision.cash + decision.alternatives - 1.0) < 0.000001
