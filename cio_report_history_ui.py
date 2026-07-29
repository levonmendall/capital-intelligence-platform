"""Streamlit archive of authoritative CIO pending-transaction report states."""

from __future__ import annotations

from typing import Mapping

import pandas as pd
import streamlit as st

from cio_pending_transactions import pending_transaction_report_history


def render_cio_report_archive() -> None:
    reports = pending_transaction_report_history(limit=250)
    st.markdown("#### CIO report archive")
    if not reports:
        st.info("No historical CIO pending-transaction reports are available yet.")
        return

    rows = []
    for report in reports:
        rows.append(
            {
                "Generated": report.get("generated_at"),
                "Decision": report.get("decision_identifier"),
                "Construction": report.get("construction_identifier"),
                "Report state": str(report.get("report_state", "")).replace(
                    "_", " "
                ).title(),
                "Execution state": str(report.get("execution_state", "")).replace(
                    "_", " "
                ).title(),
                "Transactions": int(report.get("transaction_count", 0)),
                "Target cash": report.get("target_cash_weight"),
                "Turnover": report.get("turnover"),
                "Expected improvement": report.get("expected_return_improvement"),
                "Fingerprint": str(report.get("report_fingerprint", ""))[:16],
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    selected = st.selectbox(
        "Open report state",
        options=list(range(len(reports))),
        format_func=lambda index: (
            f"{reports[index].get('generated_at', 'unavailable')} · "
            f"{str(reports[index].get('execution_state', 'unavailable')).replace('_', ' ').title()} · "
            f"{reports[index].get('transaction_count', 0)} transaction(s)"
        ),
        key="cio-report-archive-selection",
    )
    report = reports[int(selected)]
    transactions = report.get("transactions")
    if isinstance(transactions, list) and transactions:
        st.dataframe(pd.DataFrame(transactions), use_container_width=True, hide_index=True)
    else:
        st.info(str(report.get("summary", "No transaction was recommended.")))
    blocks = report.get("blocks")
    if isinstance(blocks, list) and blocks:
        with st.expander("Report blocks", expanded=False):
            for block in blocks:
                st.write(f"- {block}")


__all__ = ["render_cio_report_archive"]
