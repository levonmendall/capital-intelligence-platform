"""Authenticated Streamlit controls for exact paper-implementation consent."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from governance.paper_decision_approval import (
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
)
from portfolio.constants import CANONICAL_PORTFOLIO_CODE


def _approval_database() -> Path:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE")
    return Path(configured).expanduser() if configured else data_dir / "paper_test_governance.db"


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def render_paper_decision_controls(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    principal: object | None,
) -> None:
    """Render consent for the exact displayed decision and construction.

    Approval records intent only. The paper execution worker must separately pass
    provider, launch, runtime-control, portfolio-integrity, quote, and
    reconciliation gates before any simulated fill is recorded.
    """

    if not isinstance(construction, Mapping):
        return
    trades = construction.get("trades")
    if not isinstance(trades, list) or not trades:
        return
    if construction.get("blocks"):
        st.warning(
            "This implementation is blocked and cannot be approved for paper execution."
        )
        return

    decision_identifier = (
        None
        if not isinstance(briefing, Mapping)
        else _identifier(briefing.get("decision_identifier"))
    )
    construction_identifier = _identifier(construction.get("request_identifier"))
    if decision_identifier is None or construction_identifier is None:
        st.warning(
            "Paper approval is unavailable because the decision or construction identity is incomplete."
        )
        return

    construction_hash = canonical_construction_sha256(construction)
    store = SQLitePaperDecisionApprovalStore(_approval_database())
    store.verify_integrity()
    latest = store.latest(decision_identifier, construction_identifier)

    st.markdown("### Paper implementation approval")
    st.caption(
        "Approval applies only to the exact proposed transactions shown above. "
        "It does not authorize real money or bypass launch and risk controls."
    )

    if principal is None:
        st.info(
            "Open the authenticated application to approve or decline this paper implementation."
        )
        return
    can_manage = getattr(principal, "can_access_mandate", None)
    if not callable(can_manage) or not can_manage(
        CANONICAL_PORTFOLIO_CODE,
        write=True,
    ):
        st.info("Your account has read-only access to this portfolio.")
        return

    now = datetime.now(timezone.utc)
    if latest is not None:
        label = latest.state.value.replace("_", " ").title()
        if latest.state is PaperDecisionApprovalState.EXECUTED:
            st.success(
                f"Paper implementation executed: {latest.execution_identifier}."
            )
            return
        if latest.active_at(now):
            st.success(
                "Approved and queued for paper execution. The worker will act only "
                "while every controlled-paper authority remains active."
            )
            st.caption(f"Approval expires {latest.expires_at.isoformat()}.")
            if st.button(
                "Revoke paper approval",
                key=f"revoke-paper-{construction_hash}",
                use_container_width=True,
            ):
                store.conclude(
                    state=PaperDecisionApprovalState.REVOKED,
                    decision_identifier=decision_identifier,
                    construction_identifier=construction_identifier,
                    construction_sha256=construction_hash,
                    actor_user_id=str(principal.user_id),
                    actor_session_id=str(principal.session_id),
                    occurred_at=now,
                    rationale="User revoked the pending paper implementation.",
                )
                st.rerun()
            return
        st.info(f"Latest paper decision: {label}.")

    rationale = st.text_input(
        "Decision note",
        value="I support the exact displayed paper implementation.",
        key=f"paper-rationale-{construction_hash}",
        max_chars=500,
    )
    approve_column, decline_column = st.columns(2)
    with approve_column:
        approve = st.button(
            "Approve for paper execution",
            key=f"approve-paper-{construction_hash}",
            type="primary",
            use_container_width=True,
        )
    with decline_column:
        decline = st.button(
            "Decline implementation",
            key=f"decline-paper-{construction_hash}",
            use_container_width=True,
        )

    if approve:
        store.approve(
            decision_identifier=decision_identifier,
            construction_identifier=construction_identifier,
            construction_sha256=construction_hash,
            actor_user_id=str(principal.user_id),
            actor_session_id=str(principal.session_id),
            occurred_at=now,
            rationale=rationale,
        )
        st.rerun()
    if decline:
        store.conclude(
            state=PaperDecisionApprovalState.DECLINED,
            decision_identifier=decision_identifier,
            construction_identifier=construction_identifier,
            construction_sha256=construction_hash,
            actor_user_id=str(principal.user_id),
            actor_session_id=str(principal.session_id),
            occurred_at=now,
            rationale=rationale or "User declined the paper implementation.",
        )
        st.rerun()


__all__ = ["render_paper_decision_controls"]
