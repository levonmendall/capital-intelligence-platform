"""Presentation-only Portfolio command center.

This module changes only Streamlit presentation. It reads the canonical portfolio,
recorded CIO briefing, portfolio construction, and benchmark evaluation evidence.
It does not change investment authority, thresholds, construction, execution, or
paper-trading controls.
"""

from __future__ import annotations

from html import escape
from types import ModuleType
from typing import Mapping, Sequence

import pandas as pd
import streamlit as st

from benchmark_portfolio_comparison import (
    BenchmarkPortfolioComparison,
    load_benchmark_portfolio_comparison,
)

_INSTALLED = "_portfolio_command_center_installed"
_EPSILON = 1e-9


def _text(value: object, fallback: str = "Unavailable") -> str:
    normalized = " ".join(str(value or "").split())
    return normalized or fallback


def _number(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percent(value: float, *, decimals: int = 2) -> str:
    return f"{float(value):.{decimals}%}"


def _weight_text(value: float) -> str:
    """Render exact allocation intent without rounding a real exposure to zero."""
    normalized = float(value)
    if normalized == 0.0:
        return "0.00%"
    if 0.0 < normalized < 0.00005:
        return "<0.01%"
    if -0.00005 < normalized < 0.0:
        return ">-0.01%"
    return _percent(normalized)


def _portfolio_state(mandate: Mapping[str, object]) -> dict[str, object]:
    holdings = tuple(
        item
        for item in mandate.get("holdings", ())
        if isinstance(item, Mapping)
    )
    nav = _number(mandate.get("nav"))
    cash = _number(mandate.get("cash_base_total", mandate.get("cash")))
    holdings_value = round(
        sum(_number(item.get("market_value")) for item in holdings),
        8,
    )
    invested = max(holdings_value, 0.0)
    deployed = 0.0 if nav <= 0.0 else invested / nav
    cash_weight = 0.0 if nav <= 0.0 else cash / nav
    # Portfolio values are canonical decimal-money values. Round the display
    # reconciliation to their preserved precision so binary floating-point noise
    # cannot manufacture a false variance on an exactly balanced snapshot.
    reconciliation_residual = round(nav - cash - holdings_value, 8)
    tolerance = max(0.01, abs(nav) * 1e-8)
    return {
        "holdings": holdings,
        "nav": nav,
        "cash": cash,
        "holdings_value": holdings_value,
        "invested": invested,
        "deployed": deployed,
        "cash_weight": cash_weight,
        "reconciliation_residual": reconciliation_residual,
        "reconciled": abs(reconciliation_residual) <= tolerance,
        "tolerance": tolerance,
    }


def _pnl_attribution(mandate: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    """Return a dollar bridge that always reconciles to canonical total P&L."""
    total = _number(mandate.get("total_pnl"))
    realized = _number(mandate.get("realized_pnl"))
    unrealized = _number(mandate.get("unrealized_pnl"))
    cash_fx = _number(mandate.get("cash_fx_pnl"))
    non_trade = _number(mandate.get("non_trade_pnl"))
    fees = -abs(_number(mandate.get("fees_paid")))
    explained = realized + unrealized + cash_fx + non_trade + fees
    residual = total - explained
    return (
        ("Realized P&L", realized),
        ("Unrealized P&L", unrealized),
        ("Cash / FX P&L", cash_fx),
        ("Other recorded P&L", non_trade),
        ("Implementation costs", fees),
        ("Accounting residual", residual),
        ("Total P&L", total),
    )


def _trade_weights(trade: Mapping[str, object]) -> tuple[float | None, float | None]:
    current = _optional_number(
        trade.get("from_weight", trade.get("current_weight", trade.get("current")))
    )
    target = _optional_number(
        trade.get("to_weight", trade.get("target_weight", trade.get("target")))
    )
    return current, target


def _meaningful_trade(trade: Mapping[str, object]) -> bool:
    """Exclude completed/zero-delta records from the outstanding-action surface."""
    current, target = _trade_weights(trade)
    if current is None or target is None:
        return True
    return abs(target - current) > _EPSILON


def _target_weights(
    construction: Mapping[str, object] | None,
    holdings: Sequence[Mapping[str, object]],
    nav: float,
    cash_weight: float,
) -> tuple[dict[str, float], float]:
    current = {
        _text(item.get("symbol"), "Position"): (
            0.0 if nav <= 0.0 else _number(item.get("market_value")) / nav
        )
        for item in holdings
    }
    if not isinstance(construction, Mapping):
        return current, cash_weight

    parsed: dict[str, float] = {}
    raw_targets = construction.get("target_weights")
    if isinstance(raw_targets, Mapping):
        parsed = {
            _text(symbol): _number(weight)
            for symbol, weight in raw_targets.items()
        }
    elif isinstance(raw_targets, Sequence) and not isinstance(raw_targets, (str, bytes)):
        for item in raw_targets:
            if isinstance(item, Mapping):
                symbol = item.get("symbol")
                weight = item.get("weight", item.get("target_weight"))
                if symbol is not None and _optional_number(weight) is not None:
                    parsed[_text(symbol)] = _number(weight)
            elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)) and len(item) >= 2:
                parsed[_text(item[0])] = _number(item[1])

    if parsed:
        target_cash = _optional_number(construction.get("target_cash_weight"))
        if target_cash is None:
            target_cash = max(0.0, 1.0 - sum(parsed.values()))
        return parsed, target_cash

    target = dict(current)
    for trade in construction.get("trades", ()):
        if not isinstance(trade, Mapping):
            continue
        _, to_weight = _trade_weights(trade)
        if to_weight is not None:
            target[_text(trade.get("symbol"), "Position")] = max(to_weight, 0.0)
    target_cash = _optional_number(construction.get("target_cash_weight"))
    if target_cash is None:
        target_cash = max(0.0, 1.0 - sum(target.values()))
    return target, target_cash


def _prior_snapshot(mandate: Mapping[str, object]) -> Mapping[str, object] | None:
    current_identifier = _text(mandate.get("snapshot_identifier"), "")
    snapshots = [
        item
        for item in mandate.get("snapshots", ())
        if isinstance(item, Mapping)
        and _text(item.get("id"), "") != current_identifier
    ]
    if not snapshots:
        return None
    return max(snapshots, key=lambda item: _text(item.get("created_at"), ""))


def _benchmark_rows(comparison: BenchmarkPortfolioComparison) -> tuple[object, ...]:
    return tuple(
        row
        for row in comparison.rows
        if row.compounded_return is not None
    )


def _render_health_strip(
    app: ModuleType,
    *,
    state: Mapping[str, object],
    mandate: Mapping[str, object],
    comparison: BenchmarkPortfolioComparison,
    pending_count: int,
) -> None:
    reconciliation = (
        "✓ Reconciled"
        if bool(state["reconciled"])
        else f"⚠ Reconciliation variance {app.format_currency(state['reconciliation_residual'])}"
    )
    benchmark_state = {
        "available": "Benchmark current",
        "partial": "Benchmark partial",
        "unavailable": "Benchmark building",
    }.get(comparison.state, "Benchmark unavailable")
    st.markdown(
        '<div class="portfolio-health-strip">'
        f'<span>{escape(reconciliation)}</span>'
        f'<span>Valuation · {escape(app.format_datetime(mandate.get("as_of")))}</span>'
        f'<span>{escape(benchmark_state)}</span>'
        f'<span>{pending_count} pending action{"s" if pending_count != 1 else ""}</span>'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_cio_positioning(
    app: ModuleType,
    *,
    briefing: Mapping[str, object] | None,
    deployed: float,
    cash_weight: float,
) -> None:
    decision = app._plain_text(
        briefing.get("portfolio_decision") if isinstance(briefing, Mapping) else None,
        "No new portfolio action is currently authorized.",
    )
    why = app._plain_text(
        briefing.get("why_it_matters") if isinstance(briefing, Mapping) else None,
        "Capital remains where it is until a superior opportunity clears the governed process.",
    )
    changed = app._plain_text(
        briefing.get("what_changed") if isinstance(briefing, Mapping) else None,
        "No material portfolio-level change was recorded.",
    )
    st.markdown(
        '<section class="portfolio-cio-card">'
        '<div class="portfolio-kicker">LATEST CIO POSITIONING</div>'
        f'<h3>{escape(decision)}</h3>'
        f'<p>{escape(why)}</p>'
        '<div class="portfolio-cio-meta">'
        f'<span>{escape(_weight_text(deployed))} invested</span>'
        f'<span>{escape(_weight_text(cash_weight))} cash</span>'
        f'<span>{escape(changed)}</span>'
        '</div>'
        '</section>',
        unsafe_allow_html=True,
    )
    change_conditions = (
        briefing.get("evidence_that_changes_conclusion", ())
        if isinstance(briefing, Mapping)
        else ()
    )
    if isinstance(change_conditions, str):
        change_text = change_conditions.strip()
    elif isinstance(change_conditions, Sequence):
        change_text = " • ".join(
            _text(item, "")
            for item in change_conditions
            if _text(item, "")
        )
    else:
        change_text = ""
    if change_text:
        st.caption(f"What could change the posture: {change_text}")


def _render_benchmark_comparison(
    app: ModuleType,
    comparison: BenchmarkPortfolioComparison,
) -> None:
    app.page_header(
        "Performance vs benchmarks",
        "Same-window portfolio performance against recorded reference markets.",
        "03",
    )
    rows = _benchmark_rows(comparison)
    market_rows = tuple(row for row in rows if row.kind != "system")
    system = next((row for row in rows if row.kind == "system"), None)

    if system is None:
        st.info(comparison.detail)
        st.caption(
            "Benchmark history is building from point-in-time evidence. Missing observations are never estimated or backfilled."
        )
        return

    primary = next((row for row in market_rows if row.symbol == "SPY"), None)
    cash_like = next((row for row in market_rows if row.symbol == "SGOV"), None)
    app.metric_grid(
        (
            (
                "Portfolio return",
                _percent(system.compounded_return),
                f"{comparison.observation_count} recorded observation{'s' if comparison.observation_count != 1 else ''}",
            ),
            (
                "S&P 500 excess",
                "Unavailable" if primary is None else _percent(system.compounded_return - primary.compounded_return),
                "System minus SPY · same window",
            ),
            (
                "Cash-like excess",
                "Unavailable" if cash_like is None else _percent(system.compounded_return - cash_like.compounded_return),
                "System minus SGOV · same window",
            ),
            (
                "Max drawdown",
                "Unavailable" if comparison.system_maximum_drawdown is None else _percent(comparison.system_maximum_drawdown),
                "Recorded system evidence",
            ),
        ),
        variant="portfolio",
    )

    if market_rows:
        scale = max(
            0.001,
            max(abs(float(row.compounded_return)) for row in rows),
        )
        for row in rows:
            value = float(row.compounded_return)
            width = min(abs(value) / scale * 48.0, 48.0)
            left = 50.0 if value >= 0.0 else 50.0 - width
            css_class = "system" if row.kind == "system" else "reference"
            relative = (
                "Canonical portfolio"
                if row.kind == "system"
                else f"{_percent(system.compounded_return - value)} excess return"
            )
            label = row.label if row.symbol is None else f"{row.label} · {row.symbol}"
            st.markdown(
                '<div class="portfolio-benchmark-row">'
                f'<div class="portfolio-benchmark-label"><strong>{escape(label)}</strong><span>{escape(relative)}</span></div>'
                '<div class="portfolio-benchmark-track"><i></i>'
                f'<b class="{css_class}" style="left:{left:.2f}%;width:{width:.2f}%"></b></div>'
                f'<strong class="portfolio-benchmark-value">{escape(_percent(value))}</strong>'
                '</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info(
            "The portfolio return is recorded, but market benchmark returns are not yet available for the same evidence window."
        )

    st.caption(
        f"{comparison.detail} Evaluation window: {app.format_datetime(comparison.period_start)} → "
        f"{app.format_datetime(comparison.period_end)}. Benchmark results are evaluation-only."
    )


def _render_allocation(
    app: ModuleType,
    *,
    state: Mapping[str, object],
    construction: Mapping[str, object] | None,
) -> dict[str, float]:
    holdings = state["holdings"]
    nav = float(state["nav"])
    current = {
        _text(item.get("symbol"), "Position"): (
            0.0 if nav <= 0.0 else _number(item.get("market_value")) / nav
        )
        for item in holdings
    }
    current["Cash"] = float(state["cash_weight"])
    target, target_cash = _target_weights(
        construction,
        holdings,
        nav,
        float(state["cash_weight"]),
    )
    target = dict(target)
    target["Cash"] = target_cash

    app.page_header(
        "Current → target allocation",
        "Actual economic ownership now versus the latest construction target.",
        "04",
    )
    names = list(dict.fromkeys([*current.keys(), *target.keys()]))
    for name in names:
        current_weight = max(current.get(name, 0.0), 0.0)
        target_weight = max(target.get(name, 0.0), 0.0)
        st.markdown(
            '<div class="portfolio-allocation-row">'
            f'<div><strong>{escape(name)}</strong><span>Current {escape(_weight_text(current_weight))} · Target {escape(_weight_text(target_weight))}</span></div>'
            '<div class="portfolio-allocation-bars">'
            f'<span class="current" style="width:{min(current_weight * 100.0, 100.0):.4f}%"></span>'
            f'<span class="target" style="width:{min(target_weight * 100.0, 100.0):.4f}%"></span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    st.caption(
        "Current is the reconciled canonical portfolio. Target is construction intent only; pending implementation is shown separately."
    )
    return target


def _render_holdings(
    app: ModuleType,
    *,
    holdings: Sequence[Mapping[str, object]],
    nav: float,
    target: Mapping[str, float],
) -> None:
    app.page_header(
        "Current holdings",
        "Canonical positions with valuation, cost basis, P&L, and target context.",
        "05",
    )
    if not holdings:
        st.info("There are no invested positions in the canonical portfolio.")
        return
    for holding in holdings:
        symbol = _text(holding.get("symbol"), "Position")
        value = _number(holding.get("market_value"))
        weight = 0.0 if nav <= 0.0 else value / nav
        target_weight = target.get(symbol)
        pnl = _number(holding.get("unrealized_gain"))
        pnl_return = _number(holding.get("unrealized_return"))
        quantity = _number(holding.get("quantity"))
        price = _number(holding.get("current_price"))
        cost_basis = _number(holding.get("cost_basis"))
        asset_class = _text(holding.get("asset_class"), "Governed holding").replace("_", " ").title()
        st.markdown(
            '<div class="portfolio-position-card">'
            '<div class="portfolio-position-title">'
            f'<strong>{escape(symbol)}</strong><span>{escape(asset_class)}</span>'
            '</div>'
            f'<div><small>Market value</small><strong>{escape(app.format_currency(value))}</strong><span>{escape(_weight_text(weight))} current</span></div>'
            f'<div><small>Target</small><strong>{"Unavailable" if target_weight is None else escape(_weight_text(target_weight))}</strong><span>Construction intent</span></div>'
            f'<div><small>Unrealized P&L</small><strong>{escape(app.format_currency(pnl))}</strong><span>{escape(_percent(pnl_return))}</span></div>'
            f'<div><small>Position</small><strong>{quantity:,.4f}</strong><span>@ {escape(app.format_currency(price))}</span></div>'
            f'<div><small>Cost basis</small><strong>{escape(app.format_currency(cost_basis))}</strong><span>Recorded basis</span></div>'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_cash_thesis(
    app: ModuleType,
    *,
    briefing: Mapping[str, object] | None,
    cash: float,
    cash_weight: float,
) -> None:
    app.page_header(
        "Why capital is in cash",
        "Cash is an active portfolio position until expected opportunity clears the complete process.",
        "06",
    )
    rationale = app._plain_text(
        briefing.get("why_it_matters") if isinstance(briefing, Mapping) else None,
        "No superior opportunity has been authorized from the currently recorded evidence.",
    )
    opportunity = app._plain_text(
        briefing.get("opportunity_or_risk") if isinstance(briefing, Mapping) else None,
        "No separate qualified opportunity is recorded.",
    )
    st.markdown(
        '<div class="portfolio-cash-card">'
        f'<div><small>Available cash</small><strong>{escape(app.format_currency(cash))}</strong><span>{escape(_weight_text(cash_weight))} of NAV</span></div>'
        f'<div><small>Why</small><strong>{escape(rationale)}</strong></div>'
        f'<div><small>Opportunity / risk</small><strong>{escape(opportunity)}</strong></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_pnl_attribution(app: ModuleType, mandate: Mapping[str, object]) -> None:
    app.page_header(
        "Performance attribution",
        "A dollar bridge from recorded portfolio components to total P&L.",
        "07",
    )
    rows = _pnl_attribution(mandate)
    total = rows[-1][1]
    components = rows[:-1]
    nonzero = tuple((label, value) for label, value in components if abs(value) > 0.004)
    if not nonzero:
        nonzero = components
    max_abs = max((abs(value) for _, value in nonzero), default=1.0)
    for label, value in nonzero:
        width = 0.0 if max_abs == 0.0 else min(abs(value) / max_abs * 100.0, 100.0)
        st.markdown(
            '<div class="portfolio-attribution-row">'
            f'<span>{escape(label)}</span>'
            f'<div><i style="width:{width:.2f}%"></i></div>'
            f'<strong>{escape(app.format_currency(value))}</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        '<div class="portfolio-attribution-total">'
        f'<span>Total P&amp;L</span><strong>{escape(app.format_currency(total))}</strong>'
        '</div>',
        unsafe_allow_html=True,
    )
    residual = next(value for label, value in rows if label == "Accounting residual")
    if abs(residual) > 0.01:
        st.caption(
            "The accounting residual is shown explicitly rather than assigning it to an unverified source. "
            "It includes any difference not explained by the displayed canonical P&L components after recorded implementation costs."
        )


def _render_risk_exposure(
    app: ModuleType,
    *,
    holdings: Sequence[Mapping[str, object]],
    nav: float,
    cash_weight: float,
) -> None:
    app.page_header(
        "Risk & exposure",
        "What the canonical holdings actually expose the portfolio to right now.",
        "08",
    )
    asset_classes: dict[str, float] = {}
    position_weights: list[float] = []
    for holding in holdings:
        value = _number(holding.get("market_value"))
        weight = 0.0 if nav <= 0.0 else value / nav
        label = _text(holding.get("asset_class"), "Unknown").replace("_", " ").title()
        asset_classes[label] = asset_classes.get(label, 0.0) + weight
        position_weights.append(weight)
    exposures = [("Cash", cash_weight), *sorted(asset_classes.items(), key=lambda item: item[1], reverse=True)]
    for label, weight in exposures:
        st.markdown(
            '<div class="portfolio-risk-row">'
            f'<span>{escape(label)}</span>'
            f'<div><i style="width:{min(max(weight, 0.0) * 100.0, 100.0):.4f}%"></i></div>'
            f'<strong>{escape(_weight_text(weight))}</strong>'
            '</div>',
            unsafe_allow_html=True,
        )
    app.metric_grid(
        (
            ("Invested positions", str(len(holdings)), "Canonical holdings"),
            (
                "Largest position",
                _weight_text(max(position_weights, default=0.0)),
                "Single-position concentration",
            ),
            ("Cash reserve", _weight_text(cash_weight), "Liquidity / optionality"),
        ),
        variant="portfolio",
    )
    st.caption(
        "Only exposures derivable from canonical holdings are shown here. Unrecorded beta, factor, volatility, or drawdown estimates are not inferred."
    )


def _render_what_changed(
    app: ModuleType,
    mandate: Mapping[str, object],
    state: Mapping[str, object],
) -> None:
    prior = _prior_snapshot(mandate)
    app.page_header(
        "What changed",
        "Difference from the prior recorded canonical portfolio snapshot.",
        "09",
    )
    if prior is None:
        st.info("A prior canonical snapshot is not available yet, so no portfolio delta is inferred.")
        return
    values = (
        ("NAV", float(state["nav"]), _number(prior.get("nav"))),
        ("Cash", float(state["cash"]), _number(prior.get("cash_base_total", prior.get("cash")))),
        ("Invested", float(state["holdings_value"]), _number(prior.get("holdings_value"))),
        ("Total P&L", _number(mandate.get("total_pnl")), _number(prior.get("total_pnl"))),
    )
    cards = []
    for label, current, previous in values:
        delta = current - previous
        cards.append((label, app.format_currency(current), f"{app.format_currency(delta)} vs prior snapshot"))
    app.metric_grid(tuple(cards), variant="portfolio")
    st.caption(f"Prior snapshot: {app.format_datetime(prior.get('created_at'))}")


def _render_implementation(
    app: ModuleType,
    *,
    construction: Mapping[str, object] | None,
) -> None:
    app.page_header(
        "Pending implementation",
        "Authorized construction changes that still have an economic delta.",
        "10",
    )
    raw_trades = tuple(
        trade
        for trade in (
            construction.get("trades", ())
            if isinstance(construction, Mapping)
            else ()
        )
        if isinstance(trade, Mapping)
    )
    pending = tuple(trade for trade in raw_trades if _meaningful_trade(trade))
    stale = len(raw_trades) - len(pending)
    if not pending:
        st.info("No outstanding economic portfolio adjustment is recorded.")
    for trade in pending:
        symbol = _text(trade.get("symbol"), "Position")
        action = _text(trade.get("side", trade.get("action")), "Adjust").upper()
        current, target = _trade_weights(trade)
        reason = _text(
            trade.get("reason", trade.get("rationale")),
            "Previously authorized portfolio implementation.",
        )
        change = None if current is None or target is None else target - current
        st.markdown(
            '<div class="portfolio-action-card">'
            f'<div class="portfolio-action-head"><strong>{escape(symbol)}</strong><span>{escape(action)}</span></div>'
            '<div class="portfolio-action-metrics">'
            f'<div><small>Current</small><strong>{"Unavailable" if current is None else escape(_weight_text(current))}</strong></div>'
            f'<div><small>Target</small><strong>{"Unavailable" if target is None else escape(_weight_text(target))}</strong></div>'
            f'<div><small>Change</small><strong>{"Unavailable" if change is None else escape(_weight_text(change))}</strong></div>'
            '</div>'
            f'<p><strong>Why:</strong> {escape(reason)}</p>'
            '</div>',
            unsafe_allow_html=True,
        )
    if stale:
        st.caption(
            f"{stale} zero-delta construction record{'s' if stale != 1 else ''} remain in the audit trail and are omitted from pending actions."
        )


def _install_style() -> None:
    st.markdown(
        """<style>
        .portfolio-health-strip{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 16px}.portfolio-health-strip span{border:1px solid rgba(145,160,190,.18);border-radius:999px;padding:6px 9px;color:#9aa8bf;font-size:.68rem;background:rgba(8,15,30,.55)}
        .portfolio-cio-card,.portfolio-position-card,.portfolio-cash-card,.portfolio-action-card{border:1px solid rgba(145,160,190,.20);border-radius:20px;background:rgba(8,15,30,.72);padding:16px 18px;margin:10px 0;box-shadow:inset 0 1px 0 rgba(255,255,255,.025)}
        .portfolio-cio-card{border-color:rgba(55,211,210,.22)}.portfolio-kicker{font-size:.66rem;letter-spacing:.15em;color:#37d3d2;margin-bottom:7px}.portfolio-cio-card h3{font-size:1.05rem;margin:0;color:#f3f6ff}.portfolio-cio-card p{color:#aab5c9;font-size:.83rem;line-height:1.5;margin:8px 0 12px}.portfolio-cio-meta{display:flex;gap:7px;flex-wrap:wrap}.portfolio-cio-meta span{font-size:.7rem;color:#aab5c9;background:rgba(255,255,255,.035);border-radius:999px;padding:5px 8px}
        .portfolio-benchmark-row{display:grid;grid-template-columns:minmax(130px,1.25fr) minmax(120px,1.5fr) 72px;align-items:center;gap:12px;padding:9px 2px;border-bottom:1px solid rgba(145,160,190,.10)}.portfolio-benchmark-label{display:flex;flex-direction:column;gap:2px}.portfolio-benchmark-label strong{color:#f3f6ff;font-size:.82rem}.portfolio-benchmark-label span{color:#91a0b9;font-size:.68rem}.portfolio-benchmark-track{height:9px;border-radius:999px;background:rgba(255,255,255,.035);position:relative;overflow:hidden}.portfolio-benchmark-track i{position:absolute;left:50%;top:0;bottom:0;width:1px;background:rgba(255,255,255,.28)}.portfolio-benchmark-track b{position:absolute;height:100%;border-radius:999px;background:#7f5cff}.portfolio-benchmark-track b.system{background:#37d3d2}.portfolio-benchmark-value{text-align:right;color:#f3f6ff;font-size:.8rem}
        .portfolio-allocation-row{display:grid;grid-template-columns:minmax(150px,.85fr) 1.5fr;gap:14px;align-items:center;padding:8px 0}.portfolio-allocation-row>div:first-child{display:flex;flex-direction:column;gap:2px}.portfolio-allocation-row strong{color:#f3f6ff;font-size:.82rem}.portfolio-allocation-row span{color:#91a0b9;font-size:.69rem}.portfolio-allocation-bars{height:18px;position:relative;background:rgba(255,255,255,.035);border-radius:999px;overflow:hidden}.portfolio-allocation-bars .current,.portfolio-allocation-bars .target{position:absolute;left:0;height:7px;border-radius:999px;min-width:2px}.portfolio-allocation-bars .current{top:2px;background:#37d3d2}.portfolio-allocation-bars .target{bottom:2px;background:#7f5cff}
        .portfolio-position-card{display:grid;grid-template-columns:1.1fr repeat(5,minmax(0,1fr));gap:12px;align-items:center}.portfolio-position-card>div{display:flex;flex-direction:column;gap:3px;min-width:0}.portfolio-position-card small,.portfolio-position-card span{color:#91a0b9;font-size:.68rem}.portfolio-position-card strong{color:#f3f6ff;font-size:.82rem;overflow-wrap:anywhere}.portfolio-position-title strong{font-size:.95rem}.portfolio-position-title span{text-transform:capitalize}
        .portfolio-cash-card{display:grid;grid-template-columns:.75fr 1.4fr 1.1fr;gap:14px}.portfolio-cash-card>div{display:flex;flex-direction:column;gap:4px}.portfolio-cash-card small,.portfolio-cash-card span{color:#91a0b9;font-size:.69rem}.portfolio-cash-card strong{color:#f3f6ff;font-size:.8rem;line-height:1.4}
        .portfolio-attribution-row,.portfolio-risk-row{display:grid;grid-template-columns:minmax(120px,.8fr) 1.5fr 94px;gap:12px;align-items:center;padding:7px 0}.portfolio-attribution-row span,.portfolio-risk-row span{color:#aab5c9;font-size:.76rem}.portfolio-attribution-row>div,.portfolio-risk-row>div{height:8px;background:rgba(255,255,255,.035);border-radius:999px;overflow:hidden}.portfolio-attribution-row i,.portfolio-risk-row i{display:block;height:100%;background:#7f5cff;border-radius:999px;min-width:2px}.portfolio-risk-row i{background:#37d3d2}.portfolio-attribution-row strong,.portfolio-risk-row strong{text-align:right;color:#f3f6ff;font-size:.76rem}.portfolio-attribution-total{display:flex;justify-content:space-between;margin-top:7px;padding-top:9px;border-top:1px solid rgba(145,160,190,.18);color:#f3f6ff;font-size:.82rem}
        .portfolio-action-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.portfolio-action-head strong{color:#f3f6ff}.portfolio-action-head span{font-size:.72rem;letter-spacing:.1em;color:#a57bff}.portfolio-action-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.portfolio-action-metrics>div{display:flex;flex-direction:column;gap:4px;padding:9px;border-radius:12px;background:rgba(255,255,255,.025)}.portfolio-action-metrics small,.portfolio-action-card p{color:#91a0b9;font-size:.72rem}.portfolio-action-metrics strong{color:#f3f6ff;font-size:.86rem}.portfolio-action-card p{margin:11px 1px 0;line-height:1.45}
        @media(max-width:700px){
          .portfolio-benchmark-row{grid-template-columns:1fr 68px}.portfolio-benchmark-track{grid-column:1/-1;grid-row:2}.portfolio-benchmark-label span{font-size:.64rem}
          .portfolio-allocation-row{grid-template-columns:1fr}.portfolio-allocation-bars{height:16px}
          .portfolio-position-card{grid-template-columns:repeat(2,minmax(0,1fr));padding:14px}.portfolio-position-title{grid-column:1/-1}
          .portfolio-cash-card{grid-template-columns:1fr}.portfolio-cio-card,.portfolio-action-card{padding:14px}
          .portfolio-attribution-row,.portfolio-risk-row{grid-template-columns:minmax(105px,.85fr) 1.2fr 76px;gap:8px}
        }
        </style>""",
        unsafe_allow_html=True,
    )


def install(app: ModuleType) -> None:
    """Install the final Portfolio renderer after other UI refinements."""
    if getattr(app, _INSTALLED, False):
        return

    _install_style()

    @st.fragment(run_every="30s")
    def render_portfolio(dependencies: object, *, principal: object | None) -> None:
        construction = app._latest("portfolio_construction")
        briefing = app._latest("daily_cio_briefing")
        mandate = dependencies.get_mandate_details(app.CANONICAL_PORTFOLIO_CODE)
        if mandate is None:
            st.warning("The canonical paper portfolio is unavailable.")
            return

        state = _portfolio_state(mandate)
        holdings = state["holdings"]
        nav = float(state["nav"])
        cash = float(state["cash"])
        comparison = load_benchmark_portfolio_comparison()
        raw_trades = tuple(
            trade
            for trade in (
                construction.get("trades", ())
                if isinstance(construction, Mapping)
                else ()
            )
            if isinstance(trade, Mapping)
        )
        pending_count = sum(1 for trade in raw_trades if _meaningful_trade(trade))

        app.render_information_freshness(briefing=briefing, surface="portfolio")
        app.page_header(
            "Portfolio",
            "Canonical capital, CIO positioning, performance, risk, and implementation in one view.",
            "01",
        )
        app.metric_grid(
            (
                ("Portfolio value", app.format_currency(nav), "Canonical NAV"),
                (
                    "Total P&L",
                    app.format_currency(mandate.get("total_pnl", 0.0)),
                    app.format_percent(mandate.get("total_return", 0.0)),
                ),
                (
                    "Capital deployed",
                    _weight_text(float(state["deployed"])),
                    app.format_currency(float(state["invested"])),
                ),
                (
                    "Available cash",
                    app.format_currency(cash),
                    _weight_text(float(state["cash_weight"])),
                ),
            ),
            variant="portfolio",
        )
        _render_health_strip(
            app,
            state=state,
            mandate=mandate,
            comparison=comparison,
            pending_count=pending_count,
        )
        if not bool(state["reconciled"]):
            st.warning(
                "Canonical cash plus holdings does not reconcile to NAV within the display tolerance. "
                "Portfolio allocations are shown from recorded components, but the variance is not hidden."
            )

        _render_cio_positioning(
            app,
            briefing=briefing if isinstance(briefing, Mapping) else None,
            deployed=float(state["deployed"]),
            cash_weight=float(state["cash_weight"]),
        )
        _render_benchmark_comparison(app, comparison)
        target = _render_allocation(
            app,
            state=state,
            construction=construction if isinstance(construction, Mapping) else None,
        )
        _render_holdings(
            app,
            holdings=holdings,
            nav=nav,
            target=target,
        )
        _render_cash_thesis(
            app,
            briefing=briefing if isinstance(briefing, Mapping) else None,
            cash=cash,
            cash_weight=float(state["cash_weight"]),
        )
        _render_pnl_attribution(app, mandate)
        _render_risk_exposure(
            app,
            holdings=holdings,
            nav=nav,
            cash_weight=float(state["cash_weight"]),
        )
        _render_what_changed(app, mandate, state)
        _render_implementation(
            app,
            construction=construction if isinstance(construction, Mapping) else None,
        )

        with st.expander("Paper implementation & controls", expanded=False):
            app.render_pending_transaction_report(
                construction=construction,
                briefing=briefing,
            )
            app.render_paper_decision_controls(
                construction=construction,
                briefing=briefing,
                principal=principal,
            )

        with st.expander("Governance & audit details", expanded=False):
            st.caption(
                "Actual portfolio = canonical economic ownership now. Target portfolio = construction intent. "
                "Pending implementation = authorized economic delta not yet reconciled. Closed and zero-delta records remain audit history."
            )
            st.caption(
                "Paper-only portfolio · CIO-only investment authority · real-money execution disabled. "
                f"Valuation as of {app.format_datetime(mandate.get('as_of'))}."
            )
            if isinstance(construction, Mapping):
                app.metric_grid(
                    (
                        (
                            "Construction state",
                            app._status_title(construction.get("status")),
                            "Paper implementation",
                        ),
                        (
                            "Turnover",
                            app.format_percent(construction.get("turnover", 0.0)),
                            "Portfolio movement",
                        ),
                        (
                            "Estimated cost",
                            app.format_percent(construction.get("estimated_cost_return", 0.0)),
                            "Return drag",
                        ),
                        (
                            "Expected improvement",
                            app.format_percent(construction.get("expected_return_improvement", 0.0)),
                            "Net opportunity",
                        ),
                    ),
                    variant="portfolio",
                )
            app.render_live_portfolio_marks(mandate)
            with st.expander("Recorded positions and capital path", expanded=False):
                if holdings:
                    app.display_frame(pd.DataFrame(holdings))
                else:
                    st.info("No invested positions are recorded.")

    app._render_portfolio = render_portfolio
    setattr(app, _INSTALLED, True)


__all__ = [
    "_meaningful_trade",
    "_pnl_attribution",
    "_portfolio_state",
    "_target_weights",
    "_trade_weights",
    "_weight_text",
    "install",
]
