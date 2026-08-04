"""Prevent one primary Streamlit surface from rendering inside another.

Streamlit fragments can outlive the full-page run that created them. A delayed
fragment refresh must therefore verify that its surface still owns the selected
navigation route before emitting any UI. Render also removes fragment wrappers
for stability, so this module publishes explicit synchronous targets for Today
and Environment instead of relying on copied ``__wrapped__`` metadata.

Presentation only: this module cannot read new evidence, change a CIO decision,
size a position, construct a portfolio, execute a trade, or authorize real money.
"""

from __future__ import annotations

import logging
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Sequence

import streamlit as st


_LOGGER = logging.getLogger("capital_intelligence.surface_routes")
_ACTIVE_SURFACE_KEY = "_capital_intelligence_active_primary_surface"
_RENDER_SYNC_TARGET_ATTRIBUTE = "_capital_intelligence_render_sync_target"
_NAVIGATION_WRAPPER_ATTRIBUTE = "_capital_intelligence_surface_route_navigation"
_STORY_GUARD_ATTRIBUTE = "_capital_intelligence_surface_route_guard"
_STORY_ORIGINAL_ATTRIBUTE = "_capital_intelligence_surface_route_original"
_PRIMARY_SURFACES = frozenset({"Today", "Environment", "Portfolio", "History"})
_NAVIGATION_STATE_KEYS = (
    "primary_surface_navigation_portfolio_first_v1",
    "primary_surface_navigation_v2",
)


def _normalized_surface(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if candidate in _PRIMARY_SURFACES else ""


def active_surface() -> str:
    """Return the currently selected primary surface, when known."""

    active = _normalized_surface(st.session_state.get(_ACTIVE_SURFACE_KEY))
    if active:
        return active
    for key in _NAVIGATION_STATE_KEYS:
        active = _normalized_surface(st.session_state.get(key))
        if active:
            return active
    return ""


def _install_navigation_tracking(app_impl: ModuleType) -> None:
    current = app_impl.render_navigation
    if getattr(current, _NAVIGATION_WRAPPER_ATTRIBUTE, False):
        return

    @wraps(current, updated=())
    def render_navigation(options: Sequence[str]) -> tuple[str, bool]:
        page, visible = current(list(options))
        normalized = _normalized_surface(page)
        if normalized:
            st.session_state[_ACTIVE_SURFACE_KEY] = normalized
        return page, visible

    setattr(render_navigation, _NAVIGATION_WRAPPER_ATTRIBUTE, True)
    app_impl.render_navigation = render_navigation


def _guard_story_renderer(
    story_ui: ModuleType,
    attribute_name: str,
    expected_surface: str,
) -> Callable[[ModuleType, object], Any]:
    current = getattr(story_ui, attribute_name)
    if (
        getattr(current, _STORY_GUARD_ATTRIBUTE, "") == expected_surface
        and callable(current)
    ):
        return current

    original = getattr(current, _STORY_ORIGINAL_ATTRIBUTE, current)
    if not callable(original):
        raise TypeError(f"{attribute_name} is not callable")

    @wraps(original, updated=())
    def guarded(active_app: ModuleType, dependencies: object) -> Any:
        selected = active_surface()
        if selected and selected != expected_surface:
            _LOGGER.warning(
                "suppressed stale primary-surface render expected=%s selected=%s",
                expected_surface,
                selected,
            )
            return None
        return original(active_app, dependencies)

    setattr(guarded, _STORY_GUARD_ATTRIBUTE, expected_surface)
    setattr(guarded, _STORY_ORIGINAL_ATTRIBUTE, original)
    setattr(story_ui, attribute_name, guarded)
    return guarded


def _sync_target(
    app_impl: ModuleType,
    story_ui: ModuleType,
    attribute_name: str,
    expected_surface: str,
) -> Callable[[object], Any]:
    def render(dependencies: object) -> Any:
        renderer = getattr(story_ui, attribute_name)
        selected = active_surface()
        if selected and selected != expected_surface:
            _LOGGER.warning(
                "suppressed mismatched Render target expected=%s selected=%s",
                expected_surface,
                selected,
            )
            return None
        return renderer(app_impl, dependencies)

    render.__name__ = f"render_{expected_surface.lower()}_synchronously"
    setattr(render, _STORY_GUARD_ATTRIBUTE, expected_surface)
    return render


def install(
    app_impl: ModuleType,
    story_ui: ModuleType,
    *,
    replace_story_fragments: bool = False,
) -> None:
    """Install navigation tracking and strict Today/Environment ownership.

    ``replace_story_fragments`` is used by the local entrypoint so Today and
    Environment render synchronously there as well. Render keeps its existing
    guarded full-page bridge and consumes the explicit target attributes.
    """

    _install_navigation_tracking(app_impl)
    _guard_story_renderer(story_ui, "_render_today", "Today")
    _guard_story_renderer(story_ui, "_render_environment", "Environment")

    today_target = _sync_target(
        app_impl,
        story_ui,
        "_render_today",
        "Today",
    )
    environment_target = _sync_target(
        app_impl,
        story_ui,
        "_render_environment",
        "Environment",
    )

    if replace_story_fragments:
        app_impl._render_today = today_target
        app_impl._render_environment = environment_target
        return

    setattr(
        app_impl._render_today,
        _RENDER_SYNC_TARGET_ATTRIBUTE,
        today_target,
    )
    setattr(
        app_impl._render_environment,
        _RENDER_SYNC_TARGET_ATTRIBUTE,
        environment_target,
    )


__all__ = ["active_surface", "install"]
