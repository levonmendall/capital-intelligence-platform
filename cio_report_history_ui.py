"""Streamlit archive of CIO reports and research-only historical learning."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import premium_ui as ui

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
    ui.page_header(
        "CIO report archive",
        "Open the governed report behind each portfolio recommendation and paper-implementation state.",
        "ARC",
    )
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
    no_transaction = report.get("report_state") == "no_transaction_recommended"
    decision_reference = str(report.get("decision_identifier") or "").strip()
    if not decision_reference:
        fingerprint = str(report.get("report_fingerprint") or "").strip()
        decision_reference = f"report:{fingerprint[:16]}" if fingerprint else "Unavailable"

    st.caption(
        f"Report {int(selected) + 1} of {len(reports)} · "
        f"Fingerprint {str(report.get('report_fingerprint', ''))[:16] or 'unavailable'}"
    )
    target_allocation = (
        "Unchanged"
        if no_transaction and report.get("target_cash_weight") is None
        else _percent(report.get("target_cash_weight"))
    )
    turnover = (
        "0.00%"
        if no_transaction and report.get("turnover") is None
        else _percent(report.get("turnover"))
    )
    expected_improvement = (
        "Not applicable"
        if no_transaction and report.get("expected_return_improvement") is None
        else _percent(report.get("expected_return_improvement"))
    )
    ui.metric_grid(
        (
            ("Report state", _label(report.get("report_state")), "Portfolio recommendation"),
            ("Execution state", _label(report.get("execution_state")), "Paper worker status"),
            ("Transactions", int(report.get("transaction_count", 0)), "Recommended paper actions"),
            ("Target allocation", target_allocation, "Post-decision posture"),
            ("Turnover", turnover, "Expected portfolio movement"),
            ("Expected improvement", expected_improvement, "Net of implementation costs"),
        ),
        variant="history",
    )

    ui.callout_card(
        "Decision lineage",
        str(report.get("summary") or _label(report.get("report_state"))),
        (
            f"Generated {report.get('generated_at') or 'Unavailable'} · "
            f"Decision {decision_reference} · Construction "
            f"{report.get('construction_identifier') or ('not required' if no_transaction else 'unavailable')}"
        ),
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
