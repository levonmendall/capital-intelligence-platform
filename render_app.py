"""Canonical Render-hosted Streamlit entrypoint."""

from __future__ import annotations

import functools
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import streamlit as st

import app_impl
import educational_market_briefing_ui
import environment_actionable_learning_refinement
import environment_driver_education_runtime
import environment_story_placement_refinement
import live_operating_console
import operating_intelligence_ui
import operating_status
import opportunity_funnel_ui_refinement
import opportunity_scan_resilience
import portfolio_first_ui_refinement
import public_event_recency_runtime
import secure_app
import surface_content_refinement
import surface_route_isolation_runtime
import today_development_card_format_runtime
import today_event_alignment_runtime
import today_story_retention_runtime
import ui_experience_refinement
import ui_refinement
from render_nonblocking_data import (
    get_mandate_details_nonblocking,
    get_portfolio_totals_nonblocking,
    get_trade_history_nonblocking,
    load_cio_operating_status_nonblocking,
    load_dashboard_data_nonblocking,
    load_decision_accountability_nonblocking,
    load_diagnostic_environment_nonblocking,
    load_journal_history_nonblocking,
    load_journal_latest_nonblocking,
    load_latest_theses_nonblocking,
    load_live_market_console_nonblocking,
    load_opportunity_scan_nonblocking,
    load_public_event_snapshot_nonblocking,
    prewarm_render_data,
)
from secure_app import DeploymentContext, create_streamlit_application


_LOGGER = logging.getLogger("capital_intelligence.render_surfaces")
_RENDER_SYNC_TARGET_ATTRIBUTE = "_capital_intelligence_render_sync_target"
_RENDER_SURFACE_NAMES = (
    "_render_today",
    "_render_environment",
    "_render_portfolio",
    "_render_history",
)


def _synchronous_renderer(renderer: Callable[..., Any]) -> Callable[..., Any]:
    """Return the explicit Render target or the callable beneath a fragment."""

    explicit_target = getattr(renderer, _RENDER_SYNC_TARGET_ATTRIBUTE, None)
    if callable(explicit_target):
        return explicit_target
    return getattr(renderer, "__wrapped__", renderer)


def _portfolio_first_sync_renderer(
    renderer: Callable[..., Any],
) -> Callable[..., Any]:
    """Preserve the Portfolio-first hierarchy after Render removes fragments.

    The Portfolio-first Streamlit fragment intentionally wraps the original
    Portfolio renderer so the remaining governed controls can be reused below
    the new opening. Streamlit copies the wrapped function's ``__wrapped__``
    attribute onto the fragment wrapper, so generic unwrapping resolves to the
    old renderer and silently skips the new opening. This explicit synchronous
    bridge calls the Portfolio-first helpers directly and retains the original
    renderer only for the lower, de-duplicated controls.
    """

    original = getattr(renderer, "__wrapped__", renderer)

    def render_portfolio(
        dependencies: object,
        *,
        principal: object | None,
    ) -> None:
        construction = app_impl._latest("portfolio_construction")
        briefing = app_impl._latest("daily_cio_briefing")
        mandate = dependencies.get_mandate_details(
            app_impl.CANONICAL_PORTFOLIO_CODE
        )
        if mandate is None:
            st.warning("The canonical paper portfolio is unavailable.")
            return

        st.markdown(
            portfolio_first_ui_refinement._CSS,
            unsafe_allow_html=True,
        )
        _nav, _cash, deployed = portfolio_first_ui_refinement._capital_structure(
            app_impl,
            mandate=mandate,
        )
        portfolio_first_ui_refinement._render_cio_report(
            app_impl,
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )
        portfolio_first_ui_refinement._render_remaining_portfolio(
            app_impl,
            original,
            dependencies,
            principal=principal,
        )

    return render_portfolio


def _log_slow_surface(surface_name: str, render_thread_id: int) -> None:
    frame = sys._current_frames().get(render_thread_id)
    stack = (
        "render thread frame unavailable"
        if frame is None
        else "".join(traceback.format_stack(frame))
    )
    _LOGGER.warning(
        "primary Streamlit surface render is still running after 8 seconds: %s\n"
        "render_thread_stack:\n%s",
        surface_name,
        stack,
    )


def _guarded_renderer(
    surface_name: str,
    renderer: Callable[..., Any],
) -> Callable[..., Any]:
    """Render one surface synchronously and never leave a silent blank page."""

    target = _synchronous_renderer(renderer)

    @functools.wraps(target, updated=())
    def guarded(*args: Any, **kwargs: Any) -> Any:
        started_at = time.monotonic()
        render_thread_id = threading.get_ident()
        _LOGGER.info("primary Streamlit surface render started: %s", surface_name)
        slow_warning = threading.Timer(
            8.0,
            _log_slow_surface,
            args=(surface_name, render_thread_id),
        )
        slow_warning.daemon = True
        slow_warning.start()
        try:
            return target(*args, **kwargs)
        except Exception as error:
            _LOGGER.exception(
                "primary Streamlit surface failed to render: %s",
                surface_name,
            )
            st.error(
                "This surface could not be rendered. The application remains online "
                "and the failure has been recorded for diagnosis."
            )
            st.caption(
                f"Surface: {surface_name} · Error class: {type(error).__name__}"
            )
            return None
        finally:
            slow_warning.cancel()
            _LOGGER.info(
                "primary Streamlit surface render completed: %s duration_seconds=%.3f",
                surface_name,
                time.monotonic() - started_at,
            )

    guarded._capital_intelligence_guarded_surface = True  # type: ignore[attr-defined]
    guarded._capital_intelligence_fragment_removed = (  # type: ignore[attr-defined]
        target is not renderer
    )
    return guarded


def prepare_render_data_runtime() -> None:
    """Keep all provider, file, and operating-store latency off the UI thread."""

    # app_impl resolves these globals when it creates session dependencies and
    # renders the four surfaces. None of these display adapters can mutate or
    # authorize the canonical operating stores.
    app_impl._latest = load_journal_latest_nonblocking
    app_impl._history = load_journal_history_nonblocking
    app_impl._latest_theses = load_latest_theses_nonblocking
    app_impl._diagnostic_environment = load_diagnostic_environment_nonblocking
    app_impl.get_portfolio_totals = get_portfolio_totals_nonblocking
    app_impl.get_mandate_details = get_mandate_details_nonblocking
    app_impl.get_trade_history = get_trade_history_nonblocking
    app_impl.load_cio_operating_status = load_cio_operating_status_nonblocking
    app_impl.load_live_market_console = load_live_market_console_nonblocking
    app_impl.load_dashboard_data = load_dashboard_data_nonblocking

    # The concise educational surfaces resolve these functions through the
    # operating_intelligence_ui module at call time.
    operating_intelligence_ui.get_mandate_details = get_mandate_details_nonblocking
    operating_intelligence_ui.load_live_market_console = (
        load_live_market_console_nonblocking
    )
    operating_intelligence_ui.load_dashboard_data = load_dashboard_data_nonblocking
    operating_intelligence_ui.load_public_event_snapshot = (
        load_public_event_snapshot_nonblocking
    )
    operating_intelligence_ui.load_opportunity_scan = (
        load_opportunity_scan_nonblocking
    )
    operating_intelligence_ui.load_decision_accountability = (
        load_decision_accountability_nonblocking
    )

    # Other active presentation helpers import these modules directly.
    educational_market_briefing_ui.load_public_event_snapshot = (
        load_public_event_snapshot_nonblocking
    )
    operating_status.load_cio_operating_status = (
        load_cio_operating_status_nonblocking
    )
    live_operating_console.load_live_market_console = (
        load_live_market_console_nonblocking
    )

    prewarm_render_data()


def prepare_render_surface_runtime() -> None:
    """Replace auto-refresh fragments with stable full-run renderers on Render."""

    for attribute_name in _RENDER_SURFACE_NAMES:
        renderer = getattr(app_impl, attribute_name)
        if getattr(renderer, "_capital_intelligence_guarded_surface", False):
            continue
        if attribute_name == "_render_portfolio":
            setattr(
                renderer,
                _RENDER_SYNC_TARGET_ATTRIBUTE,
                _portfolio_first_sync_renderer(renderer),
            )
        guarded = _guarded_renderer(attribute_name.removeprefix("_render_"), renderer)
        if not getattr(guarded, "_capital_intelligence_fragment_removed", False):
            _LOGGER.warning(
                "surface renderer did not expose a fragment wrapper: %s",
                attribute_name,
            )
        setattr(app_impl, attribute_name, guarded)


def deployment_context_from_environment() -> DeploymentContext:
    release = (
        os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown"
    ).strip()
    return DeploymentContext(
        release=release,
        state_root=Path(
            os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        ).expanduser(),
        render_host=os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip(),
    )


def main() -> None:
    public_event_recency_runtime.install(educational_market_briefing_ui)
    prepare_render_data_runtime()
    today_event_alignment_runtime.install(
        educational_market_briefing_ui,
        operating_intelligence_ui,
        environment_story_placement_refinement,
    )
    today_development_card_format_runtime.install(
        environment_story_placement_refinement
    )
    environment_driver_education_runtime.install(
        environment_story_placement_refinement
    )
    environment_actionable_learning_refinement.install(
        environment_story_placement_refinement
    )
    opportunity_scan_resilience.install()
    ui_refinement.install(app_impl, secure_app)
    ui_experience_refinement.install(app_impl)
    opportunity_funnel_ui_refinement.install(app_impl)
    surface_content_refinement.install(app_impl)
    environment_story_placement_refinement.install(app_impl)
    today_story_retention_runtime.install(
        app_impl,
        educational_market_briefing_ui,
        operating_intelligence_ui,
        environment_story_placement_refinement,
    )
    surface_route_isolation_runtime.install(
        app_impl,
        environment_story_placement_refinement,
    )
    prepare_render_surface_runtime()
    create_streamlit_application(
        deployment=deployment_context_from_environment()
    )


if __name__ == "__main__":
    main()
