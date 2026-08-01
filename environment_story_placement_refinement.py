"""Keep the Environment process lens visible and horizontally aligned.

This presentation adapter moves the existing Environment process story out of its
bottom-page expander and places it immediately below the Environment surface
heading. The horizontal card treatment is scoped to Environment so the separately
managed Today layout can evolve without conflict.
"""

from __future__ import annotations

from contextlib import nullcontext
from functools import wraps
from types import ModuleType
from typing import Sequence


_INSTALLED_STATE_KEY = "_capital_intelligence_environment_story_placement_installed"
_OLD_EXPANDER_LABEL = "How the Environment surface works"
_ENVIRONMENT_STEPS: tuple[tuple[str, str], ...] = (
    ("Measure", "Read growth, inflation, policy, credit, and liquidity."),
    ("Classify", "Describe the regime without creating a trade signal."),
    ("Confirm", "Compare macro conditions with cross-asset behavior."),
    ("Monitor", "Identify what would change the classification."),
)

_ENVIRONMENT_HORIZONTAL_STYLE = """
<style>
.surface-story.story-environment {
    grid-template-columns: minmax(9rem, .82fr) repeat(4, minmax(9rem, 1fr)) !important;
    gap: .62rem !important;
    overflow-x: auto !important;
    overscroll-behavior-x: contain;
    scroll-snap-type: x proximity;
    scrollbar-width: thin;
    -webkit-overflow-scrolling: touch;
}
.surface-story.story-environment .story-lead {
    grid-column: auto !important;
    min-width: 9rem;
}
.surface-story.story-environment .story-step {
    min-width: 9rem;
    min-height: 5.3rem !important;
    border-radius: 16px !important;
    display: block !important;
    scroll-snap-align: start;
}
.surface-story.story-environment .story-step::after {
    inset: auto 0 0 0 !important;
    width: auto !important;
    height: 2px !important;
    background: linear-gradient(
        90deg,
        var(--surface-accent),
        var(--surface-accent-2),
        transparent
    ) !important;
}
@media (max-width: 760px) {
    .surface-story.story-environment {
        grid-template-columns: minmax(7.4rem, .72fr) repeat(4, minmax(10rem, 1fr)) !important;
        gap: .5rem !important;
        padding: .55rem !important;
    }
    .surface-story.story-environment .story-lead {
        min-width: 7.4rem;
        padding: .64rem .66rem !important;
    }
    .surface-story.story-environment .story-step {
        min-width: 10rem;
        min-height: 6.9rem !important;
        padding: .72rem .78rem !important;
    }
}
</style>
"""


def install(app_impl: ModuleType) -> None:
    """Install one idempotent, presentation-only Environment layout refinement."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_header = app_impl.render_app_header
    original_story = app_impl.surface_story
    original_expander = app_impl.st.expander

    @wraps(original_header)
    def render_app_header(active_page: str) -> None:
        original_header(active_page)
        if active_page == "Environment":
            app_impl.st.markdown(
                _ENVIRONMENT_HORIZONTAL_STYLE,
                unsafe_allow_html=True,
            )
            original_story("Environment", _ENVIRONMENT_STEPS)

    @wraps(original_story)
    def surface_story(
        active_page: str,
        steps: Sequence[tuple[str, str]],
    ) -> None:
        # The Environment story is rendered immediately after the surface heading.
        # Suppress only the legacy bottom-of-page call.
        if active_page == "Environment":
            return
        original_story(active_page, steps)

    @wraps(original_expander)
    def expander(label: str, *args: object, **kwargs: object):
        if label == _OLD_EXPANDER_LABEL:
            return nullcontext()
        return original_expander(label, *args, **kwargs)

    app_impl.render_app_header = render_app_header
    app_impl.surface_story = surface_story
    app_impl.st.expander = expander
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
