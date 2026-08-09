"""Presentation-only refinement for the History surface."""
from __future__ import annotations

from typing import Any

import streamlit as st

_CSS = r"""
<style>
@media (max-width: 640px) {
  div[data-testid="stMetric"] { min-width: 0 !important; }
  div[data-testid="stExpander"] { margin-bottom: .35rem; }
  .history-timeline { gap: .45rem !important; }
  .history-event { padding: .8rem .9rem !important; }
}
.history-intro { color:#91a0ba; font-size:.92rem; line-height:1.55; margin:.15rem 0 1rem; }
.history-timeline { display:flex; flex-direction:column; gap:.65rem; margin:.35rem 0 1rem; }
.history-event { border:1px solid rgba(133,157,201,.22); border-radius:16px; padding:.9rem 1rem; background:rgba(7,15,29,.62); }
.history-event strong { display:block; color:#f5f7ff; font-size:1rem; line-height:1.3; }
.history-event span { color:#91a0ba; font-size:.82rem; }
</style>
"""

def _decision_title(item: dict[str, Any]) -> str:
    text = str(item.get("portfolio_decision") or item.get("status") or "No portfolio change").strip()
    low = text.lower()
    if "no transaction" in low or "no superior" in low or "no change" in low:
        return "No portfolio change"
    return text


def install(app_impl: Any) -> None:
    """Replace History with a concise story-first surface while preserving audit access."""

    @st.fragment(run_every="30s")
    def render_history(dependencies: Any) -> None:
        st.markdown(_CSS, unsafe_allow_html=True)
        briefings = app_impl._history("daily_cio_briefing")
        evaluations = app_impl._history("decision_evaluation")
        theses = app_impl._latest_theses()
        trades = dependencies.get_trade_history(limit=250)
        latest = briefings[0] if briefings else {}
        latest_trade = trades[0] if trades else {}
        latest_eval = evaluations[0] if evaluations else {}

        # The application shell already owns the canonical History h1. Keep the
        # refinement descriptive rather than emitting a second exact History
        # heading, which creates an ambiguous accessibility tree on iPhone.
        st.markdown(
            '<div class="history-intro">The CIO\'s decisions, portfolio actions, outcomes, and learning.</div>',
            unsafe_allow_html=True,
        )
        latest_decision = _decision_title(latest) if latest else "Awaiting the first governed CIO decision."
        app_impl.status_list((
            ("Outcome status", app_impl._plain_text(latest_eval.get("outcome"), "Awaiting matured evaluation."), app_impl._plain_text(latest_eval.get("process_verdict"), "No process verdict yet.")),
            ("Execution status", (f"{latest_trade.get('side','')} {latest_trade.get('symbol','')}".strip() if latest_trade else "No paper trade recorded."), app_impl.format_datetime(latest_trade.get("created_at"))),
            ("Learning state", "Observation-only until decision horizons mature." if not evaluations else "Governed review is available.", f"{len(theses)} living thesis record{'s' if len(theses) != 1 else ''} monitored."),
        ), variant="history")

        app_impl.page_header("Decision history", "What the CIO decided and when capital actually moved.", "01")
        if not briefings:
            st.info("No governed CIO decisions have been recorded yet.")
        else:
            rows = []
            for item in briefings[:12]:
                title = _decision_title(item)
                when = app_impl.format_datetime(item.get("as_of"))
                why = app_impl._plain_text(item.get("why_it_matters"), "No additional portfolio implication was recorded.")
                rows.append(f'<div class="history-event"><strong>{title}</strong><span>{when} · {why}</span></div>')
            st.markdown('<div class="history-timeline">' + ''.join(rows) + '</div>', unsafe_allow_html=True)

        with st.expander("Latest decision context", expanded=False):
            app_impl.text_card("Most recent decision", latest_decision)
            app_impl.text_card("What changed at that decision", app_impl._plain_text(latest.get("what_changed"), "No material change was recorded for the latest decision."))
            app_impl.text_card("Why it mattered to the portfolio", app_impl._plain_text(latest.get("why_it_matters"), "No additional portfolio implication was recorded."))

        app_impl.page_header("Learning & outcomes", "What prior decisions subsequently did and whether that evidence may inform future review.", "02")
        app_impl.metric_grid((
            ("Matured evaluations", str(len(evaluations)), "Observable decision outcomes"),
            ("Living theses", str(len(theses)), "Ownership records monitored"),
            ("Learning influence", "Observation only" if not evaluations else "Governed review", "Cannot authorize execution"),
            ("Paper actions", str(len(trades)), "Recorded implementation history"),
        ), variant="history")
        app_impl.callout_card("Learning boundary", "Learning informs review; it never authorizes a trade.", "Historical evidence can affect governed review only through the live CIO process.")

        app_impl.page_header(
            "Detailed decision trail",
            "Complete institutional record of decisions, outcomes, theses, and paper execution.",
            "03",
        )
        app_impl.activity_rail((
            ("Decision", latest_decision, app_impl.format_datetime(latest.get("as_of"))),
            ("Outcome", latest_eval.get("outcome") or "Awaiting matured evaluation.", latest_eval.get("process_verdict") or "No process verdict"),
            ("Execution", (f"{latest_trade.get('side','')} {latest_trade.get('symbol','')}".strip() or "No paper trade recorded."), app_impl.format_datetime(latest_trade.get("created_at"))),
        ))

        with st.expander("Governance & audit", expanded=False):
            st.caption("Technical replay, calibration, report archive, exact lineage, and complete institutional records.")
            app_impl.render_history_decision_accountability()
            app_impl.render_operating_report_history()
            app_impl.render_cio_report_archive()

    app_impl._render_history = render_history
