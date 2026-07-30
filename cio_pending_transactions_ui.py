"""Streamlit presentation for the authoritative CIO pending-transaction report."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from cio_pending_transactions import resolve_pending_transaction_report


def _percentage(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.2%}"


def render_pending_transaction_report(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
) -> None:
    report = resolve_pending_transaction_report(
        construction=construction,
        briefing=briefing,
    )
    st.subheader("CIO Pending Transaction Recommendations")
    st.caption(
        f"Paper trading launch: {report['paper_trading_start_label']} · "
        f"Execution state: {str(report.get('execution_state', 'unavailable')).replace('_', ' ').title()} · "
        "Exact canonical CIO construction"
    )

    no_transaction = report.get("report_state") == "no_transaction_recommended"
    metrics = st.columns(4)
    metrics[0].metric("Transactions", int(report["transaction_count"]))
    metrics[1].metric(
        "Target allocation",
        (
            "Unchanged"
            if no_transaction and report.get("target_cash_weight") is None
            else _percentage(report.get("target_cash_weight"))
        ),
    )
    metrics[2].metric(
        "Turnover",
        (
            "0.00%"
            if no_transaction and report.get("turnover") is None
            else _percentage(report.get("turnover"))
        ),
    )
    metrics[3].metric(
        "Expected improvement",
        (
            "Not applicable"
            if no_transaction and report.get("expected_return_improvement") is None
            else _percentage(report.get("expected_return_improvement"))
        ),
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
        f"Report generated {report.get('generated_at', 'unavailable')} · "
        f"Fingerprint {str(report.get('report_fingerprint', 'unavailable'))[:16]} · "
        "Paper only; real-money authority disabled."
    )


__all__ = ["render_pending_transaction_report"]
