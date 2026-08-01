"""Keep the Today process lens visible at the top of the surface.

This presentation adapter moves the existing Observe / Explain / Resolve / Act
story out of its bottom-page expander. It changes layout only and does not read,
score, qualify, size, construct, execute, or authorize an investment decision.
"""

from __future__ import annotations

from contextlib import nullcontext
from functools import wraps
from types import ModuleType
from typing import Sequence


_INSTALLED_STATE_KEY = "_capital_intelligence_today_story_placement_installed"
_OLD_EXPANDER_LABEL = "How the Today surface works"
_TODAY_STEPS: tuple[tuple[str, str], ...] = (
    ("Observe", "Continuously monitor markets, economics, and material events."),
    ("Explain", "Translate developments into simple investment implications."),
    ("Resolve", "Judge whether the evidence changes the governed portfolio."),
    ("Act", "Move capital only after decision and implementation controls clear."),
)


def install(app_impl: ModuleType) -> None:
    """Install one idempotent, presentation-only Today layout refinement."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_header = app_impl.render_app_header
    original_story = app_impl.surface_story
    original_expander = app_impl.st.expander

    @wraps(original_header)
    def render_app_header(active_page: str) -> None:
        original_header(active_page)
        if active_page == "Today":
            original_story("Today", _TODAY_STEPS)

    @wraps(original_story)
    def surface_story(
        active_page: str,
        steps: Sequence[tuple[str, str]],
    ) -> None:
        # The Today story is rendered immediately after the surface heading.
        # Suppress only the legacy bottom-of-page call; other surface stories
        # retain their existing placement and behavior.
        if active_page == "Today":
            return
        original_story(active_page, steps)

    @wraps(original_expander)
    def expander(label: str, *args: object, **kwargs: object):
        # Do not render an empty legacy dropdown after its story has moved.
        if label == _OLD_EXPANDER_LABEL:
            return nullcontext()
        return original_expander(label, *args, **kwargs)

    app_impl.render_app_header = render_app_header
    app_impl.surface_story = surface_story
    app_impl.st.expander = expander
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
