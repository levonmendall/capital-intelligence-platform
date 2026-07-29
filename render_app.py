"""Render-hosted authenticated Streamlit entrypoint with deployment identity."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from production_smoke_test_ui import render_production_smoke_test


# Execute the authenticated entrypoint from source on every Streamlit rerun. A normal
# import would remain cached and could prevent navigation, authentication, or refreshed
# operating data from rendering after the first session pass. Retain the execution
# globals so the Render wrapper can apply administrator-only operational controls to the
# authenticated principal without changing the four primary application screens.
secure_source_path = Path(__file__).with_name("secure_app.py")
secure_source = secure_source_path.read_text(encoding="utf-8")
secure_globals = {
    "__name__": "__main__",
    "__file__": str(secure_source_path),
}
exec(
    compile(secure_source, str(secure_source_path), "exec"),
    secure_globals,
)
principal = secure_globals.get("principal")

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
    if principal is not None and getattr(principal, "is_administrator", False):
        if st.button("Production smoke test", key="open-production-smoke-test"):
            st.session_state["production_smoke_test_open"] = True

if (
    principal is not None
    and getattr(principal, "is_administrator", False)
    and st.session_state.get("production_smoke_test_open") is True
):

    @st.dialog("Production Smoke Test", width="large")
    def _production_smoke_test_dialog() -> None:
        render_production_smoke_test(principal)

    _production_smoke_test_dialog()
