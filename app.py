"""Four-surface Streamlit experience backed by the canonical CIO journal."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from api.config import ApiSettings
from api.repositories import (
    DailySnapshotRepository,
    JournalRepository,
    RepositoryUnavailableError,
)
from core.portfolio import (
    get_mandate_details,
    get_portfolio_totals,
    get_trade_history,
)
from portfolio.constants import (
    CANONICAL_PORTFOLIO_CODE,
    PORTFOLIO_OBJECTIVE,
)
from providers.economic_snapshot import load_dashboard_data


st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


def format_currency(value: float) -> str:
    return f"${float(value):,.2f}"


def format_percent(value: float) -> str:
    return f"{float(value):+.2%}"


@st.cache_resource
def runtime_settings() -> ApiSettings:
    return ApiSettings.from_env()


@st.cache_resource
def cio_journal() -> JournalRepository:
    settings = runtime_settings()
    return JournalRepository(
        settings.journal_database,
        required=settings.require_journal,
    )


@st.cache_resource
def diagnostic_snapshots() -> DailySnapshotRepository:
    return DailySnapshotRepository(runtime_settings().snapshot_database)


def _latest(event_type: str) -> dict[str, Any] | None:
    try:
        return cio_journal().latest_payload(event_type)
    except RepositoryUnavailableError:
        return None


def _history(event_type: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().history(event_type, limit=limit)
    except RepositoryUnavailableError:
        return ()


def _latest_theses() -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().latest_per_aggregate("thesis_snapshot", limit=200)
    except RepositoryUnavailableError:
        return ()


def _diagnostic_environment() -> dict[str, Any] | None:
    try:
        return diagnostic_snapshots().latest_payload()
    except RepositoryUnavailableError:
        return None


def _render_today() -> None:
    st.subheader("Today's Capital Intelligence")
    briefing = _latest("daily_cio_briefing")
    theses = _latest_theses()

    if briefing is None:
        st.warning(
            "No governed CIO briefing is available. No portfolio action is "
            "permitted until opportunity comparison, independent review, CIO "
            "synthesis, and portfolio construction complete successfully."
        )
        st.info(
            "The system remains comfortable holding cash or current positions "
            "when no superior evidence-supported use of capital is available."
        )
    else:
        status = str(briefing.get("status", "unavailable")).replace("_", " ").title()
        confidence = briefing.get("confidence")
        construction = briefing.get("construction_status")
        metric1, metric2, metric3, metric4 = st.columns(4)
        metric1.metric("CIO status", status)
        metric2.metric(
            "Confidence",
            "—" if confidence is None else f"{float(confidence):.0%}",
        )
        metric3.metric(
            "Implementation",
            "No change" if construction is None else str(construction).replace("_", " ").title(),
        )
        metric4.metric("Active theses", len(theses))

        st.markdown("### What changed?")
        st.write(briefing["what_changed"])

        st.markdown("### Why does it matter?")
        st.write(briefing["why_it_matters"])

        st.markdown("### Opportunity or risk")
        st.write(briefing["opportunity_or_risk"])

        st.markdown("### Should the portfolio change?")
        st.success(briefing["portfolio_decision"])

        developments = briefing.get("material_developments", [])
        if developments:
            st.markdown("### Material developments")
            for item in developments:
                st.write(f"• {item}")

        conditions = briefing.get("evidence_that_changes_conclusion", [])
        with st.expander("Evidence that would change the conclusion"):
            for item in conditions:
                st.write(f"• {item}")

        journal = briefing.get("journal", {})
        with st.expander("Decision audit reference"):
            st.write(f"Decision: {briefing.get('decision_identifier') or 'No action decision'}")
            st.write(f"Candidate: {briefing.get('candidate_identifier') or 'No qualified candidate'}")
            st.write(f"Cycle: {briefing.get('cycle_identifier')}")
            st.write(f"Journal sequence: {journal.get('sequence')}")
            st.code(str(journal.get("content_hash", "unavailable")))

    st.divider()
    totals = get_portfolio_totals()
    overview1, overview2, overview3, overview4 = st.columns(4)
    overview1.metric("Portfolio value", format_currency(totals["nav"]))
    overview2.metric("Available cash", format_currency(totals["cash"]))
    overview3.metric("Paper return", format_percent(totals["total_return"]))
    overview4.metric("Mandate", "Compounding")
    st.caption(
        "One paper portfolio pursues the strongest evidence-supported use of "
        "capital across all governed markets. CIO decisions remain non-executing "
        "until a separately approved implementation layer is validated."
    )


def _render_environment() -> None:
    st.subheader("Market environment")
    st.caption(
        "Environment evidence informs opportunity analysis. It does not issue "
        "recommendations or override the CIO decision process."
    )
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    if isinstance(environment, dict):
        st.markdown(f"### {environment.get('headline', 'Current environment')}")
        st.write(environment.get("summary", "No environment summary is available."))
        column1, column2, column3 = st.columns(3)
        column1.metric("Regime", environment.get("regime", "Unavailable"))
        confidence = environment.get("confidence")
        column2.metric(
            "Evidence confidence",
            "—" if confidence is None else f"{float(confidence):.0%}",
        )
        column3.metric("Data", environment.get("data_status", "Unavailable"))
        impact = environment.get("portfolio_impact")
        if impact:
            st.write(f"**Portfolio relevance:** {impact}")
        conditions = environment.get("review_conditions", [])
        if conditions:
            with st.expander("Environment review conditions"):
                for condition in conditions:
                    st.write(f"• {condition}")
    else:
        st.info(
            "No canonical environment brief is stored. Diagnostic readings are "
            "shown below without a portfolio conclusion."
        )

    st.divider()
    st.subheader("Economic evidence")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    if readings is None:
        st.warning("Live economic readings are unavailable.")
        st.caption(str(dashboard_data.status))
        return
    columns = st.columns(3)
    columns[0].metric("Unemployment rate", f"{readings.unemployment_rate:.1f}%")
    columns[1].metric("Estimated inflation", f"{readings.inflation_rate:.2f}%")
    columns[2].metric("Federal funds rate", f"{readings.federal_funds_rate:.2f}%")
    st.caption(
        "These readings are evidence inputs only. The opportunity engine must "
        "compare every candidate with cash, current holdings, and other qualified alternatives."
    )


def _render_portfolio() -> None:
    st.subheader("Portfolio")
    construction = _latest("portfolio_construction")
    if construction is None:
        st.info("No canonical portfolio-construction result is available.")
    else:
        status = str(construction.get("status", "unavailable")).replace("_", " ").title()
        columns = st.columns(4)
        columns[0].metric("Construction status", status)
        columns[1].metric("Turnover", format_percent(construction.get("turnover", 0.0)))
        columns[2].metric(
            "Estimated cost",
            format_percent(construction.get("estimated_cost_return", 0.0)),
        )
        columns[3].metric(
            "Expected improvement",
            format_percent(construction.get("expected_return_improvement", 0.0)),
        )
        trades = construction.get("trades", [])
        if trades:
            st.markdown("### Proposed paper implementation")
            st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)
        blocks = construction.get("blocks", [])
        for block in blocks:
            st.warning(block)
        st.caption(
            "Construction determines feasible sizing and funding. It cannot alter "
            "the CIO action and does not submit broker orders."
        )

    st.markdown("### Capital Intelligence Portfolio")
    st.caption(PORTFOLIO_OBJECTIVE)
    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if mandate is None:
        st.warning("The canonical paper portfolio is unavailable.")
        return

    summary1, summary2, summary3, summary4 = st.columns(4)
    summary1.metric("NAV", format_currency(mandate["nav"]))
    summary2.metric("Cash", format_currency(mandate["cash"]))
    summary3.metric("Paper return", format_percent(mandate["total_return"]))
    summary4.metric("Holdings", len(mandate["holdings"]))

    if mandate["holdings"]:
        st.markdown("### Current holdings")
        st.dataframe(pd.DataFrame(mandate["holdings"]), use_container_width=True, hide_index=True)
    if mandate["trades"]:
        st.markdown("### Recorded paper trades")
        st.dataframe(pd.DataFrame(mandate["trades"]), use_container_width=True, hide_index=True)
    if mandate["snapshots"]:
        frame = pd.DataFrame(mandate["snapshots"])
        if "created_at" in frame and "nav" in frame:
            frame["created_at"] = pd.to_datetime(frame["created_at"])
            st.markdown("### Portfolio value history")
            st.line_chart(frame.sort_values("created_at").set_index("created_at")["nav"])


def _render_history() -> None:
    st.subheader("Decision history")
    briefings = _history("daily_cio_briefing")
    evaluations = _history("decision_evaluation")
    theses = _latest_theses()

    st.markdown("### CIO briefings")
    if not briefings:
        st.info("No canonical CIO briefings have been recorded.")
    else:
        frame = pd.DataFrame(
            {
                "As of": item.get("as_of"),
                "Status": item.get("status"),
                "Decision": item.get("portfolio_decision"),
                "Confidence": item.get("confidence"),
                "Decision ID": item.get("decision_identifier"),
            }
            for item in briefings
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)

    st.markdown("### Point-in-time evaluations")
    if not evaluations:
        st.info("Evaluations appear after the decision horizon has observable outcomes.")
    else:
        frame = pd.DataFrame(
            {
                "Decision": item.get("decision_identifier"),
                "Process": item.get("process_verdict"),
                "Outcome": item.get("outcome"),
                "Value added": item.get("value_added_vs_best_alternative"),
                "Brier score": item.get("brier_score"),
            }
            for item in evaluations
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)

    st.markdown("### Living theses")
    if not theses:
        st.info("No active or historical ownership theses are recorded.")
    else:
        frame = pd.DataFrame(
            {
                "Thesis": item.get("identifier"),
                "Asset": item.get("asset"),
                "State": item.get("state"),
                "Confidence": item.get("current_confidence"),
                "Next review": item.get("next_review_at"),
            }
            for item in theses
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)

    st.markdown("### Paper-trade journal")
    trades = get_trade_history(limit=250)
    if trades:
        st.dataframe(pd.DataFrame(trades), use_container_width=True, hide_index=True)
    else:
        st.info("No paper trades have been recorded.")


st.title("Capital Intelligence Platform")
st.caption(
    "One portfolio · All-market analysis · Evidence-supported allocation · Point-in-time evaluation"
)

page = st.sidebar.radio("Navigation", ["Today", "Environment", "Portfolio", "History"])
if page == "Today":
    _render_today()
elif page == "Environment":
    _render_environment()
elif page == "Portfolio":
    _render_portfolio()
else:
    _render_history()
