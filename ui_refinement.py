"""Aesthetic and usability refinements for the four Streamlit surfaces.

This module changes presentation only. It does not read, score, size, approve,
or execute investments, and it does not alter any canonical operating control.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Callable

import streamlit as st

import premium_ui


_PUBLIC_VIEWER_STATE_KEY = "_capital_intelligence_public_viewer"
_INSTALLED_STATE_KEY = "_capital_intelligence_ui_refinement_installed"


_REFINEMENT_CSS = """
<style>
:root {
    --ui-radius-lg: 1rem;
    --ui-radius-md: .8rem;
    --ui-focus: rgba(var(--surface-rgb), .82);
}

/* Keep the investor-facing canvas centered and remove the oversized desktop
   top gap that made the page feel detached from its navigation. */
.block-container {
    max-width: 1120px !important;
    padding-top: 1.15rem !important;
    padding-bottom: calc(3rem + env(safe-area-inset-bottom, 0px)) !important;
}

/* The four primary surfaces are the product's main information architecture.
   Keep them visible while a reader moves through a long daily briefing. */
[data-testid="stButtonGroup"] {
    position: sticky !important;
    top: max(.42rem, env(safe-area-inset-top, 0px)) !important;
    z-index: 80 !important;
    padding: .22rem !important;
    border: 1px solid rgba(138, 157, 188, .18) !important;
    border-radius: 1rem !important;
    background: rgba(7, 12, 22, .88) !important;
    box-shadow: 0 14px 34px rgba(0, 0, 0, .28) !important;
    backdrop-filter: blur(24px) saturate(125%) !important;
    -webkit-backdrop-filter: blur(24px) saturate(125%) !important;
}

[data-testid="stButtonGroup"] div[role="radiogroup"] {
    border-bottom: 0 !important;
    border-radius: .78rem !important;
}

[data-testid="stButtonGroup"] button {
    min-height: 2.75rem !important;
}

.nav-brand-mark {
    width: 2.65rem !important;
    height: 2.65rem !important;
    border-radius: .9rem !important;
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .15), rgba(var(--surface-rgb-2), .08)) !important;
}

/* A truthful, compact trust strip replaces technical host information. */
.surface-trust-strip {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: .36rem;
    margin-top: .72rem;
}

.surface-trust-chip,
.surface-viewed-at {
    display: inline-flex;
    align-items: center;
    min-height: 1.62rem;
    padding: .26rem .52rem;
    border-radius: 999px;
    font-size: .64rem;
    line-height: 1;
    font-weight: 680;
    letter-spacing: .01em;
}

.surface-trust-chip {
    border: 1px solid rgba(138, 157, 188, .16);
    background: rgba(255, 255, 255, .025);
    color: #aebbd0;
}

.surface-trust-chip.primary {
    gap: .38rem;
    border-color: rgba(var(--surface-rgb), .25);
    background: rgba(var(--surface-rgb), .075);
    color: #e9f8ff;
}

.surface-trust-chip.primary::before {
    content: "";
    width: .38rem;
    height: .38rem;
    border-radius: 50%;
    background: var(--surface-accent);
    box-shadow: 0 0 10px rgba(var(--surface-rgb), .7);
}

.surface-viewed-at {
    padding-left: .2rem;
    color: #718299;
    font-weight: 560;
}

.compact-surface-head {
    margin: .85rem 0 1.15rem !important;
    padding-bottom: .65rem !important;
}

.compact-surface-head h1 {
    font-size: clamp(1.9rem, 4vw, 2.35rem) !important;
    font-weight: 740 !important;
}

.compact-surface-head p {
    max-width: 42rem !important;
    color: #9aa9bf !important;
    font-size: .9rem !important;
    line-height: 1.5 !important;
}

.surface-eyebrow {
    font-size: .66rem !important;
}

/* Improve hierarchy and legibility without increasing visual noise. */
.section-header {
    margin-top: 1.65rem !important;
    margin-bottom: .78rem !important;
    scroll-margin-top: 5rem;
}

.section-header h3 {
    font-size: 1.18rem !important;
}

.section-header p {
    max-width: 48rem !important;
    color: #8494aa !important;
    font-size: .8rem !important;
    line-height: 1.48 !important;
}

.status-list,
.metric-node,
.section-card,
.callout-card,
.signal-panel,
.investment-lens,
.activity-item,
.capital-orbit,
[data-testid="stExpander"],
[data-testid="stDataFrame"] {
    border-color: rgba(138, 157, 188, .19) !important;
}

.status-row {
    min-height: 4.7rem;
    padding: .86rem .92rem !important;
}

.status-label {
    font-size: .68rem !important;
    font-weight: 720 !important;
    letter-spacing: .015em;
}

.status-value {
    font-size: .98rem !important;
    line-height: 1.32 !important;
}

.status-note {
    margin-top: .22rem !important;
    color: #8494aa !important;
    font-size: .72rem !important;
    line-height: 1.42 !important;
}

.metric-seq,
.metric-label,
.metric-note,
.activity-kind,
.activity-meta,
.lens-label,
.lens-hint,
.callout-title,
.minor-note {
    color: #8292a8 !important;
}

.metric-value {
    color: #fbfdff !important;
}

.section-copy,
.lens-copy,
.signal-panel p,
.capital-copy p {
    color: #a1aec1 !important;
}

/* Expanders and secondary tabs are functional navigation, so keep their tap
   targets accessible on mobile and make the active state more obvious. */
[data-testid="stExpander"] summary {
    min-height: 2.9rem;
    display: flex;
    align-items: center;
}

button[data-baseweb="tab"] {
    min-height: 2.75rem !important;
    font-weight: 650 !important;
}

button[data-baseweb="tab"][aria-selected="true"] {
    box-shadow: inset 0 -2px 0 var(--surface-accent) !important;
}

[data-testid="stDataFrame"] {
    overflow-x: auto !important;
}

/* Keyboard focus should remain visible within the permanent-dark theme. */
button:focus-visible,
summary:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
[tabindex]:focus-visible {
    outline: 2px solid var(--ui-focus) !important;
    outline-offset: 2px !important;
}

@media (hover: hover) and (pointer: fine) {
    .metric-node,
    .activity-item,
    .section-card,
    .callout-card,
    .status-row {
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
    }

    .metric-node:hover,
    .activity-item:hover,
    .section-card:hover,
    .callout-card:hover {
        transform: translateY(-1px);
        border-color: rgba(var(--surface-rgb), .28) !important;
    }
}

@media (max-width: 760px) {
    .block-container {
        padding: .58rem .72rem calc(3.2rem + env(safe-area-inset-bottom, 0px)) !important;
    }

    [data-testid="stButtonGroup"] {
        top: max(.3rem, env(safe-area-inset-top, 0px)) !important;
        padding: .16rem !important;
        border-radius: .92rem !important;
    }

    [data-testid="stButtonGroup"] button {
        min-height: 2.8rem !important;
        font-size: clamp(.66rem, 2.85vw, .82rem) !important;
    }

    .nav-brand-mark {
        width: 2.45rem !important;
        height: 2.45rem !important;
    }

    .compact-surface-head {
        margin-top: .72rem !important;
        margin-bottom: 1rem !important;
    }

    .compact-surface-row {
        gap: .72rem !important;
    }

    .compact-surface-head h1 {
        font-size: 1.78rem !important;
    }

    .compact-surface-head p {
        font-size: .84rem !important;
        line-height: 1.48 !important;
    }

    .surface-trust-strip {
        gap: .3rem;
        margin-top: .62rem;
    }

    .surface-trust-chip,
    .surface-viewed-at {
        min-height: 1.55rem;
        font-size: .61rem;
    }

    .section-header {
        margin-top: 1.45rem !important;
    }

    .section-header h3 {
        font-size: 1.12rem !important;
    }

    .section-header p {
        font-size: .79rem !important;
    }

    .status-row {
        grid-template-columns: 2.5rem minmax(0, 1fr) !important;
        gap: .68rem !important;
        min-height: 4.65rem;
        padding: .8rem .78rem !important;
    }

    .status-icon {
        width: 2.3rem !important;
        height: 2.3rem !important;
    }

    .status-value {
        font-size: .95rem !important;
    }

    .status-note {
        font-size: .7rem !important;
    }

    .metric-grid {
        gap: .48rem !important;
    }

    .metric-node {
        min-height: 6.15rem !important;
        padding: .72rem !important;
    }

    .metric-value {
        font-size: 1rem !important;
    }

    .metric-note {
        font-size: .62rem !important;
    }

    [data-testid="stExpander"] summary,
    button[data-baseweb="tab"] {
        min-height: 3rem !important;
    }
}

@media (max-width: 390px) {
    .block-container {
        padding-left: .6rem !important;
        padding-right: .6rem !important;
    }

    .surface-viewed-at {
        flex-basis: 100%;
        padding-left: .1rem;
    }
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: .01ms !important;
        animation-iteration-count: 1 !important;
        scroll-behavior: auto !important;
        transition-duration: .01ms !important;
    }
}
</style>
"""


_PUBLIC_SIDEBAR_CSS = """
<style>
[data-testid="collapsedControl"] { display: none !important; }
[data-testid="stSidebar"] { display: none !important; }
</style>
"""


def _viewer_label() -> str:
    return (
        "Public read-only viewer"
        if st.session_state.get(_PUBLIC_VIEWER_STATE_KEY, False)
        else "Authorized governed viewer"
    )


def _render_refined_header(active_page: str) -> None:
    profile = premium_ui.surface_profile(active_page)
    viewed_at = datetime.now(timezone.utc).strftime("%b %d · %H:%M UTC")
    icon = premium_ui._icon_svg(premium_ui._icon_name(profile.name))
    st.markdown(
        (
            f'<style>:root{{--surface-accent:{profile.accent};'
            f'--surface-rgb:{profile.accent_rgb};'
            f'--surface-accent-2:{profile.accent_secondary};'
            f'--surface-rgb-2:{profile.accent_secondary_rgb};}}</style>'
            f'<div class="surface-marker surface-{profile.slug}"></div>'
            '<div class="compact-surface-head">'
            '<div class="compact-surface-row">'
            f'<div class="surface-head-icon">{icon}</div>'
            '<div>'
            f'<div class="surface-eyebrow">{escape(profile.kicker)}</div>'
            f'<h1>{escape(profile.name)}</h1>'
            f'<p>{escape(profile.copy)}</p>'
            '<div class="surface-trust-strip">'
            f'<span class="surface-trust-chip primary">{escape(_viewer_label())}</span>'
            '<span class="surface-trust-chip">$250,000 paper portfolio</span>'
            f'<span class="surface-viewed-at">Viewed {escape(viewed_at)}</span>'
            '</div></div></div></div>'
        ),
        unsafe_allow_html=True,
    )


def install(app_impl: ModuleType, secure_app: ModuleType) -> None:
    """Install one idempotent presentation layer on an application entrypoint."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_apply_global_style: Callable[..., Any] = app_impl.apply_global_style
    original_identity_controls: Callable[..., Any] = secure_app._render_identity_controls
    original_deployment_controls: Callable[..., Any] = secure_app._render_deployment_controls

    def apply_global_style(*, dark_mode: bool = True) -> None:
        original_apply_global_style(dark_mode=True)
        st.markdown(_REFINEMENT_CSS, unsafe_allow_html=True)

    def render_identity_controls(principal: Any) -> None:
        is_public = bool(getattr(principal, "is_anonymous", False))
        st.session_state[_PUBLIC_VIEWER_STATE_KEY] = is_public
        if is_public:
            st.markdown(_PUBLIC_SIDEBAR_CSS, unsafe_allow_html=True)
            return
        original_identity_controls(principal)

    def render_deployment_controls(principal: Any, deployment: Any) -> None:
        # Deployment paths, hostnames, and smoke-test controls are operational
        # details. Keep them available to administrators, not public readers.
        if getattr(principal, "is_administrator", False):
            original_deployment_controls(principal, deployment)

    app_impl.apply_global_style = apply_global_style
    app_impl.render_sidebar = lambda: None
    app_impl.render_app_header = _render_refined_header
    secure_app._render_identity_controls = render_identity_controls
    secure_app._render_deployment_controls = render_deployment_controls
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
