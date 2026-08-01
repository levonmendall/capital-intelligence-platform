"""Keep the Environment process lens visible in the shared responsive grid.

The four stages appear directly below the Environment heading. On iPhone they
render as four fully visible square cards in a two-by-two grid matching Today.
This is presentation-only.
"""

from __future__ import annotations

from contextlib import nullcontext
from functools import wraps
from types import ModuleType
from typing import Sequence

from process_lens_grid import render_process_lens


_INSTALLED_STATE_KEY = "_capital_intelligence_environment_story_placement_installed"
_OLD_EXPANDER_LABEL = "How the Environment surface works"
_ENVIRONMENT_STEPS: tuple[tuple[str, str], ...] = (
    ("Measure", "Read growth, inflation, policy, credit, and liquidity."),
    ("Classify", "Describe the regime without creating a trade signal."),
    ("Confirm", "Compare macro conditions with cross-asset behavior."),
    ("Monitor", "Identify what would change the classification."),
)


def _render_environment_story(streamlit_module: object) -> None:
    render_process_lens(
        streamlit_module,
        variant="environment",
        kicker="Market atmosphere",
        title="Environment lens",
        aria_label="Environment classification process",
        steps=_ENVIRONMENT_STEPS,
    )


def install(app_impl: ModuleType) -> None:
    """Install one idempotent, presentation-only Environment refinement."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_header = app_impl.render_app_header
    original_story = app_impl.surface_story
    original_expander = app_impl.st.expander

    @wraps(original_header)
    def render_app_header(active_page: str) -> None:
        original_header(active_page)
        if active_page == "Environment":
            _render_environment_story(app_impl.st)

    @wraps(original_story)
    def surface_story(
        active_page: str,
        steps: Sequence[tuple[str, str]],
    ) -> None:
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
