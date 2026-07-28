"""Four distinct Streamlit surfaces backed by the canonical CIO journal."""

from __future__ import annotations

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
    activity_rail,
    allocation_bar,
    apply_global_style,
    bullet_lines,
    callout_card,
    display_frame,
    format_currency,
    format_datetime,
    format_percent,
    metric_grid,
    page_header,
    render_app_header,
    render_navigation,
    render_sidebar,
    signal_panel,
    surface_story,
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
    except (RuntimeError, OSError):
        return None


def _history(event_type: str, *, limit: int = 50) -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().history(event_type, limit=limit)
    except (RuntimeError, OSError):
        return ()


def _latest_theses() -> tuple[dict[str, Any], ...]:
    try:
        return cio_journal().latest_per_aggregate(
            "thesis_snapshot",
            limit=200,
        )
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
    surface_story(
        "Today",
        (
            ("Observe", "Continuous market intelligence remains in the background."),
            ("Resolve", "Only material portfolio implications advance to the CIO."),
            ("Act", "Capital changes only after construction and implementation validate."),
        ),
    )
    page_header(
        "Decision pulse",
        "The system stays quiet until evidence earns a portfolio-level conclusion.",
        "01",
    )

    if briefing is None:
        signal_panel(
            "CIO pulse // standby",
            "No capital change authorized",
            (
                "No governed CIO briefing is available. The portfolio remains "
                "unchanged until opportunity comparison, independent review, CIO "
                "synthesis, and construction complete successfully."
            ),
            variant="today",
        )
        metric_grid(
            (
                ("Decision state", "Standby", "Fail-closed"),
                ("Implementation", "No change", "No order authority"),
                ("Active theses", len(theses), "Living ownership cases"),
                ("Market watch", "Continuous", "All governed markets"),
            ),
            variant="today",
        )
    else:
        status = str(briefing.get("status", "unavailable")).replace(
            "_",
            " ",
        ).title()
        confidence = briefing.get("confidence")
        construction = briefing.get("construction_status")
        signal_panel(
            f"CIO pulse // {status}",
            briefing.get("portfolio_decision") or "Maintain current posture",
            briefing.get("why_it_matters")
            or "No additional portfolio-level conclusion is available.",
            variant="today",
        )
        metric_grid(
            (
                ("CIO state", status, "Governed conclusion"),
                (
                    "Confidence",
                    "—" if confidence is None else f"{float(confidence):.0%}",
                    "Evidence-weighted",
                ),
                (
                    "Implementation",
                    "No change"
                    if construction is None
                    else str(construction).replace("_", " ").title(),
                    "Paper layer",
                ),
                ("Active theses", len(theses), "Monitored continuously"),
            ),
            variant="today",
        )

        left, right = st.columns((1.12, 0.88), gap="large")
        with left:
            text_card("Signal change", briefing.get("what_changed"))
            st.markdown(
                "<div style='height:.75rem'></div>",
                unsafe_allow_html=True,
            )
            text_card("Portfolio relevance", briefing.get("why_it_matters"))
        with right:
            text_card(
                "Opportunity / risk vector",
                briefing.get("opportunity_or_risk"),
            )
            st.markdown(
                "<div style='height:.75rem'></div>",
                unsafe_allow_html=True,
            )
            callout_card(
                "Capital action",
                briefing.get("portfolio_decision"),
                (
                    "The conclusion remains non-executing until implementation "
                    "is separately validated."
                ),
            )

        developments = briefing.get("material_developments", [])
        if developments:
            with st.expander("Material developments"):
                st.markdown(bullet_lines(developments))
        with st.expander("Evidence that would change the conclusion"):
            st.markdown(
                bullet_lines(
                    briefing.get("evidence_that_changes_conclusion", []),
                )
            )
        journal = briefing.get("journal", {})
        with st.expander("Decision audit reference"):
            st.write(
                "Decision: "
                f"{briefing.get('decision_identifier') or 'No action decision'}"
            )
            st.write(
                "Candidate: "
                f"{briefing.get('candidate_identifier') or 'No qualified candidate'}"
            )
            st.write(f"Cycle: {briefing.get('cycle_identifier')}")
            st.write(f"Journal sequence: {journal.get('sequence')}")
            st.code(str(journal.get("content_hash", "unavailable")))

    page_header(
        "Capital position",
        "The sole active portfolio at the current decision point.",
        "02",
    )
    totals = get_portfolio_totals()
    metric_grid(
        (
            ("Portfolio value", format_currency(totals["nav"]), "Canonical NAV"),
            (
                "Available cash",
                format_currency(totals["cash"]),
                "Optionality reserve",
            ),
            (
                "Paper return",
                format_percent(totals["total_return"]),
                "Since inception",
            ),
            ("Mandate", "Compounding", "One portfolio"),
        ),
        variant="today",
    )
    allocation_bar(cash=totals["cash"], nav=totals["nav"])


def _render_environment() -> None:
    surface_story(
        "Environment",
        (
            ("Growth", "Economic momentum and labor conditions."),
            ("Inflation", "Price pressure and policy sensitivity."),
            ("Liquidity", "Rates, funding and cross-asset transmission."),
        ),
    )
    page_header(
        "Regime field",
        (
            "Certified evidence shapes opportunity analysis without becoming a "
            "recommendation by itself."
        ),
        "01",
    )
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    if isinstance(environment, dict):
        signal_panel(
            "Market field // active",
            environment.get("headline", "Current environment"),
            environment.get(
                "summary",
                "No environment summary is available.",
            ),
            variant="environment",
        )
        confidence = environment.get("confidence")
        metric_grid(
            (
                (
                    "Regime",
                    environment.get("regime", "Unavailable"),
                    "Current classification",
                ),
                (
                    "Evidence confidence",
                    "—" if confidence is None else f"{float(confidence):.0%}",
                    "Certified inputs",
                ),
                (
                    "Data status",
                    environment.get("data_status", "Unavailable"),
                    "Freshness and coverage",
                ),
                (
                    "Portfolio effect",
                    "Observed",
                    "Not independently actionable",
                ),
            ),
            variant="environment",
        )
        if environment.get("portfolio_impact"):
            callout_card(
                "Portfolio transmission",
                environment["portfolio_impact"],
            )
        if environment.get("review_conditions"):
            with st.expander("Environment review conditions"):
                st.markdown(bullet_lines(environment["review_conditions"]))
    else:
        signal_panel(
            "Market field // limited",
            "Canonical environment brief unavailable",
            (
                "Diagnostic readings remain visible, but no portfolio conclusion "
                "is inferred from incomplete environment evidence."
            ),
            variant="environment",
        )

    page_header(
        "Economic telemetry",
        "Live macro readings feeding the broader opportunity engine.",
        "02",
    )
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    if readings is None:
        st.warning("Live economic readings are unavailable.")
        st.caption(str(dashboard_data.status))
        return
    metric_grid(
        (
            (
                "Unemployment",
                f"{readings.unemployment_rate:.1f}%",
                "Labor market",
            ),
            (
                "Estimated inflation",
                f"{readings.inflation_rate:.2f}%",
                "Price pressure",
            ),
            (
                "Federal funds",
                f"{readings.federal_funds_rate:.2f}%",
                "Policy rate",
            ),
            ("Use", "Evidence only", "Compared across candidates"),
        ),
        variant="environment",
    )


def _render_portfolio() -> None:
    surface_story(
        "Portfolio",
        (
            ("Size", "Translate conviction into a feasible portfolio weight."),
            ("Fund", "Identify the best source of capital and opportunity cost."),
            ("Validate", "Confirm concentration, cost and paper implementation."),
        ),
    )
    page_header(
        "Construction blueprint",
        (
            "Feasible sizing, funding, and implementation for the single "
            "canonical portfolio."
        ),
        "01",
    )
    construction = _latest("portfolio_construction")
    if construction is None:
        signal_panel(
            "Construction map // idle",
            "No implementation change queued",
            (
                "No canonical construction result is available. Existing capital "
                "remains in its current state."
            ),
            variant="portfolio",
        )
    else:
        status = str(construction.get("status", "unavailable")).replace(
            "_",
            " ",
        ).title()
        signal_panel(
            f"Construction map // {status}",
            "Implementation geometry resolved",
            (
                "Sizing and funding are visible for review, but construction "
                "cannot alter the CIO decision or submit broker orders."
            ),
            variant="portfolio",
        )
        metric_grid(
            (
                ("Construction state", status, "Paper implementation"),
                (
                    "Turnover",
                    format_percent(construction.get("turnover", 0.0)),
                    "Portfolio movement",
                ),
                (
                    "Estimated cost",
                    format_percent(
                        construction.get("estimated_cost_return", 0.0),
                    ),
                    "Return drag",
                ),
                (
                    "Expected improvement",
                    format_percent(
                        construction.get("expected_return_improvement", 0.0),
                    ),
                    "Net opportunity",
                ),
            ),
            variant="portfolio",
        )
        if construction.get("trades"):
            with st.expander("Proposed paper implementation"):
                display_frame(pd.DataFrame(construction["trades"]))
        for block in construction.get("blocks", []):
            st.warning(block)

    page_header(
        "Canonical portfolio",
        PORTFOLIO_OBJECTIVE,
        "02",
    )
    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if mandate is None:
        st.warning("The canonical paper portfolio is unavailable.")
        return
    metric_grid(
        (
            ("NAV", format_currency(mandate["nav"]), "Canonical value"),
            ("Cash", format_currency(mandate["cash"]), "Available capital"),
            (
                "Paper return",
                format_percent(mandate["total_return"]),
                "Since inception",
            ),
            ("Holdings", len(mandate["holdings"]), "Active positions"),
        ),
        variant="portfolio",
    )
    allocation_bar(cash=mandate["cash"], nav=mandate["nav"])

    holdings_tab, trades_tab, history_tab = st.tabs(
        ["Positions", "Implementation", "Capital path"]
    )
    with holdings_tab:
        holdings = mandate["holdings"]
        if not holdings:
            st.info("No current holdings are recorded.")
        else:
            frame = pd.DataFrame(holdings)
            columns = [
                column
                for column in (
                    "symbol",
                    "asset_class",
                    "quantity",
                    "current_price",
                    "market_value",
                    "unrealized_gain",
                    "price_currency",
                    "updated_at",
                )
                if column in frame.columns
            ]
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
            columns = [
                column
                for column in (
                    "created_at",
                    "side",
                    "symbol",
                    "asset_class",
                    "quantity",
                    "price",
                    "gross_amount_base",
                    "rationale",
                )
                if column in frame.columns
            ]
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
                st.line_chart(
                    chart.sort_values("created_at").set_index("created_at")["nav"]
                )
            columns = [
                column
                for column in (
                    "created_at",
                    "cash_base_total",
                    "holdings_value",
                    "nav",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


def _render_history() -> None:
    surface_story(
        "History",
        (
            ("Record", "Preserve the original evidence and governed conclusion."),
            ("Observe", "Wait for the complete decision horizon and real outcomes."),
            ("Evaluate", "Separate process quality from outcome quality."),
            ("Learn", "Submit evidence for governance review without self-modifying."),
        ),
    )
    page_header(
        "Decision trail",
        (
            "Every conclusion, evaluation, thesis, and paper action remains "
            "visible as governed institutional memory."
        ),
        "01",
    )
    briefings = _history("daily_cio_briefing")
    evaluations = _history("decision_evaluation")
    theses = _latest_theses()
    trades = get_trade_history(limit=250)
    metric_grid(
        (
            ("CIO briefings", len(briefings), "Recorded decisions"),
            ("Evaluations", len(evaluations), "Outcome reviews"),
            ("Living theses", len(theses), "Current ownership cases"),
            ("Paper trades", len(trades), "Execution journal"),
        ),
        variant="history",
    )

    latest_briefing = briefings[0] if briefings else {}
    latest_evaluation = evaluations[0] if evaluations else {}
    latest_thesis = theses[0] if theses else {}
    latest_trade = trades[0] if trades else {}
    activity_rail(
        (
            (
                "Decision",
                latest_briefing.get("portfolio_decision") or "Awaiting first briefing",
                format_datetime(latest_briefing.get("as_of")),
            ),
            (
                "Outcome",
                latest_evaluation.get("outcome") or "Awaiting matured evaluation",
                latest_evaluation.get("process_verdict") or "No process verdict",
            ),
            (
                "Thesis",
                latest_thesis.get("asset") or "No thesis recorded",
                latest_thesis.get("state") or "No lifecycle state",
            ),
            (
                "Execution",
                (
                    f"{latest_trade.get('side', '')} "
                    f"{latest_trade.get('symbol', '')}"
                ).strip()
                or "No paper trade recorded",
                format_datetime(latest_trade.get("created_at")),
            ),
        )
    )

    brief_tab, eval_tab, thesis_tab, trade_tab = st.tabs(
        ["Decisions", "Outcomes", "Theses", "Execution"]
    )
    with brief_tab:
        if not briefings:
            st.info("No canonical CIO briefings have been recorded.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "As of": format_datetime(item.get("as_of")),
                        "Status": item.get("status"),
                        "Decision": item.get("portfolio_decision"),
                        "Confidence": item.get("confidence"),
                        "Decision ID": item.get("decision_identifier"),
                    }
                    for item in briefings
                )
            )
    with eval_tab:
        if not evaluations:
            st.info(
                "Evaluations appear after the decision horizon has observable outcomes."
            )
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "Decision": item.get("decision_identifier"),
                        "Process": item.get("process_verdict"),
                        "Outcome": item.get("outcome"),
                        "Value added": item.get(
                            "value_added_vs_best_alternative"
                        ),
                        "Brier score": item.get("brier_score"),
                    }
                    for item in evaluations
                )
            )
    with thesis_tab:
        if not theses:
            st.info("No active or historical ownership theses are recorded.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "Thesis": item.get("identifier"),
                        "Asset": item.get("asset"),
                        "State": item.get("state"),
                        "Confidence": item.get("current_confidence"),
                        "Next review": format_datetime(item.get("next_review_at")),
                    }
                    for item in theses
                )
            )
    with trade_tab:
        if not trades:
            st.info("No paper trades have been recorded.")
        else:
            frame = pd.DataFrame(trades)
            columns = [
                column
                for column in (
                    "created_at",
                    "side",
                    "symbol",
                    "asset_class",
                    "quantity",
                    "price",
                    "gross_amount_base",
                    "rationale",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)


st.session_state.setdefault("dark_mode", True)
apply_global_style(dark_mode=bool(st.session_state["dark_mode"]))
render_sidebar()
page, _ = render_navigation(PRIMARY_SURFACES)
render_app_header(page)
if page == "Today":
    _render_today()
elif page == "Environment":
    _render_environment()
elif page == "Portfolio":
    _render_portfolio()
else:
    _render_history()
