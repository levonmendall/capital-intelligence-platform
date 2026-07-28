"""Four-surface Streamlit experience backed by the canonical CIO journal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from api.config import ApiSettings
from api.repositories import DailySnapshotRepository, JournalRepository
from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
from portfolio.constants import CANONICAL_PORTFOLIO_CODE, PORTFOLIO_OBJECTIVE
from premium_ui import (
    allocation_bar,
    apply_global_style,
    bullet_lines,
    callout_card,
    display_frame,
    format_currency,
    format_datetime,
    format_percent,
    page_header,
    render_app_header,
    render_navigation,
    render_sidebar,
    text_card,
)
from providers.economic_snapshot import load_dashboard_data


PRIMARY_SURFACES = ["Today", "Environment", "Portfolio", "History"]


st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


@st.cache_resource
def runtime_settings() -> ApiSettings:
    return ApiSettings.from_env()


@st.cache_resource
def cio_journal() -> JournalRepository:
    settings = runtime_settings()
    return JournalRepository(settings.journal_database, required=settings.require_journal)


@st.cache_resource
def diagnostic_snapshots() -> DailySnapshotRepository:
    return DailySnapshotRepository(runtime_settings().snapshot_database)


def _latest(event_type: str) -> dict[str, Any] | None:
    try:
        return cio_journal().latest_payload(event_type)
    except (RuntimeError, OSError):
        return None


def _history(event_type: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().history(event_type, limit=limit)
    except (RuntimeError, OSError):
        return ()


def _latest_theses() -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().latest_per_aggregate("thesis_snapshot", limit=200)
    except (RuntimeError, OSError):
        return ()


def _diagnostic_environment() -> dict[str, Any] | None:
    try:
        return diagnostic_snapshots().latest_payload()
    except (RuntimeError, OSError):
        return None


def _render_today() -> None:
    briefing = _latest("daily_cio_briefing")
    theses = _latest_theses()
    page_header(
        "Today’s Capital Intelligence",
        "What changed, why it matters, and whether the portfolio should respond.",
    )

    if briefing is None:
        st.warning(
            "No governed CIO briefing is available. No portfolio action is permitted until opportunity comparison, independent review, CIO synthesis, and portfolio construction complete successfully."
        )
        st.info(
            "The system remains comfortable holding cash or current positions when no superior evidence-supported use of capital is available."
        )
    else:
        status = str(briefing.get("status", "unavailable")).replace("_", " ").title()
        confidence = briefing.get("confidence")
        construction = briefing.get("construction_status")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("CIO status", status)
        c2.metric("Confidence", "—" if confidence is None else f"{float(confidence):.0%}")
        c3.metric("Implementation", "No change" if construction is None else str(construction).replace("_", " ").title())
        c4.metric("Active theses", len(theses))

        left, right = st.columns((1.15, 0.85), gap="large")
        with left:
            text_card("What changed?", briefing.get("what_changed"))
            st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
            text_card("Why does it matter?", briefing.get("why_it_matters"))
        with right:
            text_card("Opportunity or risk", briefing.get("opportunity_or_risk"))
            st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
            callout_card(
                "Should the portfolio change?",
                briefing.get("portfolio_decision"),
                "The CIO conclusion remains non-executing until implementation is validated.",
            )

        developments = briefing.get("material_developments", [])
        if developments:
            with st.expander("Material developments"):
                st.markdown(bullet_lines(developments))
        with st.expander("Evidence that would change the conclusion"):
            st.markdown(bullet_lines(briefing.get("evidence_that_changes_conclusion", [])))
        journal = briefing.get("journal", {})
        with st.expander("Decision audit reference"):
            st.write(f"Decision: {briefing.get('decision_identifier') or 'No action decision'}")
            st.write(f"Candidate: {briefing.get('candidate_identifier') or 'No qualified candidate'}")
            st.write(f"Cycle: {briefing.get('cycle_identifier')}")
            st.write(f"Journal sequence: {journal.get('sequence')}")
            st.code(str(journal.get("content_hash", "unavailable")))

    st.divider()
    page_header("Portfolio snapshot", "The sole active portfolio at the current decision point.")
    totals = get_portfolio_totals()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio value", format_currency(totals["nav"]))
    c2.metric("Available cash", format_currency(totals["cash"]))
    c3.metric("Paper return", format_percent(totals["total_return"]))
    c4.metric("Mandate", "Compounding")
    st.caption(
        "One paper portfolio pursues the strongest evidence-supported use of capital across all governed markets."
    )


def _render_environment() -> None:
    page_header(
        "Market environment",
        "Certified evidence that informs opportunity analysis without issuing a recommendation by itself.",
    )
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    if isinstance(environment, dict):
        callout_card(
            str(environment.get("headline", "Current environment")),
            environment.get("summary", "No environment summary is available."),
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Regime", environment.get("regime", "Unavailable"))
        confidence = environment.get("confidence")
        c2.metric("Evidence confidence", "—" if confidence is None else f"{float(confidence):.0%}")
        c3.metric("Data status", environment.get("data_status", "Unavailable"))
        if environment.get("portfolio_impact"):
            callout_card("Portfolio relevance", environment["portfolio_impact"])
        if environment.get("review_conditions"):
            with st.expander("Environment review conditions"):
                st.markdown(bullet_lines(environment["review_conditions"]))
    else:
        st.info("No canonical environment brief is stored. Diagnostic readings are shown below without a portfolio conclusion.")

    st.divider()
    page_header("Economic evidence", "Live macro readings used as inputs to the broader opportunity engine.")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    if readings is None:
        st.warning("Live economic readings are unavailable.")
        st.caption(str(dashboard_data.status))
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Unemployment rate", f"{readings.unemployment_rate:.1f}%")
    c2.metric("Estimated inflation", f"{readings.inflation_rate:.2f}%")
    c3.metric("Federal funds rate", f"{readings.federal_funds_rate:.2f}%")
    st.caption("These readings are evidence inputs only; every candidate must still be compared with cash, holdings, and qualified alternatives.")


def _render_portfolio() -> None:
    page_header("Portfolio", "Holdings, construction, and paper activity for the single canonical portfolio.")
    construction = _latest("portfolio_construction")
    if construction is None:
        st.info("No canonical portfolio-construction result is available.")
    else:
        status = str(construction.get("status", "unavailable")).replace("_", " ").title()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Construction status", status)
        c2.metric("Turnover", format_percent(construction.get("turnover", 0.0)))
        c3.metric("Estimated cost", format_percent(construction.get("estimated_cost_return", 0.0)))
        c4.metric("Expected improvement", format_percent(construction.get("expected_return_improvement", 0.0)))
        if construction.get("trades"):
            with st.expander("Proposed paper implementation"):
                display_frame(pd.DataFrame(construction["trades"]))
        for block in construction.get("blocks", []):
            st.warning(block)
        st.caption("Construction determines feasible sizing and funding. It cannot alter the CIO action or submit broker orders.")

    st.markdown("### Capital Intelligence Portfolio")
    st.caption(PORTFOLIO_OBJECTIVE)
    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if mandate is None:
        st.warning("The canonical paper portfolio is unavailable.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NAV", format_currency(mandate["nav"]))
    c2.metric("Cash", format_currency(mandate["cash"]))
    c3.metric("Paper return", format_percent(mandate["total_return"]))
    c4.metric("Holdings", len(mandate["holdings"]))
    allocation_bar(cash=mandate["cash"], nav=mandate["nav"])

    holdings_tab, trades_tab, history_tab = st.tabs(["Holdings", "Paper trades", "Value history"])
    with holdings_tab:
        holdings = mandate["holdings"]
        if not holdings:
            st.info("No current holdings are recorded.")
        else:
            frame = pd.DataFrame(holdings)
            columns = [c for c in ["symbol", "asset_class", "quantity", "current_price", "market_value", "unrealized_gain", "price_currency", "updated_at"] if c in frame.columns]
            frame = frame[columns] if columns else frame
            if "updated_at" in frame.columns:
                frame["updated_at"] = frame["updated_at"].map(format_datetime)
            display_frame(frame)
    with trades_tab:
        trades = mandate["trades"]
        if not trades:
            st.info("No paper trades have been recorded.")
        else:
            frame = pd.DataFrame(trades)
            columns = [c for c in ["created_at", "side", "symbol", "asset_class", "quantity", "price", "gross_amount_base", "rationale"] if c in frame.columns]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)
    with history_tab:
        snapshots = mandate["snapshots"]
        if not snapshots:
            st.info("No portfolio snapshots are available.")
        else:
            frame = pd.DataFrame(snapshots)
            if "created_at" in frame.columns and "nav" in frame.columns:
                chart = frame.copy()
                chart["created_at"] = pd.to_datetime(chart["created_at"])
                st.line_chart(chart.sort_values("created_at").set_index("created_at")["nav"])
            columns = [c for c in ["created_at", "cash_base_total", "holdings_value", "nav"] if c in frame.columns]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


def _render_history() -> None:
    page_header("Decision history", "CIO briefings, evaluations, theses, and paper-trade records.")
    briefings = _history("daily_cio_briefing")
    evaluations = _history("decision_evaluation")
    theses = _latest_theses()
    trades = get_trade_history(limit=250)
    brief_tab, eval_tab, thesis_tab, trade_tab = st.tabs(["CIO briefings", "Evaluations", "Living theses", "Paper-trade journal"])
    with brief_tab:
        if not briefings:
            st.info("No canonical CIO briefings have been recorded.")
        else:
            display_frame(pd.DataFrame({"As of": format_datetime(i.get("as_of")), "Status": i.get("status"), "Decision": i.get("portfolio_decision"), "Confidence": i.get("confidence"), "Decision ID": i.get("decision_identifier")} for i in briefings))
    with eval_tab:
        if not evaluations:
            st.info("Evaluations appear after the decision horizon has observable outcomes.")
        else:
            display_frame(pd.DataFrame({"Decision": i.get("decision_identifier"), "Process": i.get("process_verdict"), "Outcome": i.get("outcome"), "Value added": i.get("value_added_vs_best_alternative"), "Brier score": i.get("brier_score")} for i in evaluations))
    with thesis_tab:
        if not theses:
            st.info("No active or historical ownership theses are recorded.")
        else:
            display_frame(pd.DataFrame({"Thesis": i.get("identifier"), "Asset": i.get("asset"), "State": i.get("state"), "Confidence": i.get("current_confidence"), "Next review": format_datetime(i.get("next_review_at"))} for i in theses))
    with trade_tab:
        if not trades:
            st.info("No paper trades have been recorded.")
        else:
            frame = pd.DataFrame(trades)
            columns = [c for c in ["created_at", "side", "symbol", "asset_class", "quantity", "price", "gross_amount_base", "rationale"] if c in frame.columns]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


dark_mode = bool(st.session_state.get("dark_mode", False))
apply_global_style(dark_mode=dark_mode)
render_sidebar()
page, dark_mode = render_navigation(PRIMARY_SURFACES)
render_app_header(page)
if page == "Today":
    _render_today()
elif page == "Environment":
    _render_environment()
elif page == "Portfolio":
    _render_portfolio()
else:
    _render_history()
