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
from operating_status import load_cio_operating_status


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
    live_market = load_live_market_console()
    totals = get_portfolio_totals()
    operating_status = load_cio_operating_status()
    _today_construction = _latest("portfolio_construction")

    # TODAY_MARKET_BRIEF

    status = (
        _status_title(briefing.get("status"))
        if isinstance(briefing, dict)
        else operating_status.label
    )
    confidence = briefing.get("confidence") if isinstance(briefing, dict) else None
    decision = _plain_text(
        briefing.get("portfolio_decision") if isinstance(briefing, dict) else None,
        operating_status.headline,
    )
    portfolio_effect = _plain_text(
        briefing.get("why_it_matters") if isinstance(briefing, dict) else None,
        "No portfolio-level implication has been authorized from the available evidence.",
    )
    change_conditions = _joined_items(
        briefing.get("evidence_that_changes_conclusion", [])
        if isinstance(briefing, dict)
        else [],
        (
            "A qualified opportunity, stronger evidence, independent review, and feasible "
            "construction are required before capital can change."
        ),
    )
    market_state = (
        f"{_market_session(live_market)} · {_coverage_label(live_market)} live coverage"
    )
    decision_note = (
        "Not scored" if confidence is None else f"{float(confidence):.0%} confidence"
    )

    page_header(
        "Decision pulse",
        "The current CIO conclusion and the few portfolio-level facts that matter now.",
        "01",
    )
    status_list(
        (
            (
                "Market status",
                market_state,
                "Provider-backed session and governed instrument coverage.",
            ),
            (
                "Portfolio action",
                decision,
                (
                    f"CIO state: {status} · {decision_note}."
                    if isinstance(briefing, dict)
                    else operating_status.detail
                ),
            ),
            (
                "Portfolio effect",
                portfolio_effect,
                "All information is interpreted through one governed portfolio.",
            ),
            (
                "What could change the decision",
                change_conditions,
                "Review trigger; not a standalone trading signal.",
            ),
        ),
        variant="today",
    )

    # TODAY_OPPORTUNITY_SCAN

    page_header(
        "Portfolio at a glance",
        "Capital, liquidity, and performance at the current decision point.",
        "02",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(totals["nav"]), "Canonical NAV"),
            ("Available cash", format_currency(totals["cash"]), "Optionality reserve"),
            (
                "Capital deployed",
                _deployment_label(cash=totals["cash"], nav=totals["nav"]),
                "Current exposure",
            ),
            (
                "Total P&L",
                format_currency(totals.get("total_pnl", 0.0)),
                format_percent(totals["total_return"]),
            ),
        ),
        variant="today",
    )
    allocation_bar(cash=totals["cash"], nav=totals["nav"])

    with st.expander("Decision evidence and audit reference", expanded=False):
        if not isinstance(briefing, dict):
            st.write("No governed CIO briefing is available yet.")
        else:
            st.write(
                "What changed: "
                + _plain_text(
                    briefing.get("what_changed"),
                    "No material change was recorded since the previous briefing.",
                )
            )
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
            st.write(
                "Journal sequence: "
                f"{journal.get('sequence') if isinstance(journal, dict) else 'Unavailable'}"
            )

    with st.expander("How the Today surface works", expanded=False):
        surface_story(
            "Today",
            (
                ("Observe", "Continuously monitor markets, economics, and material events."),
                ("Explain", "Translate developments into simple investment implications."),
                ("Resolve", "Judge whether the evidence changes the governed portfolio."),
                ("Act", "Move capital only after decision and implementation controls clear."),
            ),
        )

    # LIVE_TODAY_OPERATING_CONTEXT

def _render_environment() -> None:
    payload = _diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard_data = load_dashboard_data()
    readings = dashboard_data.readings
    live_market = load_live_market_console()
    latest_briefing = _latest("daily_cio_briefing")

    quote_coverage = _coverage_label(live_market)
    unemployment = "Unavailable" if readings is None else f"{readings.unemployment_rate:.1f}%"
    inflation = "Unavailable" if readings is None else f"{readings.inflation_rate:.2f}%"
    policy_rate = "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"
    yield_curve = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'yield_curve_spread', 0.0)):+.2f} pp"
    )

    # ENVIRONMENT_ECONOMIC_BRIEF

    if isinstance(environment, dict):
        environment_state = "Governed environment available"
        headline = _plain_text(environment.get("headline"), "Current environment")
        summary = _plain_text(
            environment.get("summary"),
            "No additional governed environment summary is available.",
        )
        regime = environment.get("regime", "Unavailable")
        attention = _joined_items(environment.get("review_conditions", []), summary)
        portfolio_impact = _plain_text(
            environment.get("portfolio_impact"),
            _plain_text(
                latest_briefing.get("why_it_matters")
                if isinstance(latest_briefing, dict)
                else None,
                "The environment record does not independently authorize a portfolio change.",
            ),
        )
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
        # Source compatibility: Live environment evidence is available.
        environment_state = "Provider-backed evidence available"
        headline = "Live market and economic evidence is available"
        summary = (
            f"Coverage is {quote_coverage}. Unemployment is {unemployment}, inflation is "
            f"{inflation}, and the federal funds rate is {policy_rate}."
        )
        regime = "Not separately classified"
        attention = _plain_text(
            latest_briefing.get("what_changed")
            if isinstance(latest_briefing, dict)
            else None,
            "No separate environment warning was recorded in the latest CIO briefing.",
        )
        portfolio_impact = _plain_text(
            latest_briefing.get("why_it_matters")
            if isinstance(latest_briefing, dict)
            else None,
            "Current evidence is included in the CIO process but is not independently actionable.",
        )
    else:
        environment_state = "Environment evidence incomplete"
        headline = "Provider or macro evidence requires attention"
        summary = _plain_text(live_market.get("detail"), str(dashboard_data.status))
        regime = "Unavailable"
        attention = (
            "Provider or macro evidence must recover before the environment can be treated as complete."
        )
        portfolio_impact = (
            "Incomplete evidence cannot independently justify changing the portfolio."
        )

    action = _plain_text(
        latest_briefing.get("portfolio_decision")
        if isinstance(latest_briefing, dict)
        else None,
        "Maintain the current portfolio while the governed CIO process evaluates the evidence.",
    )
    assessment_change_conditions = _joined_items(
        latest_briefing.get("evidence_that_changes_conclusion", [])
        if isinstance(latest_briefing, dict)
        else [],
        (
            "A material change in growth, inflation, policy, liquidity, or cross-asset "
            "evidence would trigger governed review."
        ),
    )

    page_header(
        "Market atmosphere",
        "The current economic and cross-asset setting, simplified through portfolio relevance.",
        "01",
    )
    status_list(
        (
            ("Environment state", environment_state, headline),
            ("What deserves attention", attention, summary),
            (
                "Portfolio implication",
                portfolio_impact,
                "Economic and market evidence informs the CIO; it does not authorize execution.",
            ),
            ("CIO response", action, "One governed portfolio; fail-closed when evidence is incomplete."),
        ),
        variant="environment",
    )

    page_header(
        "Macro signals",
        "The small set of readings most relevant to growth, rates, liquidity, and valuation.",
        "02",
    )
    metric_grid(
        (
            ("Regime", regime, "Governed classification"),
            ("Inflation", inflation, "Purchasing power and margins"),
            ("Federal funds", policy_rate, "Financing and discount rate"),
            ("10Y − 2Y", yield_curve, "Growth and policy expectations"),
        ),
        variant="environment",
    )

    with st.expander("What could change the assessment", expanded=False):
        st.write(assessment_change_conditions)

    # LIVE_ENVIRONMENT_MARKET_TABLE

    with st.expander("How the Environment surface works", expanded=False):
        surface_story(
            "Environment",
            (
                ("Read", "Observe growth, inflation, policy, liquidity, and cross-asset evidence."),
                ("Translate", "Explain how each condition reaches returns, risk, and valuation."),
                ("Compare", "Use the environment consistently across investable opportunities."),
                ("Constrain", "Do not treat macro data as a standalone portfolio instruction."),
            ),
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
            "Capital remains in its current position until a governed opportunity clears "
            "evidence, risk, cost, liquidity, and construction controls."
        ),
    )
    holdings_summary = (
        "Cash only"
        if not holdings
        else f"{len(holdings)} governed position{'s' if len(holdings) != 1 else ''}"
    )
    if construction is None:
        implementation_state = "No construction change queued"
        implementation_note = "Existing capital remains in its current state."
    else:
        trade_count = len(construction.get("trades", []))
        implementation_state = _status_title(construction.get("status"))
        implementation_note = (
            f"{trade_count} proposed paper transaction{'s' if trade_count != 1 else ''}."
        )

    # PORTFOLIO_INFORMATION_FRESHNESS

    page_header(
        "Portfolio posture",
        "Where capital sits, why it is positioned there, and what action is pending now.",
        "01",
    )
    status_list(
        (
            ("Current posture", posture, holdings_summary),
            ("Portfolio action", decision, "The CIO conclusion is separate from implementation."),
            ("Implementation state", implementation_state, implementation_note),
            (
                "Why capital is positioned this way",
                positioning_reason,
                "Capital moves only when a superior opportunity clears the full governed process.",
            ),
        ),
        variant="portfolio",
    )

    page_header(
        "Capital structure",
        "The four portfolio measures needed to understand the current position.",
        "02",
    )
    metric_grid(
        (
            ("Portfolio value", format_currency(nav), "Canonical NAV"),
            ("Available cash", format_currency(cash), "Optionality reserve"),
            ("Capital deployed", f"{deployed:.0%}", "Current exposure"),
            (
                "Total P&L",
                format_currency(mandate.get("total_pnl", 0.0)),
                format_percent(mandate["total_return"]),
            ),
        ),
        variant="portfolio",
    )
    allocation_bar(cash=cash, nav=nav)

    callout_card(
        "Recommended portfolio action",
        decision,
        "Paper implementation cannot alter the CIO conclusion or create real-money authority.",
    )

    # PAPER_DECISION_CONTROLS

    page_header(
        "Construction and implementation",
        "Sizing, funding, cost, and paper-execution controls behind the current posture.",
        "03",
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
                    format_percent(construction.get("estimated_cost_return", 0.0)),
                    "Return drag",
                ),
                (
                    "Expected improvement",
                    format_percent(construction.get("expected_return_improvement", 0.0)),
                    "Net opportunity",
                ),
            ),
            variant="portfolio",
        )
        if construction.get("trades"):
            with st.expander("Proposed paper implementation", expanded=False):
                display_frame(pd.DataFrame(construction["trades"]))
        for block in construction.get("blocks", []):
            st.warning(block)

    # LIVE_PORTFOLIO_MARKS

    page_header(
        "Positions and capital path",
        PORTFOLIO_OBJECTIVE,
        "04",
    )
    st.caption(
        "Valuation as of "
        f"{format_datetime(mandate.get('as_of'))} · "
        f"Cash {format_currency(mandate['cash'])} · "
        f"Accounting residual {format_currency(mandate.get('accounting_residual', 0.0))}"
    )

    holdings_tab, trades_tab, history_tab = st.tabs(
        ["Positions", "Implementation", "Capital path"]
    )
    with holdings_tab:
        if not holdings:
            st.info("The portfolio currently holds cash only.")
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

    with st.expander("How the Portfolio surface works", expanded=False):
        surface_story(
            "Portfolio",
            (
                ("Position", "Show where capital sits and why."),
                ("Size", "Translate evidence into a feasible target weight."),
                ("Fund", "Choose the best source of capital and account for opportunity cost."),
                ("Validate", "Confirm concentration, cost, liquidity, and paper implementation."),
            ),
        )

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
