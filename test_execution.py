from core.execution_engine import execute_paper_trade
from core.seed import seed_mandates
from core.portfolio_engine import portfolio_snapshot

def test_paper_buy_reduces_cash_and_creates_position():
    seed_mandates()
    before = portfolio_snapshot("balanced_allocation")
    result = execute_paper_trade(
        "balanced_allocation", "SPY", "BUY", 1, 100, "test"
    )
    after = portfolio_snapshot("balanced_allocation")
    assert result.trade_id > 0
    assert after.cash < before.cash
    assert any(p["symbol"] == "SPY" for p in after.positions)
