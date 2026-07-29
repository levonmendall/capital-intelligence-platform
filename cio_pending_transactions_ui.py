"""Streamlit presentation for the CIO pending-transaction report."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from cio_pending_transactions import build_pending_transaction_report


def _percentage(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.2%}"


def render_pending_transaction_report(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
) -> None:
    report = build_pending_transaction_report(
        construction=construction,
        briefing=briefing,
    )
    st.subheader("CIO Pending Transaction Recommendations")
    st.caption(
        f"Paper trading is scheduled for {report['paper_trading_start_label']}. "
        "Recommendations shown here come from the exact canonical CIO construction."
    )

    metrics = st.columns(4)
    metrics[0].metric("Pending transactions", int(report["transaction_count"]))
    metrics[1].metric("Target cash", _percentage(report.get("target_cash_weight")))
    metrics[2].metric("Turnover", _percentage(report.get("turnover")))
    metrics[3].metric(
        "Expected improvement",
        _percentage(report.get("expected_return_improvement")),
    )

    transactions = report.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        st.info(str(report["summary"]))
    else:
        rows = []
        for item in transactions:
            if not isinstance(item, Mapping):
                continue
            rows.append(
                {
                    "Symbol": str(item.get("symbol", "")),
                    "Action": str(item.get("side", "")).upper(),
                    "Current": _percentage(item.get("from_weight")),
                    "Target": _percentage(item.get("to_weight")),
                    "Change": _percentage(item.get("trade_weight")),
                    "Rationale": str(item.get("reason", "")),
                    "Status": str(item.get("status", "pending_execution")).replace(
                        "_", " "
                    ).title(),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    blocks = report.get("blocks")
    if isinstance(blocks, list) and blocks:
        with st.expander("Construction blocks", expanded=True):
            for item in blocks:
                st.write(f"- {item}")

    st.caption(
        "Paper-only report. Real-money authority remains disabled; all execution "
        "eligibility, data freshness, liquidity, cost, portfolio, and reconciliation "
        "controls remain active."
    )


__all__ = ["render_pending_transaction_report"]
