from __future__ import annotations

from types import SimpleNamespace

import portfolio_only_runtime


def _fixture_html() -> str:
    totals = {
        "nav": 252_500.0,
        "cash": 200_000.0,
        "total_return": 0.01,
        "total_pnl": 2_500.0,
    }
    mandate = {
        "nav": 252_500.0,
        "cash": 200_000.0,
        "total_return": 0.01,
        "total_pnl": 2_500.0,
        "as_of": "2026-08-19T20:00:00+00:00",
        "holdings": [
            {
                "symbol": "VTI",
                "asset_class": "us_etf",
                "quantity": 100.0,
                "current_price": 250.0,
                "cost_basis": 240.0,
                "market_value": 25_000.0,
                "unrealized_gain": 1_000.0,
                "unrealized_return": 0.0416667,
                "updated_at": "2026-08-19T20:00:00+00:00",
            }
        ],
        "trades": [
            {
                "created_at": "2026-08-19T19:00:00+00:00",
                "side": "BUY",
                "symbol": "VTI",
                "asset_class": "us_etf",
                "realized_pnl_base": 500.0,
            }
        ],
        "snapshots": [
            {
                "created_at": "2026-08-19T18:00:00+00:00",
                "nav": 250_000.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            },
            {
                "created_at": "2026-08-19T20:00:00+00:00",
                "nav": 252_500.0,
                "realized_pnl": 500.0,
                "unrealized_pnl": 2_000.0,
            },
        ],
    }
    briefing = {
        "status": "hold",
        "portfolio_decision": "Maintain current weights",
        "candidate_identifier": "candidate:test",
        "evidence_that_changes_conclusion": ["Rates reprice materially"],
    }
    construction = {
        "status": "blocked",
        "blocks": ["Liquidity evidence unavailable"],
        "trades": [],
    }
    operating = SimpleNamespace(
        label="Operational",
        headline="Portfolio operating normally",
        detail="Operating evidence current",
    )
    asset_class_evaluation = {
        "successful": 2,
        "attempted": 3,
        "as_of": "2026-08-19T20:15:00+00:00",
        "source": "Current comprehensive evaluation attempt",
        "rows": [
            {
                "key": "us_equity",
                "asset_class": "U.S. equities",
                "status": "Evaluated",
                "detail": "500 cataloged · 80 deep analyzed · 12 selected",
            },
            {
                "key": "crypto",
                "asset_class": "Crypto",
                "status": "Evaluated",
                "detail": "120 cataloged · 30 deep analyzed · 5 selected",
            },
            {
                "key": "fixed_income",
                "asset_class": "Fixed income",
                "status": "Failed",
                "detail": "Evaluation evidence failed · ProviderEvidenceError",
            },
        ],
    }
    return portfolio_only_runtime._command_center_html(
        totals=totals,
        mandate=mandate,
        briefing=briefing,
        construction=construction,
        operating_status=operating,
        asset_class_evaluation=asset_class_evaluation,
    )


def test_command_center_mirrors_crypto_information_hierarchy() -> None:
    html = _fixture_html()

    for expected in (
        "Portfolio Command Center",
        "PAPER · $250K GENESIS",
        "AUTO PAPER EXECUTION · ON",
        "LIVE MONEY · DISABLED",
        "Current portfolio NAV",
        "Starting capital",
        "Cash",
        "Deployed",
        "Realized P&L",
        "Unrealized P&L",
        "Max drawdown",
        "Open positions",
        "Equity curve",
        "P&L attribution",
        "Open paper positions",
        "Recent paper trades",
        "Skipped / rejected allocations",
        "Asset class evaluation status",
        "Decision pipeline status",
        "What needs attention next",
    ):
        assert expected in html


def test_command_center_surfaces_asset_class_evaluation_coverage_and_statuses() -> None:
    html = _fixture_html()

    assert "Asset classes evaluated" in html
    assert "2 / 3" in html
    assert "2 / 3 successful" in html
    assert "U.S. equities" in html
    assert "Crypto" in html
    assert "Fixed income" in html
    assert "Evaluated" in html
    assert "Failed" in html
    assert "ProviderEvidenceError" in html
    assert "Current comprehensive evaluation attempt" in html


def test_command_center_surfaces_current_blockers_and_watch_conditions() -> None:
    html = _fixture_html()

    assert "Liquidity evidence unavailable" in html
    assert "Rates reprice materially" in html
    assert "candidate:test" in html
    assert "Maintain current weights" in html
    assert "Operating evidence current" in html


def test_command_center_keeps_capital_authority_boundaries_visible() -> None:
    html = _fixture_html()

    assert "CIO-only authority" in html
    assert "Paper-only system" in html
    assert "no live-money execution" in html
    assert "Live execution" in html
    assert "No authority" in html


def test_command_center_is_mobile_responsive_and_dependency_free() -> None:
    html = _fixture_html()

    assert "@media(max-width:650px)" in html
    assert "@media(max-width:1050px)" in html
    assert "<script" not in html
    assert "https://" not in html
    assert "<svg" in html
