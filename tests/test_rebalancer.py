from datetime import datetime, timezone

from intelligence.rebalancer import calculate_rebalance
from portfolio.state import (
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)


def _state(tmp_path, monkeypatch):
    path = tmp_path / "canonical.db"
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    SQLiteCanonicalPortfolioStore(path).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:PRES:1", portfolio_code="PRES",
            display_name="Archived test portfolio", constraint_profile="standard",
            as_of=now, starting_capital=25000, cash_amount=15000,
            positions=(CanonicalPortfolioPosition("SPY", 20, 500, 500, now),),
            source_identifiers=("test",),
        )
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", str(path))


def test_rebalancer_returns_actions(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    assert len(calculate_rebalance("PRES")) > 0


def test_actions_have_valid_type(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    assert {item.action for item in calculate_rebalance("PRES")} <= {"BUY", "SELL", "HOLD"}
