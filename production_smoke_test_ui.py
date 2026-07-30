"""Administrator-only Streamlit controls for the Render production smoke test."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import streamlit as st

from api.config import ApiSettings
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
    "governed_paper_outcome_recorded": "Comparative CIO outcome or completed paper execution is recorded",
    "encrypted_backup_healthy": "Encrypted backup is healthy",
}

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"
)


def _sanitized_failure_detail(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    detail = value.strip()[:1000]
    return _SECRET_ASSIGNMENT.sub(r"\1=[REDACTED]", detail)


def _canonical_cycle_diagnostic(result: dict[str, object]) -> dict[str, object] | None:
    heartbeat = result.get("heartbeat")
    cycle_key = heartbeat.get("cycle_key") if isinstance(heartbeat, dict) else None
    if not isinstance(cycle_key, str) or not cycle_key.strip():
        return None

    try:
        settings = ApiSettings.from_env()
        database = settings.alert_database or settings.snapshot_database.with_name("alerts.db")
    except (OSError, TypeError, ValueError):
        return None
    database = Path(database)
    if not database.is_file():
        return None

    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT status, attempts, next_attempt_at, error, updated_at
                FROM scheduled_cycles
                WHERE cycle_key = ?
                """,
                (cycle_key,),
            ).fetchone()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return None
    if row is None:
        return None

    return {
        "cycle_key": cycle_key,
        "status": row["status"],
        "attempts": int(row["attempts"]),
        "next_attempt_at": row["next_attempt_at"],
        "updated_at": row["updated_at"],
        "failure_detail": _sanitized_failure_detail(row["error"]),
        "paper_only": True,
        "real_money_authorized": False,
    }


def _render_result(result: dict[str, object]) -> None:
    result = dict(result)
    diagnostic = _canonical_cycle_diagnostic(result)
    if diagnostic is not None:
        result["canonical_cio_cycle"] = diagnostic

    passed = result.get("overall_status") == "PASS"
    if passed:
        st.success("All five production runtime and decision-readiness checks passed.")
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

    if diagnostic is not None and diagnostic.get("status") == "failed":
        detail = diagnostic.get("failure_detail") or "No persisted failure detail is available."
        st.error(f"Canonical CIO cycle failed closed: {detail}")
        st.caption(
            "The failed cycle remains paper-only. The next scheduled retry is "
            f"{diagnostic.get('next_attempt_at') or 'not recorded'}."
        )

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
