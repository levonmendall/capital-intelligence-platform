"""Authenticated controls and status for exact canonical paper implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import streamlit as st

from governance.paper_decision_approval import (
    PaperDecisionApprovalState,
    SQLitePaperDecisionApprovalStore,
    canonical_construction_sha256,
)
from paper_execution_runtime import (
    PaperExecutionMode,
    approval_database,
    attempt_paper_execution,
    paper_execution_mode,
)
from portfolio.constants import CANONICAL_PORTFOLIO_CODE


def _identifier(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _can_manage(principal: object | None) -> bool:
    if principal is None:
        return False
    can_manage = getattr(principal, "can_access_mandate", None)
    return bool(
        callable(can_manage)
        and can_manage(CANONICAL_PORTFOLIO_CODE, write=True)
    )


@st.fragment(run_every="5s")
def render_paper_decision_controls(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    principal: object | None,
) -> None:
    """Show paper state while preserving a human pause for automatic operation."""

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

    mode = paper_execution_mode()
    construction_hash = canonical_construction_sha256(construction)
    store = SQLitePaperDecisionApprovalStore(approval_database())
    store.verify_integrity()
    now = datetime.now(timezone.utc)
    attempt = attempt_paper_execution(
        construction=construction,
        briefing=briefing,
        now=now,
        mode=mode,
    )
    latest = store.latest(decision_identifier, construction_identifier)

    st.markdown("### Paper implementation")
    if mode is PaperExecutionMode.AUTOMATIC:
        st.caption(
            "Autonomous paper mode authorizes only this exact canonical construction. "
            "It cannot bypass market data, eligibility, portfolio, liquidity, cost, "
            "or reconciliation controls and never authorizes real money."
        )
    elif mode is PaperExecutionMode.MANUAL:
        st.caption(
            "Manual mode requires approval of the exact proposed transactions. "
            "Approval never authorizes real money or a live brokerage order."
        )
    else:
        st.warning(attempt.detail)
        return

    if attempt.completed:
        toast_key = f"paper-execution-complete:{construction_hash}"
        if not st.session_state.get(toast_key, False):
            st.toast("Paper transaction completed.", icon="✅")
            st.session_state[toast_key] = True
        st.success(
            "Paper implementation executed"
            + (
                "."
                if attempt.execution_identifier is None
                else f": {attempt.execution_identifier}."
            )
        )
        return

    if attempt.state == "blocked":
        st.warning(f"Paper execution is blocked: {attempt.detail}")
    elif attempt.state == "held":
        st.info(f"Paper execution is held: {attempt.detail}")
    elif attempt.state == "paused":
        st.info(attempt.detail)
    elif mode is PaperExecutionMode.AUTOMATIC:
        st.success("Autonomous paper execution is active for this construction.")
    else:
        st.info(attempt.detail)

    if attempt.attempted_at is not None:
        st.caption(
            "Last execution check: "
            f"{attempt.attempted_at.astimezone(timezone.utc).isoformat()}"
        )

    can_manage = _can_manage(principal)
    if mode is PaperExecutionMode.AUTOMATIC:
        if not can_manage:
            st.caption(
                "A portfolio manager can pause or resume autonomous execution for "
                "this exact construction."
            )
            return
        if latest is not None and latest.state in {
            PaperDecisionApprovalState.DECLINED,
            PaperDecisionApprovalState.REVOKED,
        }:
            if st.button(
                "Resume autonomous paper execution",
                key=f"resume-paper-{construction_hash}",
                type="primary",
                use_container_width=True,
            ):
                store.approve(
                    decision_identifier=decision_identifier,
                    construction_identifier=construction_identifier,
                    construction_sha256=construction_hash,
                    actor_user_id=str(principal.user_id),
                    actor_session_id=str(principal.session_id),
                    occurred_at=now,
                    rationale=(
                        "Portfolio manager resumed autonomous paper execution for "
                        "the exact displayed construction."
                    ),
                )
                st.rerun()
            return
        if st.button(
            "Pause this paper implementation",
            key=f"pause-paper-{construction_hash}",
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
                rationale=(
                    "Portfolio manager paused autonomous execution for the exact "
                    "displayed construction."
                ),
            )
            st.rerun()
        return

    # Manual compatibility mode.
    if not can_manage:
        st.info("Your account has read-only access to this portfolio.")
        return
    if latest is not None and latest.active_at(now):
        st.success("Approved and queued for exact paper execution.")
        if latest.expires_at is not None:
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
