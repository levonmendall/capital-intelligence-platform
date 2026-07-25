"""Streamlit dashboard for the Capital Intelligence Platform."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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
from personalization import (
    InvestorBehaviorTag,
    InvestorDecisionAction,
    InvestorMemoryEvent,
    InvestorMemoryEventType,
    InvestorRiskLevel,
    SQLiteInvestorMemoryStore,
)
from portfolio import (
    AssetBucket,
    FundingCandidate,
    PortfolioMandate,
    PortfolioPosition,
    PortfolioProposal,
    PortfolioSnapshot,
    assess_opportunity_cost,
)
from providers.economic_snapshot import load_dashboard_data
from reporting import build_conviction_trend_from_store


st.set_page_config(
    page_title="Capital Intelligence Platform",
    page_icon="📊",
    layout="wide",
)


INVESTOR_IDENTIFIER = "primary"


def format_currency(value: float) -> str:
    """Format a number as United States currency."""

    return f"${float(value):,.2f}"


def format_percent(value: float) -> str:
    """Format a decimal value as a percentage."""

    return f"{float(value):+.2%}"


def decision_bucket(now: datetime) -> datetime:
    """Return a stable fifteen-minute canonical decision timestamp."""

    minute = (now.minute // 15) * 15
    return now.replace(minute=minute, second=0, microsecond=0)


@st.cache_resource
def daily_snapshot_store() -> SQLiteDailySnapshotStore:
    return SQLiteDailySnapshotStore(
        Path("database/daily_intelligence_snapshots.db")
    )


@st.cache_resource
def investor_memory_store() -> SQLiteInvestorMemoryStore:
    return SQLiteInvestorMemoryStore(Path("database/investor_memory.db"))


@st.cache_data(ttl=900, show_spinner=False)
def load_daily_snapshot(as_of_text: str):
    as_of = datetime.fromisoformat(as_of_text)
    service = DailyCapitalIntelligenceService(
        build_fred_regime_pipeline(),
        store=daily_snapshot_store(),
        clock=lambda: as_of,
    )
    return service.run(as_of=as_of).snapshot


def _legacy_portfolio_snapshot(mandate: dict, *, as_of: datetime) -> PortfolioSnapshot:
    """Build a weight-only context for the non-executing opportunity-cost view."""

    nav = float(mandate["nav"])
    cash_weight = max(0.0, min(1.0, float(mandate["cash"]) / nav))
    positions: list[PortfolioPosition] = []
    for holding in mandate["holdings"]:
        market_value = float(holding["market_value"])
        weight = max(0.0, market_value / nav)
        if weight <= 0.0:
            continue
        symbol = str(holding["symbol"])
        positions.append(
            PortfolioPosition(
                identifier=symbol,
                bucket=AssetBucket.EQUITY,
                weight=weight,
                risk_budget_usage=0.0,
                liquidity_score=1.0,
                exposure_tags=(symbol.lower(),),
            )
        )
    invested = sum(position.weight for position in positions)
    total = cash_weight + invested
    if total <= 0:
        return PortfolioSnapshot(
            identifier=f"display:{mandate['code']}:{as_of.isoformat()}",
            as_of=as_of,
            nav=nav,
            cash_weight=1.0,
            risk_budget_used=0.0,
            positions=(),
        )
    cash_weight = round(cash_weight / total, 6)
    normalized_positions = tuple(
        PortfolioPosition(
            identifier=position.identifier,
            bucket=position.bucket,
            weight=round(position.weight / total, 6),
            risk_budget_usage=0.0,
            liquidity_score=1.0,
            exposure_tags=position.exposure_tags,
        )
        for position in positions
    )
    difference = round(
        1.0 - cash_weight - sum(item.weight for item in normalized_positions),
        6,
    )
    if normalized_positions and difference:
        first, *rest = normalized_positions
        normalized_positions = (
            PortfolioPosition(
                identifier=first.identifier,
                bucket=first.bucket,
                weight=round(first.weight + difference, 6),
                risk_budget_usage=first.risk_budget_usage,
                liquidity_score=first.liquidity_score,
                exposure_tags=first.exposure_tags,
            ),
            *rest,
        )
    else:
        cash_weight = round(cash_weight + difference, 6)
    return PortfolioSnapshot(
        identifier=f"display:{mandate['code']}:{as_of.isoformat()}",
        as_of=as_of,
        nav=nav,
        cash_weight=cash_weight,
        risk_budget_used=0.0,
        positions=normalized_positions,
    )


initialize_database()
seed_mandates()

dashboard_data = load_dashboard_data()
legacy_decision = run_intelligence(save=False)
totals = get_portfolio_totals()

now = datetime.now(timezone.utc)
updated_time = now.strftime("%B %d, %Y at %H:%M UTC")
canonical_error: str | None = None
try:
    daily_snapshot = load_daily_snapshot(decision_bucket(now).isoformat())
    daily_history = daily_snapshot_store().history(limit=30)
    daily_view = build_daily_intelligence_view(daily_snapshot, daily_history)
    conviction_trend = build_conviction_trend_from_store(
        daily_snapshot_store().path,
        lookback=7,
    )
except Exception as error:  # pragma: no cover - application safety boundary
    daily_snapshot = None
    daily_history = ()
    daily_view = None
    conviction_trend = None
    canonical_error = str(error)

try:
    memory_profile = investor_memory_store().profile(INVESTOR_IDENTIFIER)
except Exception:  # pragma: no cover - application safety boundary
    memory_profile = None


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
        score_column, conviction_column, environment_column, risk_column = (
            st.columns([1.25, 1, 1, 1])
        )
        score_delta = (
            None
            if daily_snapshot.score_delta is None
            else f"{daily_snapshot.score_delta:+d}"
        )
        score_column.metric(
            "Capital Intelligence",
            daily_view.score,
            delta=score_delta,
            help=(
                "A 0–100 measure of evidence quality, confidence, committee "
                "support, agreement, and risk-adjusted opportunity."
            ),
        )
        score_column.caption(daily_view.score_label)
        if conviction_trend is None or conviction_trend.current is None:
            conviction_column.metric("Conviction", "—")
            conviction_column.caption("No trend history yet")
        else:
            conviction_delta = (
                None
                if conviction_trend.change_points is None
                else f"{conviction_trend.change_points:+d}"
            )
            conviction_column.metric(
                "Conviction",
                conviction_trend.current,
                delta=conviction_delta,
            )
            conviction_column.caption(
                conviction_trend.direction.value.title()
            )
        environment_column.metric("Environment", daily_view.environment)
        risk_column.metric("Risk", daily_view.risk)

        status_messages = {
            "current": ("success", "Current evidence and decision cycle."),
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

        if conviction_trend is not None:
            st.caption(conviction_trend.explanation)

        st.markdown("### Committee")
        st.write(daily_view.committee)

        st.markdown("### Portfolio impact")
        st.write(daily_view.portfolio_impact)
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
            history_frame["as_of"] = pd.to_datetime(history_frame["as_of"])
            st.line_chart(history_frame.set_index("as_of")["score"])

    st.divider()
    overview1, overview2, overview3, overview4 = st.columns(4)
    overview1.metric("Virtual AUM", format_currency(totals["nav"]))
    overview2.metric("Available Cash", format_currency(totals["cash"]))
    overview3.metric("Platform Return", format_percent(totals["total_return"]))
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
        exposures = ", ".join(daily_snapshot.environment.affected_exposures)
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
        column4.metric("2-Year Treasury", f"{readings.two_year_yield:.2f}%")
        column5.metric("10-Year Treasury", f"{readings.ten_year_yield:.2f}%")
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
            st.success("The Treasury yield curve is positively sloped.")
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
            holdings_frame["quantity"] = holdings_frame["quantity"].map(
                lambda value: f"{value:,.4f}"
            )
            for column in (
                "average_cost",
                "current_price",
                "cost_basis",
                "market_value",
                "unrealized_gain",
            ):
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

        with st.expander("Compare the opportunity cost of a new allocation"):
            st.caption(
                "This is a non-executing comparison. Cash reserve and any "
                "position reduction are explicit inputs; the platform does not "
                "choose a sale silently."
            )
            target = st.text_input(
                "Proposed exposure",
                value="New risk asset exposure",
            )
            requested_percent = st.slider(
                "Requested portfolio increase",
                min_value=1,
                max_value=20,
                value=3,
                step=1,
            )
            reserve_percent = st.slider(
                "Minimum cash reserve",
                min_value=0,
                max_value=30,
                value=5,
                step=1,
            )
            holding_symbols = [str(item["symbol"]) for item in holdings]
            selected_funding = st.selectbox(
                "Explicit position reduction after excess cash",
                options=["None", *holding_symbols],
            )
            reduction_percent = 0
            if selected_funding != "None":
                reduction_percent = st.slider(
                    "Maximum position reduction",
                    min_value=1,
                    max_value=20,
                    value=3,
                    step=1,
                )
            if st.button("Explain opportunity cost"):
                context = _legacy_portfolio_snapshot(mandate, as_of=now)
                mandate_policy = PortfolioMandate(
                    identifier=f"display:{selected_code}",
                    version="display-opportunity-cost.v1",
                    maximum_position_weight=1.0,
                    minimum_cash_weight=reserve_percent / 100,
                    maximum_risk_budget=1.0,
                    minimum_liquidity_score=0.0,
                    bucket_limits=(),
                )
                proposal = PortfolioProposal(
                    identifier=f"display-proposal:{uuid4()}",
                    source_decision_identifier=(
                        daily_snapshot.score.decision_identifier
                        if daily_snapshot is not None
                        else "legacy-display-decision"
                    ),
                    target_identifier=target,
                    bucket=AssetBucket.EQUITY,
                    requested_weight_delta=requested_percent / 100,
                    estimated_risk_budget_delta=requested_percent / 100,
                    liquidity_score=1.0,
                )
                candidates: tuple[FundingCandidate, ...] = ()
                if selected_funding != "None":
                    candidates = (
                        FundingCandidate(
                            position_identifier=selected_funding,
                            maximum_reduction=reduction_percent / 100,
                            priority=1,
                            reason="explicitly selected as the funding source",
                            trade_off=(
                                f"The portfolio may forgo future upside and "
                                f"diversification from {selected_funding}."
                            ),
                        ),
                    )
                assessment = assess_opportunity_cost(
                    context,
                    mandate_policy,
                    proposal,
                    funding_candidates=candidates,
                )
                st.write(assessment.summary)
                for source in assessment.funding_sources:
                    st.write(f"• {source.explanation}")
                for trade_off in assessment.trade_offs:
                    st.warning(trade_off)
                if assessment.alternative_sources:
                    st.caption(
                        "Overlapping positions worth reviewing: "
                        + ", ".join(assessment.alternative_sources)
                    )

        st.divider()
        st.subheader("Recent mandate trades")
        trades = mandate["trades"]
        if not trades:
            st.info("No paper trades have been recorded for this mandate.")
        else:
            trades_frame = pd.DataFrame(trades)
            trades_frame["price"] = trades_frame["price"].map(format_currency)
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
            st.line_chart(snapshot_frame.set_index("created_at")["nav"])


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

    if conviction_trend is not None and conviction_trend.observations:
        st.markdown("### Conviction trend")
        conviction_frame = pd.DataFrame(
            [
                {
                    "As of": observation.as_of,
                    "Conviction": observation.conviction,
                    "Capital Intelligence": (
                        observation.capital_intelligence_score
                    ),
                }
                for observation in conviction_trend.observations
            ]
        )
        st.line_chart(
            conviction_frame.set_index("As of")[
                ["Conviction", "Capital Intelligence"]
            ]
        )
        st.caption(conviction_trend.explanation)

    st.markdown("### Investor Memory")
    if memory_profile is None or memory_profile.total_events == 0:
        st.info(
            "No investor behavior has been recorded yet. Memory is built only "
            "from explicit reflections and preferences."
        )
    else:
        memory1, memory2 = st.columns(2)
        memory1.metric(
            "Preferred risk",
            (
                memory_profile.preferred_risk_level.value.title()
                if memory_profile.preferred_risk_level is not None
                else "Not recorded"
            ),
        )
        memory2.metric("Recorded events", memory_profile.total_events)
        if memory_profile.recurring_mistakes:
            st.markdown("**Recurring mistakes**")
            for pattern in memory_profile.recurring_mistakes:
                st.write(f"• {pattern.label} ({pattern.count} records)")
        elif memory_profile.recurring_patterns:
            st.markdown("**Recurring patterns**")
            for pattern in memory_profile.recurring_patterns:
                st.write(f"• {pattern.label} ({pattern.count} records)")
        if memory_profile.lessons:
            st.markdown("**Lessons to carry forward**")
            for lesson in memory_profile.lessons:
                st.write(f"• {lesson}")

    with st.expander("Add an investor reflection"):
        risk_level = st.selectbox(
            "Preferred risk level",
            [level.value for level in InvestorRiskLevel],
            index=1,
        )
        if st.button("Save risk preference"):
            event = InvestorMemoryEvent(
                identifier=f"investor-memory:{uuid4()}",
                investor_identifier=INVESTOR_IDENTIFIER,
                recorded_at=datetime.now(timezone.utc),
                event_type=InvestorMemoryEventType.RISK_PREFERENCE,
                summary=f"Preferred risk level set to {risk_level}.",
                risk_level=InvestorRiskLevel(risk_level),
            )
            investor_memory_store().append(event)
            st.success("Risk preference recorded.")
            st.rerun()

        action = st.selectbox(
            "How did you respond to the latest decision?",
            [value.value for value in InvestorDecisionAction],
        )
        tag_options = {
            tag.value: tag for tag in InvestorBehaviorTag
        }
        selected_tags = st.multiselect(
            "Behavior patterns observed",
            options=list(tag_options),
        )
        recorded_mistake = st.checkbox(
            "Record this as a mistake to learn from"
        )
        reflection = st.text_area(
            "Lesson or reflection",
            placeholder="What should the personal CIO remember next time?",
        )
        if st.button("Save decision reflection"):
            tags = tuple(tag_options[value] for value in selected_tags)
            event_type = (
                InvestorMemoryEventType.MISTAKE
                if recorded_mistake
                else InvestorMemoryEventType.DECISION_ACTION
            )
            if recorded_mistake and (not tags or not reflection.strip()):
                st.error(
                    "A mistake record needs at least one pattern and a lesson."
                )
            else:
                event = InvestorMemoryEvent(
                    identifier=f"investor-memory:{uuid4()}",
                    investor_identifier=INVESTOR_IDENTIFIER,
                    recorded_at=datetime.now(timezone.utc),
                    event_type=event_type,
                    summary=(
                        reflection.strip()
                        or f"Latest decision response: {action}."
                    ),
                    source_decision_identifier=(
                        daily_snapshot.score.decision_identifier
                        if daily_snapshot is not None
                        else None
                    ),
                    action=InvestorDecisionAction(action),
                    behavior_tags=tags,
                    lesson=reflection.strip() or None,
                )
                investor_memory_store().append(event)
                st.success("Decision reflection recorded.")
                st.rerun()

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
        trade_frame["gross_amount"] = trade_frame["gross_amount"].map(
            format_currency
        )
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
        st.success("Append-only investor memory operational")
        st.success("Read-only production API operational")
        st.write(f"Current economic source: **{dashboard_data.data_source}**")
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
