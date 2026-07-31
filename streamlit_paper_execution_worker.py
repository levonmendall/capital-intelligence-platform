"""Keep the complete autonomous CIO and paper operation active in Streamlit.

A standalone Streamlit deployment therefore performs the same scheduled CIO cycle,
report generation, delivery drain, launch gating, and paper execution as the headless
operator. Existing scheduler and execution leases keep multiple app sessions or an
attached Docker scheduler idempotent.
"""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from api.config import ApiSettings
from paper_execution_runtime import (
    PaperExecutionAttempt,
    PaperExecutionMode,
    attempt_approved_paper_execution,
    attempt_paper_execution,
    paper_execution_enabled,
    paper_execution_mode,
)
from portfolio.state import ensure_canonical_portfolio_store
from run_autonomous_paper_operator import _run_pass
from run_scheduler import build_worker

# Historical public names retained for compatibility.
StreamlitPaperExecutionAttempt = PaperExecutionAttempt
streamlit_paper_execution_enabled = paper_execution_enabled


def _has_private_operator_access(principal: object | None) -> bool:
    """Return true only for an authenticated administrator session."""

    return bool(
        principal is not None
        and not getattr(principal, "is_anonymous", False)
        and getattr(principal, "is_administrator", False)
    )


@st.cache_resource
def _streamlit_operator_runtime():
    settings = ApiSettings.from_env()
    ensure_canonical_portfolio_store(settings.portfolio_database)
    return settings, build_worker(settings)


def _run_streamlit_operator_pass() -> dict[str, object]:
    settings, worker = _streamlit_operator_runtime()
    return _run_pass(settings=settings, worker=worker)


@st.fragment(run_every="30s")
def render_background_paper_execution_worker(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    principal: object | None = None,
) -> None:
    if not _has_private_operator_access(principal):
        st.session_state["capital_intelligence_operator_status"] = {
            "status": "read-only",
            "detail": "The Streamlit paper operator is private.",
            "paper_only": True,
            "real_money_authorized": False,
        }
        return

    # The parameters preserve the prior public contract. The authoritative pass reloads
    # the journal after running the due CIO cycle so it cannot execute stale page values.
    del construction, briefing
    try:
        payload = _run_streamlit_operator_pass()
    except (ImportError, AttributeError, OSError, TypeError, ValueError, RuntimeError) as error:
        st.session_state["capital_intelligence_operator_status"] = {
            "status": "degraded",
            "error": str(error),
            "paper_only": True,
            "real_money_authorized": False,
        }
        st.warning(
            "The autonomous paper operator is temporarily unavailable. "
            f"No transaction was executed: {error}"
        )
        return

    st.session_state["capital_intelligence_operator_status"] = payload
    execution = payload.get("paper_execution", {})
    if not isinstance(execution, Mapping):
        return
    execution_identifier = execution.get("execution_identifier")
    previous_identifier = st.session_state.get(
        "capital_intelligence_last_rendered_execution_identifier"
    )
    if (
        execution.get("state") == "completed"
        and execution_identifier
        and execution_identifier != previous_identifier
    ):
        st.session_state[
            "capital_intelligence_last_rendered_execution_identifier"
        ] = execution_identifier
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
