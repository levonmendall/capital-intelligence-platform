"""Canonical local Streamlit entrypoint."""

from __future__ import annotations

import app_impl
import decision_pulse_ui_refinement
import educational_market_briefing_ui
import environment_mobile_clarity_runtime
import environment_story_placement_refinement
import operating_intelligence_ui
import opportunity_funnel_ui_refinement
import opportunity_scan_resilience
import portfolio_ui_refinement
import public_event_recency_runtime
import secure_app
import surface_content_refinement
import surface_route_isolation_runtime
import today_event_alignment_runtime
import today_story_retention_runtime
import today_trust_ui_runtime
import ui_experience_refinement
import ui_refinement
from secure_app import create_streamlit_application


def main() -> None:
    public_event_recency_runtime.install()
    today_event_alignment_runtime.install()
    opportunity_scan_resilience.install()
    ui_refinement.install(app_impl, secure_app)
    ui_experience_refinement.install(app_impl)
    decision_pulse_ui_refinement.install(app_impl)
    opportunity_funnel_ui_refinement.install(app_impl)
    surface_content_refinement.install(app_impl)
    environment_story_placement_refinement.install(app_impl)
    environment_mobile_clarity_runtime.install(environment_story_placement_refinement)
    today_story_retention_runtime.install(
        app_impl,
        educational_market_briefing_ui,
        operating_intelligence_ui,
        environment_story_placement_refinement,
    )
    today_trust_ui_runtime.install(
        app_impl,
        educational_market_briefing_ui,
        operating_intelligence_ui,
        environment_story_placement_refinement,
    )
    surface_route_isolation_runtime.install(
        app_impl,
        environment_story_placement_refinement,
        replace_story_fragments=True,
    )
    # Install last so Portfolio remains a single, presentation-only source of truth.
    portfolio_ui_refinement.install(app_impl)
    create_streamlit_application()


if __name__ == "__main__":
    main()
