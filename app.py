"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

import app_impl
import decision_pulse_ui_refinement
import opportunity_funnel_ui_refinement
import opportunity_scan_resilience
import secure_app
import ui_experience_refinement
import ui_refinement
from secure_app import create_streamlit_application


def main() -> None:
    opportunity_scan_resilience.install()
    ui_refinement.install(app_impl, secure_app)
    ui_experience_refinement.install(app_impl)
    decision_pulse_ui_refinement.install(app_impl)
    opportunity_funnel_ui_refinement.install(app_impl)
    create_streamlit_application()


if __name__ == "__main__":
    main()
