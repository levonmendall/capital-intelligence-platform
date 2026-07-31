"""Render-hosted authenticated Streamlit entrypoint with deployment identity."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from production_smoke_test_ui import render_production_smoke_test
from secure_app import run_authenticated_app


principal = run_authenticated_app(configure_page=True)
release = (
    os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
    or os.getenv("RENDER_GIT_COMMIT")
    or "unknown"
).strip()
state_root = Path(
    os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
).expanduser()
render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()

with st.sidebar:
    st.divider()
    st.caption(
        "Persistent operating host · "
        f"build `{release[:12] if release else 'unknown'}`"
    )
    st.caption(f"State authority: `{state_root}`")
    if render_host:
        st.caption(f"Render service: `{render_host}`")

if (
    principal is not None
    and getattr(principal, "is_administrator", False)
    and st.session_state.get("production_smoke_test_open") is True
):

    @st.dialog("Production Smoke Test", width="large")
    def _production_smoke_test_dialog() -> None:
        render_production_smoke_test(principal)

    _production_smoke_test_dialog()
