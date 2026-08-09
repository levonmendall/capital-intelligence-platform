"""Presentation-only Portfolio refinement for clearer current state and implementation.

This module changes only Streamlit presentation. It does not alter CIO authority,
portfolio construction, evidence, execution, thresholds, or paper-trading controls.
"""

from __future__ import annotations

from html import escape
from types import ModuleType
from typing import Mapping, Sequence

import pandas as pd
import streamlit as st

_INSTALLED = "_portfolio_clarity_refinement_installed"


def _text(value: object, fallback: str = "Unavailable") -> str:
    value = " ".join(str(value or "").split())
    return value or fallback


def _percent(value: float, *, decimals: int = 2) -> str:
    return f"{value:.{decimals}%}"


def _holding_cards(app: ModuleType, holdings: Sequence[Mapping[str, object]], cash: float, nav: float) -> None:
    app.page_header(
        "Current holdings",
        "What the portfolio owns now, including cash and current portfolio weights.",
        "02",
    )
    if holdings:
        for holding in holdings:
            symbol = _text(holding.get("symbol"), "Position")
            value = float(holding.get("market_value", 0.0) or 0.0)
            weight = 0.0 if nav <= 0 else value / nav
            pnl = float(holding.get("unrealized_gain", 0.0) or 0.0)
            st.markdown(
                '<div class="portfolio-position-card">'
                f'<div><strong>{escape(symbol)}</strong><span>{escape(_text(holding.get("asset_class"), "Governed holding"))}</span></div>'
                f'<div><strong>{escape(app.format_currency(value))}</strong><span>{escape(_percent(weight))} of portfolio</span></div>'
                f'<div><strong>{escape(app.format_currency(pnl))}</strong><span>Unrealized P&amp;L</span></div>'
                '</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("There are no invested positions in the canonical portfolio.")
    cash_weight = 0.0 if nav <= 0 else cash / nav
    st.markdown(
        '<div class="portfolio-position-card cash">'
        '<div><strong>Cash</strong><span>Optionality reserve</span></div>'
        f'<div><strong>{escape(app.format_currency(cash))}</strong><span>{escape(_percent(cash_weight))} of portfolio</span></div>'
        '<div><strong>Available</strong><span>Subject to CIO authorization</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _implementation_cards(app: ModuleType, construction: Mapping[str, object] | None) -> None:
    if not isinstance(construction, Mapping):
        st.info("No portfolio implementation is currently outstanding.")
        return
    trades = tuple(item for item in construction.get("trades", ()) if isinstance(item, Mapping))
    if not trades:
        st.info("No portfolio implementation is currently outstanding.")
        return
    for trade in trades:
        symbol = _text(trade.get("symbol"), "Position")
        action = _text(trade.get("action") or trade.get("side"), "Adjust").upper()
        current = float(trade.get("current_weight", trade.get("current", 0.0)) or 0.0)
        target = float(trade.get("target_weight", trade.get("target", 0.0)) or 0.0)
        change = target - current
        rationale = _text(trade.get("rationale"), "Previously authorized portfolio implementation.")
        st.markdown(
            '<div class="portfolio-action-card">'
            f'<div class="portfolio-action-head"><strong>{escape(symbol)}</strong><span>{escape(action)}</span></div>'
            '<div class="portfolio-action-metrics">'
            f'<div><small>Current</small><strong>{escape(_percent(current))}</strong></div>'
            f'<div><small>Target</small><strong>{escape(_percent(target))}</strong></div>'
            f'<div><small>Change</small><strong>{escape(_percent(change))}</strong></div>'
            '</div>'
            f'<p><strong>Why:</strong> {escape(rationale)}</p>'
            '</div>',
            unsafe_allow_html=True,
        )


def install(app: ModuleType) -> None:
    """Install the final Portfolio renderer after other UI refinements."""
    if getattr(app, _INSTALLED, False):
        return

    st.markdown(
        """<style>
        .portfolio-position-card,.portfolio-action-card{border:1px solid rgba(145,160,190,.22);border-radius:22px;background:rgba(8,15,30,.72);padding:18px 20px;margin:10px 0;box-shadow:inset 0 1px 0 rgba(255,255,255,.025)}
        .portfolio-position-card{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:14px;align-items:center}.portfolio-position-card>div{display:flex;flex-direction:column;gap:4px}.portfolio-position-card span,.portfolio-action-card small,.portfolio-action-card p{color:#91a0b9;font-size:.82rem}.portfolio-position-card strong{color:#f3f6ff}.portfolio-position-card.cash{border-color:rgba(55,211,210,.18)}
        .portfolio-action-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}.portfolio-action-head span{font-size:.78rem;letter-spacing:.12em;color:#a57bff}.portfolio-action-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.portfolio-action-metrics>div{display:flex;flex-direction:column;gap:5px;padding:11px;border-radius:14px;background:rgba(255,255,255,.025)}.portfolio-action-card p{margin:14px 2px 0}
        @media(max-width:700px){.portfolio-position-card{grid-template-columns:1fr 1fr}.portfolio-position-card>div:last-child{grid-column:1/-1}.portfolio-action-card{padding:16px}.portfolio-action-metrics{gap:6px}.portfolio-action-metrics>div{padding:9px 7px}.portfolio-action-metrics strong{font-size:.9rem}}
        </style>""",
        unsafe_allow_html=True,
    )

    @st.fragment(run_every="30s")
    def render_portfolio(dependencies: object, *, principal: object | None) -> None:
        construction = app._latest("portfolio_construction")
        briefing = app._latest("daily_cio_briefing")
        mandate = dependencies.get_mandate_details(app.CANONICAL_PORTFOLIO_CODE)
        if mandate is None:
            st.warning("The canonical paper portfolio is unavailable.")
            return

        nav = float(mandate["nav"])
        cash = float(mandate["cash"])
        invested = max(nav - cash, 0.0)
        deployed = 0.0 if nav <= 0 else invested / nav
        cash_weight = 0.0 if nav <= 0 else cash / nav
        holdings = tuple(item for item in mandate.get("holdings", ()) if isinstance(item, Mapping))
        decision = app._plain_text(
            briefing.get("portfolio_decision") if isinstance(briefing, Mapping) else None,
            "No new portfolio action is currently authorized.",
        )
        why = app._plain_text(
            briefing.get("why_it_matters") if isinstance(briefing, Mapping) else None,
            "Capital remains where it is until a superior opportunity clears the complete governed process.",
        )
        trades = tuple(construction.get("trades", ())) if isinstance(construction, Mapping) else ()
        outstanding = len(trades)

        app.render_information_freshness(briefing=briefing, surface="portfolio")
        app.page_header(
            "Portfolio",
            "What the portfolio owns, why it is positioned this way, and whether anything is changing.",
            "01",
        )
        app.metric_grid(
            (
                ("Portfolio value", app.format_currency(nav), "Canonical NAV"),
                ("Available cash", app.format_currency(cash), f"{_percent(cash_weight)} of portfolio"),
                ("Capital deployed", _percent(deployed), app.format_currency(invested)),
                ("Total P&L", app.format_currency(mandate.get("total_pnl", 0.0)), app.format_percent(mandate["total_return"])),
            ),
            variant="portfolio",
        )

        _holding_cards(app, holdings, cash, nav)

        app.page_header("CIO decision", "The latest governed portfolio conclusion.", "03")
        app.callout_card(
            "Current CIO decision",
            decision,
            why,
        )
        st.caption(
            f"Current posture: {_percent(deployed)} invested · {_percent(cash_weight)} cash. "
            "The CIO decision is separate from any previously authorized implementation still in progress."
        )

        app.page_header("Capital deployment", "Current invested capital versus available cash.", "04")
        app.allocation_bar(cash=cash, nav=nav)
        app.metric_grid(
            (
                ("Invested", app.format_currency(invested), _percent(deployed)),
                ("Available cash", app.format_currency(cash), _percent(cash_weight)),
            ),
            variant="portfolio",
        )
        st.caption("Capital is deployed only when an opportunity clears the full governed investment process.")

        app.page_header("Outstanding portfolio actions", "Previously authorized implementation that has not fully completed.", "05")
        if outstanding:
            st.caption(f"{outstanding} pending portfolio adjustment{'s' if outstanding != 1 else ''}. A pending implementation does not mean the current CIO decision authorized a new trade.")
        _implementation_cards(app, construction if isinstance(construction, Mapping) else None)

        with st.expander("Paper implementation & controls", expanded=False):
            app.render_pending_transaction_report(construction=construction, briefing=briefing)
            app.render_paper_decision_controls(construction=construction, briefing=briefing, principal=principal)

        with st.expander("Governance & audit details", expanded=False):
            st.caption(
                "Paper-only portfolio · CIO-only investment authority · real-money execution disabled. "
                f"Valuation as of {app.format_datetime(mandate.get('as_of'))}."
            )
            if isinstance(construction, Mapping):
                app.metric_grid(
                    (
                        ("Construction state", app._status_title(construction.get("status")), "Paper implementation"),
                        ("Turnover", app.format_percent(construction.get("turnover", 0.0)), "Portfolio movement"),
                        ("Estimated cost", app.format_percent(construction.get("estimated_cost_return", 0.0)), "Return drag"),
                        ("Expected improvement", app.format_percent(construction.get("expected_return_improvement", 0.0)), "Net opportunity"),
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


__all__ = ["install"]
