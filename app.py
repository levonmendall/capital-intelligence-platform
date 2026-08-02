"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

import app_impl
import decision_pulse_ui_refinement
import environment_story_placement_refinement
import opportunity_funnel_ui_refinement
import opportunity_scan_resilience
import public_event_recency_runtime
import secure_app
import surface_content_refinement
import today_development_card_format_runtime
import today_event_alignment_runtime
import ui_experience_refinement
import ui_refinement
from secure_app import create_streamlit_application


def main() -> None:
    public_event_recency_runtime.install()
    today_event_alignment_runtime.install()
    today_development_card_format_runtime.install()
    opportunity_scan_resilience.install()
    ui_refinement.install(app_impl, secure_app)
    ui_experience_refinement.install(app_impl)
    decision_pulse_ui_refinement.install(app_impl)
    opportunity_funnel_ui_refinement.install(app_impl)
    surface_content_refinement.install(app_impl)
    environment_story_placement_refinement.install(app_impl)
    create_streamlit_application()


if __name__ == "__main__":
    main()
