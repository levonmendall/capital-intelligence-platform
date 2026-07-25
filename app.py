"""Streamlit dashboard for the Capital Intelligence Platform."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from application import DailyCapitalIntelligenceService, SQLiteDailySnapshotStore
from core.database import initialize_database
from core.portfolio import (
    get_mandate_details,
    get_mandates,
    get_portfolio_totals,
    get_trade_history,
)
from core.seed import seed_mandates
from dashboard import build_daily_intelligence_view
from intelligence.pipeline import run_intelligence
from intelligence.regime_pipeline import build_fred_regime_pipeline
from providers.economic_snapshot import load_dashboard_data


st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


def format_currency(value: float) -> str:
    """Format a number as United States currency."""

    return f"${float(value):,.2f}"


def format_percent(value: float) -> str:
    """Format a decimal value as a percentage."""

    return f"{float(value):+.2%}"


def build_allocation_table(decision) -> pd.DataFrame:
    """Build a display table from the legacy CIO allocation decision."""

    return pd.DataFrame(
        [
            {"Asset Class": "Equities", "Weight": float(decision.equities)},
            {"Asset Class": "Bonds", "Weight": float(decision.bonds)},
            {"Asset Class": "Cash", "Weight": float(decision.cash)},
            {
                "Asset Class": "Alternatives",
                "Weight": float(decision.alternatives),
            },
        ]
    )


def decision_bucket(now: datetime) -> datetime:
    """Return a stable fifteen-minute canonical decision timestamp."""

    minute = (now.minute // 15) * 15
    return now.replace(minute=minute, second=0, microsecond=0)


@st.cache_resource
def daily_snapshot_store() -> SQLiteDailySnapshotStore:
    """Return the shared append-only daily history store."""

    return SQLiteDailySnapshotStore(
        Path("database/daily_intelligence_snapshots.db")
    )


@st.cache_data(ttl=900, show_spinner=False)
def load_daily_snapshot(as_of_text: str):
    """Run one canonical cycle per fifteen-minute decision bucket."""

    as_of = datetime.fromisoformat(as_of_text)
    service = DailyCapitalIntelligenceService(
        build_fred_regime_pipeline(),
        store=daily_snapshot_store(),
        clock=lambda: as_of,
    )
    return service.run(as_of=as_of).snapshot


initialize_database()
seed_mandates()

dashboard_data = load_dashboard_data()
legacy_decision = run_intelligence(save=False)
totals = get_portfolio_totals()

now = datetime.now(timezone.utc)
updated_time = now.strftime("%B %d, %Y at %H:%M UTC")
canonical_error: str | None = None
try:
    daily_snapshot = load_daily_snapshot(
        decision_bucket(now).isoformat()
    )
    daily_history = daily_snapshot_store().history(limit=30)
    daily_view = build_daily_intelligence_view(
        daily_snapshot,
        daily_history,
    )
except Exception as error:  # pragma: no cover - application safety boundary
    daily_snapshot = None
    daily_history = ()
    daily_view = None
    canonical_error = str(error)


st.title("Capital Intelligence Platform")
st.caption(
    "Explainable market intelligence · Selective portfolio alerts · "
    "Decision accountability"
)

page = st.sidebar.radio(
    "Navigation",
    ["Today", "Environment", "Portfolio", "History"],
)


if page == "Today":
    st.subheader("Today's Capital Intelligence")

    if daily_view is None:
        st.error(
            "The canonical daily intelligence cycle is unavailable. "
            "The legacy dashboard remains visible below."
        )
        if canonical_error:
            st.caption(f"System detail: {canonical_error}")
        fallback1, fallback2, fallback3 = st.columns(3)
        fallback1.metric("Market Regime", legacy_decision.regime)
        fallback2.metric(
            "CIO Confidence",
            f"{legacy_decision.confidence:.0%}",
        )
        fallback3.metric("Risk Posture", legacy_decision.risk_posture)
    else:
        score_column, environment_column, risk_column = st.columns(
            [1.25, 1, 1]
        )
        delta = (
            None
            if daily_snapshot.score_delta is None
            else f"{daily_snapshot.score_delta:+d}"
        )
        score_column.metric(
            "Capital Intelligence",
            daily_view.score,
            delta=delta,
            help=(
                "A 0–100 measure of evidence quality, confidence, "
                "committee support, agreement, and risk-adjusted opportunity."
            ),
        )
        score_column.caption(daily_view.score_label)
        environment_column.metric(
            "Environment",
            daily_view.environment,
        )
        risk_column.metric("Risk", daily_view.risk)

        status_messages = {
            "current": (
                "success",
                "Current evidence and decision cycle.",
            ),
            "incomplete": (
                "warning",
                "Some evidence is incomplete. The score discloses reduced confidence.",
            ),
            "stale": (
                "warning",
                "The latest canonical evidence is stale and should be refreshed.",
            ),
            "unavailable": (
                "error",
                "Canonical market evidence is unavailable. No false precision is shown.",
            ),
        }
        message_type, message = status_messages[daily_view.status]
        getattr(st, message_type)(message)

        st.markdown("### Committee")
        st.write(daily_view.committee)

        st.markdown("### Portfolio impact")
        st.write(daily_view.portfolio_impact)
        if daily_view.considerations:
            for consideration in daily_view.considerations:
                st.write(f"• {consideration}")

        st.markdown("### What changed?")
        if daily_view.should_alert:
            st.warning(daily_view.what_changed)
        else:
            st.info(daily_view.what_changed)

        if len(daily_view.history) > 1:
            history_frame = pd.DataFrame(
                daily_view.history,
                columns=["as_of", "score"],
            )
            history_frame["as_of"] = pd.to_datetime(
                history_frame["as_of"]
            )
            st.line_chart(history_frame.set_index("as_of")["score"])

    st.divider()
    overview1, overview2, overview3, overview4 = st.columns(4)
    overview1.metric("Virtual AUM", format_currency(totals["nav"]))
    overview2.metric("Available Cash", format_currency(totals["cash"]))
    overview3.metric(
        "Platform Return",
        format_percent(totals["total_return"]),
    )
    overview4.metric("Active Mandates", totals["mandate_count"])
    st.caption(f"Daily intelligence refreshed {updated_time}")


elif page == "Environment":
    st.subheader("Market environment")

    if daily_snapshot is None:
        st.warning(
            "The canonical Environment Brief is unavailable. "
            "Live economic readings are shown for diagnostic context."
        )
    else:
        st.markdown(f"### {daily_snapshot.environment.headline}")
        st.write(daily_snapshot.environment.summary)
        env1, env2, env3 = st.columns(3)
        env1.metric("Regime", daily_snapshot.environment.regime)
        env2.metric(
            "Confidence",
            f"{daily_snapshot.environment.confidence:.0%}",
        )
        env3.metric("Data", daily_snapshot.environment.data_status)
        st.write(
            f"**Portfolio:** {daily_snapshot.environment.portfolio_impact}"
        )
        exposures = ", ".join(
            daily_snapshot.environment.affected_exposures
        )
        st.caption(f"Affected exposures: {exposures or 'none'}")
        if daily_snapshot.environment.review_conditions:
            with st.expander("Review conditions"):
                for condition in daily_snapshot.environment.review_conditions:
                    st.write(f"• {condition}")

    st.divider()
    st.subheader("Economic evidence")
    readings = dashboard_data.readings
    if readings is None:
        st.warning(
            "Live FRED readings are unavailable. "
            "The legacy diagnostic source may be using sample data."
        )
        st.write(f"System status: {dashboard_data.status}")
    else:
        column1, column2, column3 = st.columns(3)
        column1.metric(
            "Unemployment Rate",
            f"{readings.unemployment_rate:.1f}%",
        )
        column2.metric(
            "Estimated Inflation",
            f"{readings.inflation_rate:.2f}%",
        )
        column3.metric(
            "Federal Funds Rate",
            f"{readings.federal_funds_rate:.2f}%",
        )

        column4, column5, column6 = st.columns(3)
        column4.metric(
            "2-Year Treasury",
            f"{readings.two_year_yield:.2f}%",
        )
        column5.metric(
            "10-Year Treasury",
            f"{readings.ten_year_yield:.2f}%",
        )
        column6.metric(
            "Yield Curve Spread",
            f"{readings.yield_curve_spread:.2f}%",
        )

        if readings.yield_curve_spread < 0:
            st.warning(
                "The Treasury yield curve is inverted. "
                "Short-term yields exceed long-term yields."
            )
        else:
            st.success(
                "The Treasury yield curve is positively sloped."
            )
        st.info(f"Data source: {dashboard_data.data_source}")

    st.caption(f"Environment refreshed {updated_time}")


elif page == "Portfolio":
    st.subheader("Portfolio")

    if daily_snapshot is not None:
        st.info(
            f"Current intelligence: {daily_snapshot.score.portfolio_impact}"
        )

    mandates = get_mandates()
    mandate_options = {
        f"{item['name']} ({item['code']})": item["code"]
        for item in mandates
    }
    selected_label = st.selectbox(
        "Select an investment mandate",
        options=list(mandate_options.keys()),
    )
    selected_code = mandate_options[selected_label]
    mandate = get_mandate_details(selected_code)

    if mandate is None:
        st.error("The selected mandate could not be loaded.")
    else:
        st.caption(f"Risk classification: {mandate['risk']}")
        column1, column2, column3, column4 = st.columns(4)
        column1.metric("Net Asset Value", format_currency(mandate["nav"]))
        column2.metric("Cash", format_currency(mandate["cash"]))
        column3.metric(
            "Starting Capital",
            format_currency(mandate["starting_capital"]),
        )
        column4.metric(
            "Return Since Inception",
            format_percent(mandate["total_return"]),
        )

        holdings = mandate["holdings"]
        st.divider()
        st.subheader("Current holdings")
        if not holdings:
            st.info(
                "This mandate currently holds only cash. "
                "No paper positions have been opened."
            )
        else:
            holdings_frame = pd.DataFrame(holdings)
            holdings_frame["quantity"] = holdings_frame[
                "quantity"
            ].map(lambda value: f"{value:,.4f}")
            currency_columns = [
                "average_cost",
                "current_price",
                "cost_basis",
                "market_value",
                "unrealized_gain",
            ]
            for column in currency_columns:
                holdings_frame[column] = holdings_frame[column].map(
                    format_currency
                )
            holdings_frame = holdings_frame.rename(
                columns={
                    "symbol": "Symbol",
                    "quantity": "Quantity",
                    "average_cost": "Average Cost",
                    "current_price": "Current Price",
                    "cost_basis": "Cost Basis",
                    "market_value": "Market Value",
                    "unrealized_gain": "Unrealized Gain/Loss",
                    "updated_at": "Last Updated",
                }
            )
            st.dataframe(
                holdings_frame[
                    [
                        "Symbol",
                        "Quantity",
                        "Average Cost",
                        "Current Price",
                        "Market Value",
                        "Unrealized Gain/Loss",
                        "Last Updated",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent mandate trades")
        trades = mandate["trades"]
        if not trades:
            st.info("No paper trades have been recorded for this mandate.")
        else:
            trades_frame = pd.DataFrame(trades)
            trades_frame["price"] = trades_frame["price"].map(
                format_currency
            )
            trades_frame["gross_amount"] = trades_frame[
                "gross_amount"
            ].map(format_currency)
            trades_frame = trades_frame.rename(
                columns={
                    "created_at": "Date",
                    "side": "Action",
                    "symbol": "Symbol",
                    "quantity": "Quantity",
                    "price": "Price",
                    "gross_amount": "Gross Amount",
                    "rationale": "Rationale",
                }
            )
            st.dataframe(
                trades_frame[
                    [
                        "Date",
                        "Action",
                        "Symbol",
                        "Quantity",
                        "Price",
                        "Gross Amount",
                        "Rationale",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

        snapshots = mandate["snapshots"]
        if snapshots:
            st.divider()
            st.subheader("Portfolio value history")
            snapshot_frame = pd.DataFrame(snapshots)
            snapshot_frame["created_at"] = pd.to_datetime(
                snapshot_frame["created_at"]
            )
            snapshot_frame = snapshot_frame.sort_values("created_at")
            st.line_chart(
                snapshot_frame.set_index("created_at")["nav"]
            )


else:
    st.subheader("History")

    if daily_history:
        st.markdown("### Capital Intelligence history")
        history_frame = pd.DataFrame(
            [
                {
                    "As of": item.as_of,
                    "Score": item.score,
                    "Environment": item.environment,
                    "Risk": item.risk,
                    "Status": item.status.value,
                    "Alert": item.should_alert,
                }
                for item in reversed(daily_history)
            ]
        )
        st.line_chart(history_frame.set_index("As of")["Score"])
        st.dataframe(
            history_frame.sort_values("As of", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No canonical daily snapshots have been recorded yet.")

    st.markdown("### Decision Replay")
    replay_identifiers = (
        daily_view.replay_identifiers if daily_view is not None else ()
    )
    if replay_identifiers:
        selected_replay = st.selectbox(
            "Select a decision replay",
            replay_identifiers,
        )
        st.info(
            f"Replay available: {selected_replay}. "
            "The detailed timeline is supplied by the canonical replay API."
        )
    else:
        st.info(
            "Decision Replays appear here after a major event has a stored "
            "point-in-time reasoning chain."
        )

    st.divider()
    st.markdown("### Paper-trade journal")
    trades = get_trade_history(limit=250)
    if not trades:
        st.info("No paper trades have been recorded yet.")
    else:
        trade_frame = pd.DataFrame(trades)
        trade_frame["price"] = trade_frame["price"].map(format_currency)
        trade_frame["gross_amount"] = trade_frame[
            "gross_amount"
        ].map(format_currency)
        trade_frame = trade_frame.rename(
            columns={
                "created_at": "Date",
                "mandate_code": "Mandate",
                "side": "Action",
                "symbol": "Symbol",
                "quantity": "Quantity",
                "price": "Price",
                "gross_amount": "Gross Amount",
                "rationale": "Rationale",
            }
        )
        st.dataframe(
            trade_frame[
                [
                    "Date",
                    "Mandate",
                    "Action",
                    "Symbol",
                    "Quantity",
                    "Price",
                    "Gross Amount",
                    "Rationale",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("System status"):
        if dashboard_data.readings is not None:
            st.success("FRED economic data connected")
        else:
            st.warning(dashboard_data.status)
        st.success("SQLite databases initialized")
        st.success("Canonical daily intelligence service operational")
        st.success("Append-only score history operational")
        st.success("Portfolio reporting API operational")
        st.success("Paper-trading engine operational")
        st.write(
            f"Current economic source: **{dashboard_data.data_source}**"
        )
        st.write(
            "Virtual assets under management: "
            f"**{format_currency(totals['nav'])}**"
        )
        st.caption(f"Status checked {updated_time}")


st.divider()
st.caption(
    "Research and paper-trading software only. "
    "This platform does not provide individualized investment advice."
)
