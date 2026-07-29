"""Render-hosted authenticated Streamlit entrypoint with deployment identity."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

# Importing the authenticated entrypoint renders the complete application. Keeping the
# wrapper separate avoids changing local and Docker Compose entrypoint contracts.
import secure_app  # noqa: F401,E402


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
