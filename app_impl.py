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
    status_list,
    surface_story,
    text_card,
)
from providers.economic_snapshot import load_dashboard_data
from live_operating_console import load_live_market_console


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


def _briefing_identifier(briefing: dict[str, Any] | None) -> str:
    if not isinstance(briefing, dict):
        return "Unavailable"
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = str(briefing.get(field_name, "")).strip()
        if value:
            return value
    return "Unavailable"


def _plain_text(value: object, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def _joined_items(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (list, tuple)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return " • ".join(cleaned) if cleaned else fallback
    return fallback


def _status_title(value: object, fallback: str = "Unavailable") -> str:
    text = "" if value is None else str(value).strip()
    return text.replace("_", " ").title() if text else fallback


def _market_session(snapshot: dict[str, object]) -> str:
    state = snapshot.get("market_open")
    return "Open" if state is True else "Closed" if state is False else "Unavailable"


def _coverage_label(snapshot: dict[str, object]) -> str:
    return (
        f"{int(snapshot.get('quote_count', 0) or 0)}/"
        f"{int(snapshot.get('expected_quote_count', 0) or 0)}"
    )


def _deployment_label(*, cash: float, nav: float) -> str:
    if nav <= 0:
        return "Unavailable"
    invested = max(float(nav) - float(cash), 0.0)
    return f"{invested / float(nav):.0%} deployed"


def _render_today() -> None:
    briefing = _latest("daily_cio_briefing")
    theses = _latest_theses()
    live_market = load_live_market_console()
    totals = get_portfolio_totals()
    _today_construction = _latest("portfolio_construction")

    page_header(
        "Today's CIO briefing",
        (
            "The current portfolio conclusion, the evidence that matters, what changed, "
            "and the action the CIO recommends now."
        ),
        "01",
    )

    if briefing is None:
        signal_panel(
            "Daily CIO briefing // unavailable",
            "No governed CIO conclusion is available yet",
            (
                "The portfolio remains unchanged until opportunity comparison, independent "
                "review, CIO synthesis, and construction complete successfully."
            ),
            variant="today",
        )
        metric_grid(
            (
                ("U.S. session", _market_session(live_market), "Live provider clock"),
                ("Live coverage", _coverage_label(live_market), "Governed instruments"),
                ("Portfolio posture", _deployment_label(cash=totals["cash"], nav=totals["nav"]), "Current capital"),
                ("Decision state", "Standby", "Fail-closed"),
            ),
            variant="today",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _plain_text(
                    live_market.get("detail"),
                    "The CIO has not published a completed portfolio conclusion yet.",
                ),
            )
        with right:
            text_card(
                "What could change the state",
                (
                    "A completed evidence comparison, independent review, CIO synthesis, "
                    "and feasible construction are required before capital can change."
                ),
            )
    else:
        status = _status_title(briefing.get("status"))
        confidence = briefing.get("confidence")
        construction = briefing.get("construction_status")
        decision = _plain_text(
            briefing.get("portfolio_decision"),
            "Maintain the current portfolio posture.",
        )
        why_it_matters = _plain_text(
            briefing.get("why_it_matters"),
            "No additional portfolio-level implication was recorded.",
        )
        developments = briefing.get("material_developments", [])
        attention = _joined_items(
            developments,
            _plain_text(
                briefing.get("opportunity_or_risk"),
                "No separate material development requires portfolio action.",
            ),
        )
        signal_panel(
            f"Daily CIO briefing // {status}",
            decision,
            why_it_matters,
            variant="today",
        )
        st.caption(
            f"Briefing as of {format_datetime(briefing.get('as_of'))} · "
            f"Decision reference {_briefing_identifier(briefing)}"
        )
        metric_grid(
            (
                ("U.S. session", _market_session(live_market), "Live provider clock"),
                ("Live coverage", _coverage_label(live_market), "Governed instruments"),
                ("Portfolio posture", _deployment_label(cash=totals["cash"], nav=totals["nav"]), "Current capital"),
                (
                    "CIO state",
                    status,
                    "Not scored" if confidence is None else f"{float(confidence):.0%} confidence",
                ),
            ),
            variant="today",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card("What deserves attention", attention)
            st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
            text_card(
                "What changed",
                _plain_text(
                    briefing.get("what_changed"),
                    "No material change was recorded since the previous governed briefing.",
                ),
            )
        with right:
            text_card("Why it matters to the portfolio", why_it_matters)
            st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
            callout_card(
                "Recommended portfolio action",
                decision,
                (
                    "Paper implementation remains separate and cannot alter the CIO conclusion."
                ),
            )
        text_card(
            "What could change the decision",
            _joined_items(
                briefing.get("evidence_that_changes_conclusion", []),
                "No additional decision-change conditions were recorded.",
            ),
        )
        with st.expander("Decision evidence and audit reference"):
            st.write(
                "Opportunity or risk: "
                + _plain_text(
                    briefing.get("opportunity_or_risk"),
                    "No separate opportunity or risk vector was recorded.",
                )
            )
            st.write(f"Decision: {_briefing_identifier(briefing)}")
            st.write(
                "Candidate: "
                f"{briefing.get('candidate_identifier') or 'No qualified candidate'}"
            )
            st.write(f"Cycle: {briefing.get('cycle_identifier') or 'Unavailable'}")
            journal = briefing.get("journal", {})
            st.write(f"Journal sequence: {journal.get('sequence') if isinstance(journal, dict) else 'Unavailable'}")

    with st.expander("How the Today surface works"):
        surface_story(
            "Today",
            (
                ("Observe", "Continuous market intelligence remains in the background."),
                ("Resolve", "Only material portfolio implications advance to the CIO."),
                ("Act", "Capital changes only after construction and implementation validate."),
            ),
        )

    page_header(
        "Current capital position",
        "The sole governed portfolio at today's decision point.",
        "02",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(totals["nav"]), "Canonical NAV"),
            ("Available cash", format_currency(totals["cash"]), "Optionality reserve"),
            ("Total P&L", format_currency(totals.get("total_pnl", 0.0)), format_percent(totals["total_return"])),
            ("Today P&L", format_currency(totals.get("day_pnl", 0.0)), format_percent(totals.get("day_return", 0.0))),
        ),
        variant="today",
    )
    allocation_bar(cash=totals["cash"], nav=totals["nav"])

    # LIVE_TODAY_OPERATING_CONTEXT

def _render_environment() -> None:
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    live_market = load_live_market_console()
    latest_briefing = _latest("daily_cio_briefing")

    page_header(
        "Environment synopsis",
        (
            "What current market and macro evidence says, what deserves attention, "
            "and how the evidence affects the portfolio conclusion."
        ),
        "01",
    )

    quote_coverage = _coverage_label(live_market)
    unemployment = "Unavailable" if readings is None else f"{readings.unemployment_rate:.1f}%"
    inflation = "Unavailable" if readings is None else f"{readings.inflation_rate:.2f}%"
    policy_rate = "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"

    if isinstance(environment, dict):
        headline = _plain_text(environment.get("headline"), "Current environment")
        summary = _plain_text(
            environment.get("summary"),
            "No additional governed environment summary is available.",
        )
        signal_panel(
            "Environment // governed",
            headline,
            summary,
            variant="environment",
        )
        metric_grid(
            (
                ("Regime", environment.get("regime", "Unavailable"), "Governed classification"),
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _joined_items(
                    environment.get("review_conditions", []),
                    summary,
                ),
            )
        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    environment.get("portfolio_impact"),
                    _plain_text(
                        latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                        "The environment record does not independently authorize a portfolio change.",
                    ),
                ),
            )
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
        macro_summary = (
            f"Live quote coverage is {quote_coverage}. Unemployment is {unemployment}, "
            f"estimated inflation is {inflation}, and the federal funds rate is {policy_rate}. "
            "Regime: Not separately classified. No synthetic label is inferred from those readings."
        )
        signal_panel(
            "Environment // provider backed",
            "Live environment evidence is available",
            macro_summary,
            variant="environment",
        )
        metric_grid(
            (
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Unemployment", unemployment, "Labor market"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        left, right = st.columns(2, gap="large")
        with left:
            text_card(
                "What deserves attention",
                _plain_text(
                    latest_briefing.get("what_changed") if isinstance(latest_briefing, dict) else None,
                    "No separate environment warning was recorded in the latest CIO briefing.",
                ),
            )
        with right:
            text_card(
                "Portfolio implication",
                _plain_text(
                    latest_briefing.get("why_it_matters") if isinstance(latest_briefing, dict) else None,
                    "Current evidence is included in the CIO process but is not independently actionable.",
                ),
            )
        text_card(
            "What could change the assessment",
            _joined_items(
                latest_briefing.get("evidence_that_changes_conclusion", [])
                if isinstance(latest_briefing, dict)
                else [],
                "A material change in growth, inflation, policy, liquidity, or cross-asset evidence would trigger review.",
            ),
        )
    else:
        detail = _plain_text(
            live_market.get("detail"),
            str(dashboard_data.status),
        )
        signal_panel(
            "Environment // incomplete",
            "Operating environment evidence is incomplete",
            detail,
            variant="environment",
        )
        metric_grid(
            (
                ("Live coverage", quote_coverage, "Cross-asset wrappers"),
                ("Unemployment", unemployment, "Labor market"),
                ("Estimated inflation", inflation, "Price pressure"),
                ("Federal funds", policy_rate, "Policy rate"),
            ),
            variant="environment",
        )
        text_card(
            "What deserves attention",
            "Provider or macro evidence must recover before the environment can be treated as complete.",
        )

    with st.expander("How the Environment surface works"):
        surface_story(
            "Environment",
            (
                ("Growth", "Economic momentum and labor conditions."),
                ("Inflation", "Price pressure and policy sensitivity."),
                ("Liquidity", "Rates, funding and cross-asset transmission."),
            ),
        )

    # LIVE_ENVIRONMENT_MARKET_TABLE

    page_header(
        "Economic detail",
        "Provider-backed macro readings used as evidence in opportunity comparison.",
        "02",
    )
    if readings is None:
        st.warning("Live economic readings are unavailable.")
        st.caption(str(dashboard_data.status))
        return
    metric_grid(
        (
            ("Unemployment", unemployment, "Labor market"),
            ("Estimated inflation", inflation, "Price pressure"),
            ("Federal funds", policy_rate, "Policy rate"),
            ("Use", "Evidence only", "Compared across candidates"),
        ),
        variant="environment",
    )

def _render_portfolio() -> None:
    construction = _latest("portfolio_construction")
    briefing = _latest("daily_cio_briefing")
    mandate = get_mandate_details(CANONICAL_PORTFOLIO_CODE)
    if mandate is None:
        st.warning("The canonical paper portfolio is unavailable.")
        return

    nav = float(mandate["nav"])
    cash = float(mandate["cash"])
    invested = max(nav - cash, 0.0)
    deployed = 0.0 if nav <= 0 else invested / nav
    holdings = mandate.get("holdings", [])
    posture = "Fully in cash" if invested <= 0.01 else f"{deployed:.0%} invested"
    decision = _plain_text(
        briefing.get("portfolio_decision") if isinstance(briefing, dict) else None,
        "No new portfolio action is currently authorized.",
    )
    positioning_reason = _plain_text(
        briefing.get("why_it_matters") if isinstance(briefing, dict) else None,
        (
            "Capital remains in its current position until a governed opportunity "
            "clears evidence, risk, cost, liquidity, and construction controls."
        ),
    )

    page_header(
        "Portfolio synopsis",
        "Where capital is positioned, why it is there, and what action is pending now.",
        "01",
    )
    signal_panel(
        "Portfolio // current posture",
        posture,
        positioning_reason,
        variant="portfolio",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(nav), "Canonical NAV"),
            ("Available cash", format_currency(cash), "Optionality reserve"),
            ("Capital deployed", f"{deployed:.0%}", "Current exposure"),
            ("Total P&L", format_currency(mandate.get("total_pnl", 0.0)), format_percent(mandate["total_return"])),
        ),
        variant="portfolio",
    )
    left, right = st.columns(2, gap="large")
    with left:
        text_card("Why the portfolio is positioned this way", positioning_reason)
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        text_card(
            "Current holdings",
            (
                "The portfolio holds cash only."
                if not holdings
                else f"{len(holdings)} governed position{'s' if len(holdings) != 1 else ''} are currently recorded."
            ),
        )
    with right:
        callout_card("Recommended portfolio action", decision)
        st.markdown("<div style='height:.65rem'></div>", unsafe_allow_html=True)
        if construction is None:
            text_card(
                "Implementation status",
                "No construction change is queued. Existing capital remains in its current state.",
            )
        else:
            trade_count = len(construction.get("trades", []))
            text_card(
                "Implementation status",
                (
                    f"{_status_title(construction.get('status'))}. "
                    f"{trade_count} proposed paper transaction{'s' if trade_count != 1 else ''}."
                ),
            )

    with st.expander("How the Portfolio surface works"):
        surface_story(
            "Portfolio",
            (
                ("Size", "Translate conviction into a feasible portfolio weight."),
                ("Fund", "Identify the best source of capital and opportunity cost."),
                ("Validate", "Confirm concentration, cost and paper implementation."),
            ),
        )

    # PAPER_DECISION_CONTROLS

    page_header(
        "Construction detail",
        "Sizing, funding, costs, and implementation controls behind the current posture.",
        "02",
    )
    if construction is None:
        signal_panel(
            "Construction map // idle",
            "No implementation change queued",
            "No canonical construction result is required for the current no-change posture.",
            variant="portfolio",
        )
    else:
        status = _status_title(construction.get("status"))
        signal_panel(
            f"Construction map // {status}",
            "Implementation geometry resolved",
            (
                "Sizing and funding are visible for review, but construction cannot "
                "alter the CIO decision or submit broker orders."
            ),
            variant="portfolio",
        )
        metric_grid(
            (
                ("Construction state", status, "Paper implementation"),
                ("Turnover", format_percent(construction.get("turnover", 0.0)), "Portfolio movement"),
                ("Estimated cost", format_percent(construction.get("estimated_cost_return", 0.0)), "Return drag"),
                ("Expected improvement", format_percent(construction.get("expected_return_improvement", 0.0)), "Net opportunity"),
            ),
            variant="portfolio",
        )
        if construction.get("trades"):
            with st.expander("Proposed paper implementation"):
                display_frame(pd.DataFrame(construction["trades"]))
        for block in construction.get("blocks", []):
            st.warning(block)

    page_header(
        "Holdings and capital path",
        PORTFOLIO_OBJECTIVE,
        "03",
    )
    metric_grid(
        (
            ("NAV", format_currency(mandate["nav"]), "Canonical value"),
            ("Total P&L", format_currency(mandate.get("total_pnl", 0.0)), format_percent(mandate["total_return"])),
            ("Realized", format_currency(mandate.get("realized_pnl", 0.0)), "Closed positions and lifecycle cash"),
            ("Unrealized", format_currency(mandate.get("unrealized_pnl", 0.0)), "Current marks"),
        ),
        variant="portfolio",
    )
    st.caption(
        "Valuation as of "
        f"{format_datetime(mandate.get('as_of'))} · "
        f"Cash {format_currency(mandate['cash'])} · "
        f"Accounting residual {format_currency(mandate.get('accounting_residual', 0.0))}"
    )
    allocation_bar(cash=mandate["cash"], nav=mandate["nav"])

    # LIVE_PORTFOLIO_MARKS

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
                    "symbol", "asset_class", "quantity", "current_price", "cost_basis",
                    "market_value", "unrealized_gain", "unrealized_return",
                    "price_currency", "updated_at",
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
                    "created_at", "side", "symbol", "asset_class", "quantity", "price",
                    "gross_amount_base", "cost_basis_relieved_base", "realized_pnl_base",
                    "cost_amount_base", "rationale",
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
                st.line_chart(chart.sort_values("created_at").set_index("created_at")["nav"])
            columns = [
                column
                for column in (
                    "created_at", "cash_base_total", "holdings_value", "nav", "total_pnl",
                    "realized_pnl", "unrealized_pnl", "total_return",
                )
                if column in frame.columns
            ]
            frame = frame[columns] if columns else frame
            if "created_at" in frame.columns:
                frame["created_at"] = frame["created_at"].map(format_datetime)
            display_frame(frame)

def _render_history() -> None:
    briefings = _history("daily_cio_briefing")
    evaluations = _history("decision_evaluation")
    theses = _latest_theses()
    trades = get_trade_history(limit=250)

    latest_briefing = briefings[0] if briefings else {}
    latest_evaluation = evaluations[0] if evaluations else {}
    latest_thesis = theses[0] if theses else {}
    latest_trade = trades[0] if trades else {}
    latest_decision = _plain_text(
        latest_briefing.get("portfolio_decision"),
        "Awaiting the first governed CIO briefing.",
    )

    # Source-level compatibility: History synopsis — The latest decision, what happened next, and the state of the governed record.
    status_list(
        (
            (
                "Outcome status",
                _plain_text(
                    latest_evaluation.get("outcome"),
                    "Awaiting matured evaluation.",
                ),
                _plain_text(
                    latest_evaluation.get("process_verdict"),
                    "No process verdict yet.",
                ),
            ),
            (
                "Execution status",
                (
                    f"{latest_trade.get('side', '')} {latest_trade.get('symbol', '')}".strip()
                    if latest_trade
                    else "No paper trade recorded."
                ),
                "No execution activity." if not latest_trade else format_datetime(latest_trade.get("created_at")),
            ),
            (
                "Learning state",
                (
                    "Observation-only until decision horizons mature."
                    if not evaluations
                    else _plain_text(
                        latest_evaluation.get("process_verdict"),
                        "Governed review is available.",
                    )
                ),
                f"{len(theses)} living thesis record{'s' if len(theses) != 1 else ''} monitored.",
            ),
        ),
        variant="history",
    )

    # These labels remain visible through the compact status stack above:
    # Most recent decision · What changed at that decision · Outcome status · Execution status.
    with st.expander("Latest decision context", expanded=False):
        text_card("Most recent decision", latest_decision)
        text_card(
            "What changed at that decision",
            _plain_text(
                latest_briefing.get("what_changed"),
                "No material change was recorded for the latest briefing.",
            ),
        )
        text_card(
            "Why it mattered to the portfolio",
            _plain_text(
                latest_briefing.get("why_it_matters"),
                "No additional portfolio implication was recorded.",
            ),
        )

    with st.expander("How the History surface works"):
        surface_story(
            "History",
            (
                ("Record", "Preserve original evidence and the governed conclusion."),
                ("Observe", "Wait for the complete horizon and later outcomes."),
                ("Evaluate", "Separate decision quality from outcome quality."),
                ("Learn", "Inform governance without self-modifying or authorizing trades."),
            ),
        )

    # OPERATING_REPORT_HISTORY
    # CIO_REPORT_ARCHIVE

    page_header(
        "Detailed decision trail",
        "Complete institutional record of decisions, outcomes, theses, and paper execution.",
        "02",
    )
    activity_rail(
        (
            ("Decision", latest_decision, format_datetime(latest_briefing.get("as_of"))),
            (
                "Outcome",
                latest_evaluation.get("outcome") or "Awaiting matured evaluation.",
                latest_evaluation.get("process_verdict") or "No process verdict",
            ),
            (
                "Thesis",
                latest_thesis.get("asset") or "No thesis recorded.",
                latest_thesis.get("state") or "No lifecycle state",
            ),
            (
                "Execution",
                (
                    f"{latest_trade.get('side', '')} {latest_trade.get('symbol', '')}".strip()
                    or "No paper trade recorded."
                ),
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
                    (
                        {
                            "As of": format_datetime(item.get("as_of")),
                            "Status": item.get("status"),
                            "Decision": item.get("portfolio_decision"),
                            "Decision ID": _briefing_identifier(item),
                        }
                        for item in briefings
                    )
                )[["As of", "Status", "Decision"]]
            )
    with eval_tab:
        if not evaluations:
            st.info("Evaluations appear after the decision horizon has observable outcomes.")
        else:
            display_frame(
                pd.DataFrame(
                    {
                        "Decision": item.get("decision_identifier"),
                        "Process": item.get("process_verdict"),
                        "Outcome": item.get("outcome"),
                        "Value added": item.get("value_added_vs_best_alternative"),
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
                    "created_at", "side", "symbol", "asset_class", "quantity", "price",
                    "gross_amount_base", "realized_pnl_base", "cost_amount_base", "rationale",
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
