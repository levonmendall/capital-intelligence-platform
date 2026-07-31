"""Deprecated read-only Streamlit projection of headless paper execution state."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from paper_execution_runtime import (
    PaperExecutionMode,
    paper_execution_enabled,
    paper_execution_mode,
    read_paper_execution_status,
)
streamlit_paper_execution_enabled = paper_execution_enabled


def streamlit_execution_projection(
    construction: Mapping[str, Any] | None,
) -> dict[str, object]:
    """Build the read-only UI projection without invoking an operator."""

    return {
        "status": "read-only",
        "headless_execution": read_paper_execution_status(construction),
        "paper_only": True,
        "real_money_authorized": False,
    }


@st.fragment(run_every="30s")
def render_background_paper_execution_worker(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    principal: object | None = None,
) -> None:
    del briefing, principal
    st.session_state["capital_intelligence_operator_status"] = (
        streamlit_execution_projection(construction)
    )


__all__ = [
    "PaperExecutionMode",
    "paper_execution_mode",
    "render_background_paper_execution_worker",
    "streamlit_execution_projection",
    "streamlit_paper_execution_enabled",
]
