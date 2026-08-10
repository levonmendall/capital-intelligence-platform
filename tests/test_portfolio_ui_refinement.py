from __future__ import annotations

from portfolio_ui_refinement import (
    _meaningful_trade,
    _pnl_attribution,
    _portfolio_state,
    _target_weights,
    _trade_weights,
    _weight_text,
)


def test_portfolio_state_uses_canonical_components_and_preserves_sub_percent_exposure() -> None:
    mandate = {
        "nav": 249_995.65,
        "cash_base_total": 248_899.06,
        "holdings": [
            {
                "symbol": "MCD",
                "market_value": 1_096.59,
                "unrealized_gain": 5.75,
            }
        ],
    }

    state = _portfolio_state(mandate)

    assert state["reconciled"] is True
    assert state["reconciliation_residual"] == 0.0
    assert round(float(state["deployed"]) * 100, 2) == 0.44
    assert _weight_text(float(state["deployed"])) == "0.44%"
    assert _weight_text(float(state["cash_weight"])) == "99.56%"


def test_pnl_attribution_surfaces_unexplained_residual_instead_of_inventing_source() -> None:
    mandate = {
        "total_pnl": -4.35,
        "realized_pnl": 0.0,
        "unrealized_pnl": 5.75,
        "cash_fx_pnl": 0.0,
        "non_trade_pnl": 0.0,
        "fees_paid": 0.0,
    }

    rows = dict(_pnl_attribution(mandate))

    assert rows["Unrealized P&L"] == 5.75
    assert round(rows["Accounting residual"], 2) == -10.10
    assert round(
        rows["Realized P&L"]
        + rows["Unrealized P&L"]
        + rows["Cash / FX P&L"]
        + rows["Other recorded P&L"]
        + rows["Implementation costs"]
        + rows["Accounting residual"],
        2,
    ) == rows["Total P&L"]


def test_pnl_attribution_separates_recorded_fees_from_remaining_residual() -> None:
    mandate = {
        "total_pnl": -4.35,
        "realized_pnl": 0.0,
        "unrealized_pnl": 5.75,
        "cash_fx_pnl": 0.0,
        "non_trade_pnl": 0.0,
        "fees_paid": 10.10,
    }

    rows = dict(_pnl_attribution(mandate))

    assert rows["Implementation costs"] == -10.10
    assert round(rows["Accounting residual"], 2) == 0.0


def test_weight_text_does_not_round_real_tiny_weight_to_zero() -> None:
    assert _weight_text(0.0) == "0.00%"
    assert _weight_text(0.000049) == "<0.01%"
    assert _weight_text(-0.000049) == ">-0.01%"
    assert _weight_text(0.00438646) == "0.44%"


def test_trade_weight_aliases_support_construction_trade_proposal_payload() -> None:
    trade = {
        "symbol": "MCD",
        "side": "sell",
        "from_weight": 0.0044,
        "to_weight": 0.0,
    }

    assert _trade_weights(trade) == (0.0044, 0.0)
    assert _meaningful_trade(trade) is True


def test_zero_delta_trade_is_not_presented_as_outstanding() -> None:
    trade = {
        "symbol": "KLAC",
        "side": "sell",
        "from_weight": 0.0,
        "to_weight": 0.0,
    }

    assert _meaningful_trade(trade) is False


def test_target_weights_use_canonical_construction_target_map() -> None:
    holdings = (
        {"symbol": "MCD", "market_value": 1_096.59},
    )
    construction = {
        "target_cash_weight": 0.90,
        "target_weights": [["MCD", 0.10]],
    }

    targets, cash = _target_weights(
        construction,
        holdings,
        249_995.65,
        248_899.06 / 249_995.65,
    )

    assert targets == {"MCD": 0.10}
    assert cash == 0.90


def test_target_weights_fall_back_to_current_portfolio_without_construction() -> None:
    holdings = (
        {"symbol": "MCD", "market_value": 1_096.59},
    )
    nav = 249_995.65
    cash_weight = 248_899.06 / nav

    targets, cash = _target_weights(None, holdings, nav, cash_weight)

    assert round(targets["MCD"], 8) == round(1_096.59 / nav, 8)
    assert cash == cash_weight
