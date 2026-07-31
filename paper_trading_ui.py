"""Read-only Streamlit status for exact canonical paper implementation."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from paper_execution_runtime import (
    PaperExecutionMode,
    paper_execution_mode,
    read_paper_execution_status,
)


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def paper_execution_view(
    construction: Mapping[str, Any] | None,
) -> tuple[PaperExecutionMode, dict[str, Any] | None]:
    """Load the headless execution projection without writing runtime state."""

    return paper_execution_mode(), read_paper_execution_status(construction)


@st.fragment(run_every="5s")
def render_paper_decision_controls(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    principal: object | None,
) -> None:
    """Show paper state without authorizing or invoking implementation."""

    del principal

    if not isinstance(construction, Mapping):
        return
    trades = construction.get("trades")
    if not isinstance(trades, list) or not trades:
        return
    if construction.get("blocks"):
        st.warning("This implementation is blocked and cannot enter paper execution.")
        return

    decision_identifier = (
        None
        if not isinstance(briefing, Mapping)
        else _identifier(briefing.get("decision_identifier"))
    )
    construction_identifier = _identifier(construction.get("request_identifier"))
    if decision_identifier is None or construction_identifier is None:
        st.warning(
            "Paper execution is unavailable because the decision or construction "
            "identity is incomplete."
        )
        return

    mode, status = paper_execution_view(construction)

    st.markdown("### Paper implementation")
    st.caption(
        "Streamlit is a read-only execution observer. The headless paper operator is "
        "the sole implementation authority; real-money execution is prohibited."
    )
    if mode is PaperExecutionMode.DISABLED:
        st.info("Paper execution is disabled.")
    elif status is None:
        st.info("No headless execution status has been recorded for this construction.")
    else:
        state = str(status.get("state") or status.get("status") or "unknown")
        detail = str(status.get("detail") or status.get("error") or "")
        message = f"Headless execution state: {state}."
        if detail:
            message += f" {detail}"
        if state == "completed":
            st.success(message)
        elif state in {"blocked", "failed"}:
            st.warning(message)
        else:
            st.info(message)
        st.rerun()


__all__ = ["paper_execution_view", "render_paper_decision_controls"]
