"""Deployment-stable primary navigation for the Streamlit command deck.

The live application imports this module from ``app.py`` so the authenticated and
unauthenticated entrypoints share one permanent-dark navigation contract.
"""

from __future__ import annotations

from typing import Any, Sequence

import streamlit as st


_NAVIGATION_CSS = """
<style>
/* Permanent dark command deck. This final override intentionally follows the
   broader presentation stylesheet so older responsive radio rules cannot win. */
.stApp {
    color: #f8fafc !important;
    background-color: #05070d !important;
}

[data-testid="stSegmentedControl"] {
    width: 100% !important;
    margin: 0 0 1.05rem !important;
}

[data-testid="stSegmentedControl"] > div,
[data-testid="stSegmentedControl"] div[role="radiogroup"] {
    width: 100% !important;
}

[data-testid="stSegmentedControl"] div[role="radiogroup"] {
    display: grid !important;
    grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
    gap: 0 !important;
    padding: .32rem !important;
    overflow: hidden !important;
    border: 1px solid rgba(86, 224, 255, .34) !important;
    border-radius: 1.35rem !important;
    background:
        linear-gradient(180deg, rgba(13, 19, 32, .96), rgba(7, 11, 19, .96)) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, .045),
        0 0 0 1px rgba(91, 124, 255, .08),
        0 18px 46px rgba(0, 0, 0, .30) !important;
    backdrop-filter: blur(22px) !important;
}

[data-testid="stSegmentedControl"] button {
    position: relative !important;
    width: 100% !important;
    min-width: 0 !important;
    min-height: 3.15rem !important;
    padding: .72rem .35rem !important;
    border: 0 !important;
    border-radius: 1rem !important;
    background: transparent !important;
    color: #9aa9bf !important;
    box-shadow: none !important;
    font-size: clamp(.68rem, 2.8vw, .94rem) !important;
    font-weight: 620 !important;
    letter-spacing: -.015em !important;
    white-space: nowrap !important;
    transition:
        color 160ms ease,
        background 160ms ease,
        box-shadow 160ms ease !important;
}

[data-testid="stSegmentedControl"] button:not(:last-child)::after {
    content: "";
    position: absolute;
    top: 22%;
    right: 0;
    bottom: 22%;
    width: 1px;
    background: rgba(138, 157, 188, .13);
}

[data-testid="stSegmentedControl"] button:hover {
    color: #eef8ff !important;
    background: rgba(86, 224, 255, .045) !important;
}

[data-testid="stSegmentedControl"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[aria-pressed="true"] {
    color: #ffffff !important;
    font-weight: 760 !important;
    background:
        radial-gradient(circle at 50% 115%, rgba(86, 224, 255, .30), transparent 58%),
        linear-gradient(135deg, rgba(86, 224, 255, .15), rgba(91, 124, 255, .20)) !important;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, .08),
        0 0 28px rgba(86, 224, 255, .10) !important;
}

[data-testid="stSegmentedControl"] button[aria-checked="true"]::before,
[data-testid="stSegmentedControl"] button[aria-pressed="true"]::before {
    content: "";
    position: absolute;
    left: 16%;
    right: 16%;
    bottom: .18rem;
    height: 2px;
    border-radius: 999px;
    background: #56e0ff;
    box-shadow: 0 0 12px rgba(86, 224, 255, .85);
}

@media (max-width: 760px) {
    [data-testid="stSegmentedControl"] div[role="radiogroup"] {
        grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
        padding: .26rem !important;
        border-radius: 1.15rem !important;
    }

    [data-testid="stSegmentedControl"] button {
        min-height: 2.9rem !important;
        padding: .62rem .12rem !important;
        border-radius: .88rem !important;
    }
}

@media (max-width: 390px) {
    [data-testid="stSegmentedControl"] button {
        font-size: .64rem !important;
        letter-spacing: -.025em !important;
    }
}
</style>
"""


def install(premium_ui: Any) -> None:
    """Install the permanent-dark navigation contract on ``premium_ui``.

    ``app_impl.py`` imports its helpers only after this function runs, so both
    active Streamlit entrypoints receive the same implementation without source
    rewriting or a second theme control.
    """

    original_apply_global_style = premium_ui.apply_global_style

    def apply_global_style(*, dark_mode: bool = True) -> None:
        del dark_mode
        original_apply_global_style(dark_mode=True)
        st.markdown(_NAVIGATION_CSS, unsafe_allow_html=True)

    def render_navigation(options: Sequence[str]) -> tuple[str, bool]:
        choices = [str(option) for option in options]
        if not choices:
            raise ValueError("primary navigation requires at least one surface")

        st.markdown(
            '<div class="command-label">Capital Intelligence // Command Deck</div>',
            unsafe_allow_html=True,
        )
        selected = st.segmented_control(
            "Primary screens",
            choices,
            selection_mode="single",
            default=choices[0],
            required=True,
            label_visibility="collapsed",
            width="stretch",
            key="primary_surface_navigation_v2",
        )
        return str(selected or choices[0]), True

    premium_ui.apply_global_style = apply_global_style
    premium_ui.render_navigation = render_navigation
