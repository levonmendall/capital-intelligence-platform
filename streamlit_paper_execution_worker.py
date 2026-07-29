"""Keep autonomous or manual paper execution active on every Streamlit surface."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from cio_pending_transactions import paper_trading_launch_open
from paper_execution_runtime import (
    PaperExecutionAttempt,
    PaperExecutionMode,
    attempt_approved_paper_execution,
    attempt_paper_execution,
    paper_execution_enabled,
    paper_execution_mode,
)

# Historical public name retained for compatibility.
StreamlitPaperExecutionAttempt = PaperExecutionAttempt
streamlit_paper_execution_enabled = paper_execution_enabled


@st.fragment(run_every="30s")
def render_background_paper_execution_worker(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
) -> None:
    if not paper_trading_launch_open():
        return
    attempt = attempt_paper_execution(
        construction=construction,
        briefing=briefing,
    )
    if attempt.completed:
        st.rerun()


__all__ = [
    "PaperExecutionMode",
    "StreamlitPaperExecutionAttempt",
    "attempt_approved_paper_execution",
    "attempt_paper_execution",
    "paper_execution_mode",
    "render_background_paper_execution_worker",
    "streamlit_paper_execution_enabled",
]
