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

[data-testid="stButtonGroup"] {
    width: 100% !important;
    margin: 0 !important;
}

.nav-brand-mark {
    width: 2.4rem;
    height: 2.4rem;
    display: grid;
    place-items: center;
    border-radius: .78rem;
    border: 1px solid rgba(86, 224, 255, .24);
    background: linear-gradient(145deg, rgba(86, 224, 255, .10), rgba(91, 124, 255, .07));
    color: #56e0ff;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 0 20px rgba(86,224,255,.08);
    margin-top: .08rem;
}

.nav-brand-mark svg {
    width: 1.15rem;
    height: 1.15rem;
    stroke: currentColor;
    fill: none;
    stroke-width: 1.7;
    stroke-linecap: round;
    stroke-linejoin: round;
}

[data-testid="stButtonGroup"] > div,
[data-testid="stButtonGroup"] div[role="radiogroup"] {
    width: 100% !important;
}

[data-testid="stButtonGroup"] div[role="radiogroup"] {
    display: grid !important;
    grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
    gap: 0 !important;
    padding: .08rem !important;
    overflow: hidden !important;
    border: 0 !important;
    border-bottom: 1px solid rgba(138, 157, 188, .14) !important;
    border-radius: 0 !important;
    background: transparent !important;
    box-shadow: none !important;
    backdrop-filter: blur(22px) !important;
}

[data-testid="stButtonGroup"] button {
    position: relative !important;
    width: 100% !important;
    min-width: 0 !important;
    min-height: 2.4rem !important;
    padding: .48rem .16rem !important;
    border: 0 !important;
    border-radius: .55rem !important;
    background: transparent !important;
    color: #9aa9bf !important;
    box-shadow: none !important;
    font-size: clamp(.68rem, 2.8vw, .94rem) !important;
    font-weight: 650 !important;
    letter-spacing: -.015em !important;
    white-space: nowrap !important;
    transition:
        color 160ms ease,
        background 160ms ease,
        box-shadow 160ms ease !important;
}

[data-testid="stButtonGroup"] button:not(:last-child)::after {
    content: "";
    position: absolute;
    top: 22%;
    right: 0;
    bottom: 22%;
    width: 1px;
    background: rgba(138, 157, 188, .13);
}

[data-testid="stButtonGroup"] button:hover {
    color: #eef8ff !important;
    background: rgba(86, 224, 255, .045) !important;
}

[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stButtonGroup"] button[aria-pressed="true"] {
    color: #ffffff !important;
    font-weight: 760 !important;
    background: rgba(var(--surface-rgb), .045) !important;
    box-shadow: none !important;
}

[data-testid="stButtonGroup"] button[aria-checked="true"]::before,
[data-testid="stButtonGroup"] button[aria-pressed="true"]::before {
    content: "";
    position: absolute;
    left: 16%;
    right: 16%;
    bottom: .1rem;
    height: 2px;
    border-radius: 999px;
    background: var(--surface-accent);
    box-shadow: 0 0 12px rgba(var(--surface-rgb), .85);
}

/* Streamlit wraps each columns row in a short element container. Making only
   the inner row sticky allows that short wrapper to release the navigation as
   soon as it leaves the viewport. Pin the complete element wrapper instead,
   then keep the visual row relative inside it. */
:is(
    div[data-testid="stElementContainer"],
    div.stElementContainer,
    div.element-container
):has(div[data-testid="stHorizontalBlock"] .nav-brand-mark) {
    position: sticky !important;
    top: max(.28rem, env(safe-area-inset-top, 0px)) !important;
    z-index: 1000 !important;
    width: 100% !important;
    align-self: stretch !important;
    isolation: isolate !important;
}

:is(
    div[data-testid="stElementContainer"],
    div.stElementContainer,
    div.element-container
):has(div[data-testid="stHorizontalBlock"] .nav-brand-mark)
  div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) {
    position: relative !important;
    top: auto !important;
}

@media (min-width: 761px) {
    .block-container {
        padding-top: 4rem !important;
    }
}

@media (max-width: 760px) {
    [data-testid="stButtonGroup"] div[role="radiogroup"] {
        grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
        padding: .18rem !important;
        border-radius: .95rem !important;
    }

    [data-testid="stButtonGroup"] button {
        min-height: 2.75rem !important;
        padding: .43rem .04rem !important;
        border-radius: .48rem !important;
    }

    :is(
        div[data-testid="stElementContainer"],
        div.stElementContainer,
        div.element-container
    ):has(div[data-testid="stHorizontalBlock"] .nav-brand-mark) {
        top: max(.16rem, env(safe-area-inset-top, 0px)) !important;
    }
}

@media (max-width: 390px) {
    [data-testid="stButtonGroup"] button {
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

        brand, navigation = st.columns((0.42, 5.58), gap="small", vertical_alignment="center")
        with brand:
            st.markdown(
                '<div class="nav-brand-mark">'
                '<svg viewBox="0 0 24 24" aria-hidden="true">'
                '<path d="m12 3 7 4v10l-7 4-7-4V7z"/>'
                '<path d="m8.5 9 3.5-2 3.5 2v6L12 17l-3.5-2z"/>'
                '</svg></div>',
                unsafe_allow_html=True,
            )
        with navigation:
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
