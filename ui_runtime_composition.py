"""Shared Streamlit presentation composition for local and Render entrypoints."""
from __future__ import annotations

import all_market_certification_ui
import app_impl
import decision_pulse_ui_refinement
import educational_market_briefing_ui
import environment_mobile_clarity_runtime
import environment_story_placement_refinement
import history_ui_refinement
import operating_intelligence_ui
import opportunity_funnel_ui_refinement
import portfolio_evidence_accumulation_ui
import portfolio_only_runtime
import portfolio_ui_refinement
import secure_app
import surface_content_refinement
import surface_route_isolation_runtime
import today_story_retention_runtime
import today_trust_ui_runtime
import ui_experience_refinement
import ui_refinement


def install_canonical_surface_composition(
    *,
    include_decision_pulse: bool,
    include_history_refinement: bool,
    replace_story_fragments: bool,
) -> None:
    """Install shared presentation refinements in one deterministic order."""

    ui_refinement.install(app_impl, secure_app)
    ui_experience_refinement.install(app_impl)
    if include_decision_pulse:
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
        replace_story_fragments=replace_story_fragments,
    )
    portfolio_ui_refinement.install(app_impl)
    if include_history_refinement:
        history_ui_refinement.install(app_impl)

    # Portfolio-only presentation is deliberately installed last so the complete
    # underlying surfaces stay available to code/tests while Render exposes only the
    # canonical portfolio during the operating phase. Evidence accumulation replaces
    # only the read-only asset-class presentation, then certification provenance wraps
    # that final renderer so both surfaces share one exact-release envelope.
    portfolio_only_runtime.install(app_impl, secure_app)
    portfolio_evidence_accumulation_ui.install(portfolio_only_runtime)
    all_market_certification_ui.install(portfolio_only_runtime)


__all__ = ["install_canonical_surface_composition"]
