from datetime import datetime, timezone

import pytest

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
            identifier="portfolio:COMPOUNDING:1", portfolio_code="COMPOUNDING",
            display_name="Capital Intelligence Portfolio", constraint_profile="standard",
            as_of=now, starting_capital=250000, cash_amount=240000,
            positions=(CanonicalPortfolioPosition("SPY", 20, 500, 500, now),),
            source_identifiers=("test",),
        )
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", str(path))


def test_retired_rebalancer_cannot_issue_active_actions(tmp_path, monkeypatch):
    _state(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="offline research only"):
        calculate_rebalance("COMPOUNDING")
