"""Streamlit archive of CIO reports and research-only historical learning."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from cio_pending_transactions import pending_transaction_report_history
from historical_replay_ui import render_canonical_historical_replay


def _label(value: object, *, fallback: str = "Unavailable") -> str:
    text = str(value or "").strip()
    return text.replace("_", " ").title() if text else fallback


def _percent(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "—"
    return f"{float(value):.2%}"


def render_cio_report_archive() -> None:
    render_canonical_historical_replay()

    reports = pending_transaction_report_history(limit=250)
    st.markdown("#### CIO report archive")
    if not reports:
        st.info("No historical CIO pending-transaction reports are available yet.")
        return

    selected = st.selectbox(
        "Open report",
        options=list(range(len(reports))),
        format_func=lambda index: (
            f"{reports[index].get('generated_at', 'unavailable')} · "
            f"{_label(reports[index].get('execution_state'))} · "
            f"{reports[index].get('transaction_count', 0)} transaction(s)"
        ),
        key="cio-report-archive-selection",
    )
    report = reports[int(selected)]

    st.caption(
        f"Report {int(selected) + 1} of {len(reports)} · "
        f"Fingerprint {str(report.get('report_fingerprint', ''))[:16] or 'unavailable'}"
    )
    metrics = st.columns(2)
    metrics[0].metric("Report state", _label(report.get("report_state")))
    metrics[1].metric("Execution state", _label(report.get("execution_state")))
    metrics = st.columns(2)
    metrics[0].metric(
        "Transactions",
        int(report.get("transaction_count", 0)),
    )
    metrics[1].metric(
        "Target cash",
        _percent(report.get("target_cash_weight")),
    )
    metrics = st.columns(2)
    metrics[0].metric("Turnover", _percent(report.get("turnover")))
    metrics[1].metric(
        "Expected improvement",
        _percent(report.get("expected_return_improvement")),
    )

    st.markdown("##### Decision lineage")
    st.write(
        f"Generated: {report.get('generated_at') or 'Unavailable'}"
    )
    st.write(
        f"Decision: {report.get('decision_identifier') or 'Unavailable'}"
    )
    st.write(
        "Construction: "
        f"{report.get('construction_identifier') or 'Unavailable'}"
    )

    transactions = report.get("transactions")
    if isinstance(transactions, list) and transactions:
        st.markdown("##### Recommended paper transactions")
        st.dataframe(
            pd.DataFrame(transactions),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(str(report.get("summary", "No transaction was recommended.")))

    blocks = report.get("blocks")
    if isinstance(blocks, list) and blocks:
        with st.expander("Report blocks", expanded=False):
            for block in blocks:
                st.write(f"- {block}")

    if len(reports) > 1:
        with st.expander("Archive index", expanded=False):
            for index, archived in enumerate(reports, start=1):
                st.write(
                    f"{index}. {archived.get('generated_at', 'Unavailable')} · "
                    f"{_label(archived.get('report_state'))} · "
                    f"{int(archived.get('transaction_count', 0))} transaction(s)"
                )


__all__ = ["render_cio_report_archive"]
