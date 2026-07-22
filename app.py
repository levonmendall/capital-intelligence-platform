from __future__ import annotations
import json
from datetime import date
import pandas as pd
import streamlit as st

from core.cio_brain import create_decision, infer_market_view, target_allocations
from core.database import connection, initialize_schema
from core.execution_engine import ExecutionError, execute_paper_trade
from core.performance_engine import mandate_metrics
from core.portfolio_engine import all_portfolios, portfolio_snapshot
from core.seed import seed_mandates

st.set_page_config(
    page_title="AI Chief Investment Office",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {padding-top: 1.25rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {background:#111827;border:1px solid #263244;padding:14px;border-radius:10px;}
.small-label {font-size:.78rem;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;}
.fund-card {border:1px solid #263244;border-radius:12px;padding:16px;background:#0b1220;margin-bottom:10px;}
</style>
""", unsafe_allow_html=True)

initialize_schema()
seed_mandates()

st.sidebar.title("AI CIO")
page = st.sidebar.radio(
    "Command Center",
    ["Executive Dashboard", "Mandates", "CIO Decision", "Paper Trade", "Decision Ledger", "System"],
)

portfolios = all_portfolios()
total_nav = sum(p["nav"] for p in portfolios)
total_start = sum(float(p["starting_capital"]) for p in portfolios)
total_gain = total_nav - total_start

if page == "Executive Dashboard":
    st.title("AI Chief Investment Office")
    st.caption("Personal, paper-only virtual asset manager · Inception July 22, 2026")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Virtual AUM", f"${total_nav:,.2f}")
    c2.metric("Starting Capital", f"${total_start:,.2f}")
    c3.metric("Net Gain/Loss", f"${total_gain:,.2f}", f"{total_gain/total_start:.2%}")
    c4.metric("Active Mandates", str(len(portfolios)))

    rows = []
    for p in portfolios:
        m = mandate_metrics(p["mandate_id"])
        rows.append({
            "Mandate": p["display_name"],
            "Risk": p["risk_level"],
            "Benchmark": p["benchmark"],
            "NAV": p["nav"],
            "Cash": p["cash"],
            "Net Return": m["net_return"],
            "Fees": m["total_fees"],
            "Positions": p["positions_count"],
        })
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.format({
            "NAV": "${:,.2f}", "Cash": "${:,.2f}",
            "Net Return": "{:.2%}", "Fees": "${:,.2f}"
        }),
        use_container_width=True,
        hide_index=True,
    )
    st.info("All eight mandates are initialized entirely in virtual cash. No live brokerage connection or real funds are used.")

elif page == "Mandates":
    st.title("Eight AI Mandates")
    selected = st.selectbox(
        "Select mandate",
        options=[p["mandate_id"] for p in portfolios],
        format_func=lambda x: next(p["display_name"] for p in portfolios if p["mandate_id"] == x),
    )
    p = next(x for x in portfolios if x["mandate_id"] == selected)
    snap = portfolio_snapshot(selected)
    metrics = mandate_metrics(selected)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NAV", f"${snap.nav:,.2f}")
    c2.metric("Cash", f"${snap.cash:,.2f}")
    c3.metric("Net Return", f"{metrics['net_return']:.2%}")
    c4.metric("Modeled Fees", f"${metrics['total_fees']:,.2f}")
    st.write(f"**Benchmark:** {p['benchmark']}  |  **Risk level:** {p['risk_level']}")
    if snap.positions:
        st.dataframe(pd.DataFrame(snap.positions), use_container_width=True, hide_index=True)
    else:
        st.warning("This mandate is currently 100% virtual cash and has not made its first paper trade.")

elif page == "CIO Decision":
    st.title("CIO Decision Engine")
    st.caption("Enter normalized evidence scores from 0 to 100. Sprint 1 uses deterministic, explainable rules.")
    cols = st.columns(5)
    growth = cols[0].slider("Growth", 0, 100, 50)
    inflation = cols[1].slider("Inflation pressure", 0, 100, 50)
    liquidity = cols[2].slider("Liquidity", 0, 100, 50)
    breadth = cols[3].slider("Market breadth", 0, 100, 50)
    volatility = cols[4].slider("Volatility risk", 0, 100, 50)
    signals = {
        "growth": growth, "inflation": inflation, "liquidity": liquidity,
        "breadth": breadth, "volatility": volatility,
    }
    view = infer_market_view(signals)
    c1, c2, c3 = st.columns(3)
    c1.metric("Regime", view.regime)
    c2.metric("CIO Confidence", f"{view.confidence:.0%}")
    c3.metric("Risk Score", f"{view.risk_score:.1f}/100")

    allocations = target_allocations(view)
    selected = st.selectbox("Review mandate allocation", list(allocations))
    alloc_df = pd.DataFrame(
        [{"Symbol": k, "Target Weight": v} for k, v in allocations[selected].items()]
    )
    st.dataframe(
        alloc_df.style.format({"Target Weight": "{:.1%}"}),
        use_container_width=True, hide_index=True
    )
    if st.button("Archive CIO decision", type="primary"):
        decision_id = create_decision(signals, notes="Created from Streamlit CIO Decision page.")
        st.success(f"Decision #{decision_id} archived. It has not executed any trades.")

elif page == "Paper Trade":
    st.title("Manual Paper Trade")
    st.warning("This changes only the virtual ledger. It cannot place a real order.")
    mandate_id = st.selectbox(
        "Mandate",
        [p["mandate_id"] for p in portfolios],
        format_func=lambda x: next(p["display_name"] for p in portfolios if p["mandate_id"] == x),
    )
    c1, c2 = st.columns(2)
    symbol = c1.text_input("Symbol", "SPY").upper().strip()
    side = c2.selectbox("Side", ["BUY", "SELL"])
    c3, c4 = st.columns(2)
    quantity = c3.number_input("Quantity", min_value=0.0001, value=1.0, step=0.1)
    price = c4.number_input("Market price", min_value=0.01, value=100.00, step=0.01)
    rationale = st.text_area("Rationale", "Manual paper trade for platform validation.")
    snap = portfolio_snapshot(mandate_id)
    st.caption(f"Available virtual cash: ${snap.cash:,.2f}")
    if st.button("Execute paper trade", type="primary"):
        try:
            result = execute_paper_trade(
                mandate_id, symbol, side, quantity, price, rationale=rationale
            )
            st.success(
                f"Paper trade #{result.trade_id} completed at ${result.execution_price:,.4f}. "
                f"Modeled costs: ${result.total_fees:,.2f}. Cash: ${result.cash_after:,.2f}."
            )
            st.rerun()
        except ExecutionError as exc:
            st.error(str(exc))

elif page == "Decision Ledger":
    st.title("Decision Ledger")
    with connection() as conn:
        decisions = conn.execute(
            """SELECT decision_id, timestamp, regime, confidence, approved, notes
               FROM cio_decisions ORDER BY decision_id DESC"""
        ).fetchall()
        trades = conn.execute(
            """SELECT trade_id, mandate_id, timestamp, symbol, side, quantity,
                      execution_price, total_fees, rationale
               FROM trades ORDER BY trade_id DESC"""
        ).fetchall()
    st.subheader("CIO Decisions")
    st.dataframe(pd.DataFrame([dict(x) for x in decisions]), use_container_width=True, hide_index=True)
    st.subheader("Paper Trades")
    st.dataframe(pd.DataFrame([dict(x) for x in trades]), use_container_width=True, hide_index=True)

else:
    st.title("System")
    st.code("streamlit run app.py")
    st.write("**Paper trading only:** Yes")
    st.write("**Inception date:** July 22, 2026")
    st.write("**Mandates:** 8")
    st.write("**Starting capital per mandate:** $25,000")
    st.write("**Total starting virtual AUM:** $200,000")
    st.write("**Database:** `database/cio_paper_funds.db`")
    st.write("**Historical V2.1 reference layer:** `legacy_v2_1/`")
