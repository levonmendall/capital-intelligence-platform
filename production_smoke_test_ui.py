"""Administrator-only Streamlit controls for the Render production smoke test."""

from __future__ import annotations

import json

import streamlit as st

from production_smoke_test import (
    capture_pre_restart_snapshot,
    create_encrypted_backup_now,
    evaluate_runtime_smoke_test,
    load_pre_restart_snapshot,
)


_CHECK_LABELS = {
    "persistent_state_survived_restart": "Persistent state survived restart",
    "operator_heartbeat_and_cio_cycle_current": "Heartbeat and CIO cycle are current",
    "provider_market_observations_current": "Provider observations are current",
    "governed_paper_outcome_recorded": "Governed paper outcome is recorded",
    "encrypted_backup_healthy": "Encrypted backup is healthy",
}


def _render_result(result: dict[str, object]) -> None:
    passed = result.get("overall_status") == "PASS"
    if passed:
        st.success("All five production runtime checks passed.")
    else:
        st.warning(
            "The verification is not yet a full pass. Review the failed checks below; "
            "no trading control was bypassed."
        )

    checks = result.get("checks")
    rows = []
    if isinstance(checks, dict):
        rows = [
            {
                "Check": _CHECK_LABELS.get(name, name.replace("_", " ").title()),
                "Result": "PASS" if value is True else "REVIEW",
            }
            for name, value in checks.items()
        ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Sanitized verification evidence", expanded=not passed):
        st.json(result)
    st.download_button(
        "Download verification JSON",
        data=json.dumps(result, indent=2, sort_keys=True) + "\n",
        file_name="production-runtime-smoke-result.json",
        mime="application/json",
    )


def render_production_smoke_test(principal) -> None:
    if not getattr(principal, "is_administrator", False):
        st.error("Administrator authorization is required.")
        return

    st.subheader("Production Smoke Test")
    st.caption(
        "Administrator-only verification of Render persistence, the CIO operator, "
        "provider evidence, governed paper outcomes, and encrypted backups."
    )
    st.info(
        "This page does not display credentials, alter the portfolio, create a CIO "
        "recommendation, or authorize real-money trading."
    )

    if st.button("Close production smoke test"):
        st.session_state["production_smoke_test_open"] = False
        st.rerun()

    st.divider()
    st.markdown("#### 1. Capture the pre-restart state")
    existing = load_pre_restart_snapshot()
    if existing is not None:
        st.caption(f"Current snapshot captured {existing.get('captured_at', 'at an unknown time')}.")
    if st.button("Capture pre-restart snapshot", type="primary"):
        try:
            snapshot = capture_pre_restart_snapshot()
        except (OSError, TypeError, ValueError) as error:
            st.error(f"Snapshot capture failed: {type(error).__name__}")
        else:
            st.success(
                "The persistent portfolio and journal baseline was captured. Restart "
                "the Render service, wait until it is Live, then return to this page."
            )
            st.json(
                {
                    "captured_at": snapshot.get("captured_at"),
                    "release": snapshot.get("release"),
                    "databases": snapshot.get("databases"),
                    "paper_only": True,
                    "real_money_authorized": False,
                }
            )

    st.markdown("#### 2. Restart the Render service")
    st.write(
        "Use **Render Dashboard → capital-intelligence-platform → Manual Deploy → "
        "Restart service**. Wait for the service and `/_stcore/health` to report healthy, "
        "then sign back in and reopen this dialog."
    )

    st.markdown("#### 3. Verify the five runtime checks")
    if st.button("Run post-restart verification", type="primary"):
        try:
            result = evaluate_runtime_smoke_test()
        except (OSError, TypeError, ValueError) as error:
            st.error(f"Runtime verification failed: {type(error).__name__}")
        else:
            _render_result(result)

    st.markdown("#### Encrypted backup control")
    st.caption(
        "Use this only when the verification reports that no recent encrypted backup "
        "is available. It creates a backup of the currently activated canonical authorities."
    )
    if st.button("Create encrypted backup now"):
        result = create_encrypted_backup_now()
        if result.get("status") == "completed":
            st.success("Encrypted backup completed and was recorded on persistent storage.")
        else:
            st.error("Encrypted backup creation was blocked. Review Render logs.")
        st.json(result)


__all__ = ["render_production_smoke_test"]
