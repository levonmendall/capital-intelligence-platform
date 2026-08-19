"""Minimal portfolio-only Streamlit runtime for the operating phase.

Capital Intelligence keeps the full CIO, evidence, construction, history and audit
machinery behind the interface.  During this phase the public product surface mirrors
the Crypto command-center philosophy: one canonical paper portfolio, its capital,
performance, positions and implementation history.  No UI element gains decision or
execution authority.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st

from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from premium_ui import apply_global_style, format_currency, format_percent


def portfolio_only_enabled() -> bool:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PORTFOLIO_ONLY_UI")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("RENDER", "").strip().lower() == "true"


def _drawdown(snapshots: list[dict[str, Any]]) -> float:
    navs = [
        float(item.get("nav", 0.0) or 0.0)
        for item in sorted(snapshots, key=lambda item: str(item.get("created_at", "")))
        if float(item.get("nav", 0.0) or 0.0) > 0.0
    ]
    if not navs:
        return 0.0
    peak = navs[0]
    worst = 0.0
    for nav in navs:
        peak = max(peak, nav)
        if peak > 0.0:
            worst = min(worst, nav / peak - 1.0)
    return worst


def _deployed(cash: float, nav: float) -> float:
    return 0.0 if nav <= 0.0 else max(0.0, min(1.0, (nav - cash) / nav))


def _positions_frame(holdings: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(holdings)
    if frame.empty:
        return frame
    columns = [
        item
        for item in (
            "symbol",
            "asset_class",
            "quantity",
            "current_price",
            "market_value",
            "unrealized_gain",
            "unrealized_return",
        )
        if item in frame.columns
    ]
    return frame[columns] if columns else frame


def _trades_frame(trades: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(trades[:25])
    if frame.empty:
        return frame
    columns = [
        item
        for item in (
            "created_at",
            "side",
            "symbol",
            "asset_class",
            "quantity",
            "price",
            "gross_amount_base",
            "realized_pnl_base",
            "cost_amount_base",
        )
        if item in frame.columns
    ]
    return frame[columns] if columns else frame


@st.fragment(run_every="30s")
def _render_portfolio_command_center(dependencies) -> None:
    totals = dependencies.get_portfolio_totals()
    mandate = dependencies.get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if not isinstance(mandate, dict):
        st.error("The canonical paper portfolio is unavailable.")
        return

    nav = float(totals.get("nav", mandate.get("nav", 0.0)) or 0.0)
    cash = float(totals.get("cash", mandate.get("cash", 0.0)) or 0.0)
    total_return = float(totals.get("total_return", mandate.get("total_return", 0.0)) or 0.0)
    total_pnl = float(totals.get("total_pnl", mandate.get("total_pnl", 0.0)) or 0.0)
    holdings = list(mandate.get("holdings", ()) or ())
    trades = list(mandate.get("trades", ()) or ())
    snapshots = list(mandate.get("snapshots", ()) or ())

    st.title("Portfolio")
    st.caption(
        "Capital Intelligence · canonical $250,000 paper portfolio · automatic paper operation · live money disabled"
    )

    metric_columns = st.columns(4)
    metric_columns[0].metric("Portfolio value", format_currency(nav))
    metric_columns[1].metric("Total return", format_percent(total_return))
    metric_columns[2].metric("Cash", format_currency(cash))
    metric_columns[3].metric("Capital deployed", format_percent(_deployed(cash, nav)))

    st.caption(
        f"Total P&L {format_currency(total_pnl)} · Maximum drawdown {format_percent(_drawdown(snapshots))} · "
        f"{len(holdings)} open position{'s' if len(holdings) != 1 else ''}"
    )

    st.divider()
    st.subheader("Performance")
    if snapshots:
        frame = pd.DataFrame(snapshots)
        if "created_at" in frame.columns and "nav" in frame.columns:
            frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
            chart = frame.dropna(subset=["created_at"]).sort_values("created_at")
            if not chart.empty:
                st.line_chart(chart.set_index("created_at")["nav"])
            else:
                st.info("The new portfolio is awaiting its first valuation history.")
        else:
            st.info("The new portfolio is awaiting its first valuation history.")
    else:
        st.info("The new portfolio is awaiting its first valuation history.")

    st.subheader("Positions")
    position_frame = _positions_frame(holdings)
    if position_frame.empty:
        st.info("The portfolio currently holds cash only.")
    else:
        st.dataframe(position_frame, use_container_width=True, hide_index=True)

    with st.expander("Paper implementation history", expanded=False):
        trade_frame = _trades_frame(trades)
        if trade_frame.empty:
            st.caption("No paper trades have been recorded in this portfolio epoch.")
        else:
            st.dataframe(trade_frame, use_container_width=True, hide_index=True)

    st.caption(
        "Only the CIO can authorize a portfolio change. The interface is read-only and cannot lower evidence, risk, liquidity, cost, construction or execution controls."
    )


def _minimal_identity_controls(secure_app_module, principal: Any) -> None:
    with st.sidebar:
        st.markdown("### Capital Intelligence")
        st.caption("Portfolio")
        if getattr(principal, "is_anonymous", False):
            st.caption("Read-only")
            return
        st.caption(str(getattr(principal, "display_name", "Authorized user")))
        if st.button("Sign out", key="portfolio-only-sign-out"):
            token = st.session_state.get("access_token")
            if token:
                secure_app_module.authentication_service().store.logout(token)
            secure_app_module._clear_session()
            st.rerun()


def install(app_impl_module, secure_app_module) -> None:
    """Replace navigation-heavy presentation only when the portfolio-only mode is active."""

    if not portfolio_only_enabled():
        return

    def render_surfaces(*, dependencies=None, principal=None) -> None:
        del principal
        resolved = dependencies or app_impl_module.default_dependencies()
        st.session_state["dark_mode"] = True
        apply_global_style(dark_mode=True)
        _render_portfolio_command_center(resolved)

    def render_identity_controls(principal: Any) -> None:
        _minimal_identity_controls(secure_app_module, principal)

    def render_deployment_controls(_principal: Any, deployment: Any) -> None:
        with st.sidebar:
            release = str(getattr(deployment, "release", "") or "unknown")
            st.caption(f"Build `{release[:12]}`")
            st.caption("Paper only")

    app_impl_module.render_surfaces = render_surfaces
    secure_app_module.render_surfaces = render_surfaces
    secure_app_module._render_identity_controls = render_identity_controls
    secure_app_module._render_deployment_controls = render_deployment_controls


__all__ = ["install", "portfolio_only_enabled"]
