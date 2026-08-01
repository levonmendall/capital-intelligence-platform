"""Expandable Decision Pulse presentation for the Today surface.

This module changes presentation only. It does not read, score, size, approve,
construct, or execute an investment decision.
"""

from __future__ import annotations

from html import escape
from types import ModuleType
from typing import Sequence

import streamlit as st


_INSTALLED_STATE_KEY = "_capital_intelligence_decision_pulse_refinement_installed"

_DECISION_PULSE_LABELS = (
    "market status",
    "portfolio action",
    "portfolio effect",
    "what could change the decision",
)

_MARKER_CLASSES = {
    "market status": "decision-section-market",
    "portfolio action": "decision-section-action",
    "portfolio effect": "decision-section-portfolio",
    "what could change the decision": "decision-section-change",
}


_DECISION_PULSE_CSS = """
<style>
/* The Decision Pulse uses the same interaction model as the daily synopsis:
   every icon-and-headline row is a collapsed control with its own detail. */
div[data-testid="stExpander"]:has(.decision-pulse-marker) {
    margin: .36rem 0 !important;
    border: 1px solid rgba(138, 157, 188, .18) !important;
    border-radius: .92rem !important;
    background: linear-gradient(135deg, rgba(13, 20, 34, .9), rgba(8, 14, 25, .9)) !important;
    overflow: hidden !important;
    box-shadow: none !important;
}

div[data-testid="stExpander"]:has(.decision-pulse-marker) summary {
    min-height: 5rem !important;
    padding: .72rem .84rem !important;
    display: grid !important;
    grid-template-columns: 2.7rem minmax(0, 1fr) auto !important;
    align-items: center !important;
    gap: .78rem !important;
}

div[data-testid="stExpander"]:has(.decision-pulse-marker) summary::before {
    content: "◈";
    width: 2.5rem;
    height: 2.5rem;
    display: grid;
    place-items: center;
    border: 1px solid rgba(var(--surface-rgb), .3);
    border-radius: .78rem;
    background: linear-gradient(
        145deg,
        rgba(var(--surface-rgb), .14),
        rgba(var(--surface-rgb-2), .08)
    );
    color: var(--surface-accent);
    font-size: 1rem;
    font-weight: 760;
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, .05),
        0 0 22px rgba(var(--surface-rgb), .06);
}

div[data-testid="stExpander"]:has(.decision-section-action) summary::before {
    content: "✓";
}

div[data-testid="stExpander"]:has(.decision-section-portfolio) summary::before {
    content: "⌂";
}

div[data-testid="stExpander"]:has(.decision-section-change) summary::before {
    content: "↗";
}

div[data-testid="stExpander"]:has(.decision-pulse-marker) summary p {
    margin: 0 !important;
    color: #dce7f6 !important;
    font-size: .92rem !important;
    line-height: 1.48 !important;
    font-weight: 690 !important;
}

div[data-testid="stExpander"]:has(.decision-pulse-marker)[open] {
    border-color: rgba(var(--surface-rgb), .3) !important;
    background: linear-gradient(
        135deg,
        rgba(var(--surface-rgb), .075),
        rgba(8, 14, 25, .94)
    ) !important;
}

div[data-testid="stExpander"]:has(.decision-pulse-marker)
[data-testid="stExpanderDetails"] {
    padding: 0 .98rem .96rem 4.25rem !important;
}

.decision-pulse-marker {
    display: none;
}

@media (max-width: 760px) {
    div[data-testid="stExpander"]:has(.decision-pulse-marker) summary {
        min-height: 4.65rem !important;
        grid-template-columns: 2.45rem minmax(0, 1fr) auto !important;
        gap: .62rem !important;
        padding: .64rem .68rem !important;
    }

    div[data-testid="stExpander"]:has(.decision-pulse-marker) summary::before {
        width: 2.3rem;
        height: 2.3rem;
        border-radius: .7rem;
    }

    div[data-testid="stExpander"]:has(.decision-pulse-marker) summary p {
        font-size: .84rem !important;
        line-height: 1.43 !important;
    }

    div[data-testid="stExpander"]:has(.decision-pulse-marker)
    [data-testid="stExpanderDetails"] {
        padding: 0 .76rem .82rem .76rem !important;
    }
}
</style>
"""


def _clean(value: object, fallback: str = "No additional detail is available.") -> str:
    text = " ".join(str(value or "").split())
    return text or fallback


def _compact(value: object, *, limit: int = 108) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]) + "…"


def _headline(label: object, value: object) -> str:
    normalized = _clean(label, "").casefold()
    if normalized == "what could change the decision":
        return (
            "A stronger, liquid, risk-adjusted opportunity must clear every "
            "decision threshold."
        )
    return _compact(value)


def _normalized_labels(
    items: Sequence[tuple[str, object, str | None]],
) -> tuple[str, ...]:
    return tuple(_clean(label, "").casefold() for label, _value, _note in items)


def _is_decision_pulse(
    items: Sequence[tuple[str, object, str | None]],
    *,
    variant: str,
) -> bool:
    return (
        str(variant).strip().casefold() == "today"
        and _normalized_labels(items) == _DECISION_PULSE_LABELS
    )


def _expander_label(label: object, value: object) -> str:
    headline = _headline(label, value)
    return f"{_clean(label, '').upper()} · {headline}"


def render_decision_pulse_status_list(
    items: Sequence[tuple[str, object, str | None]],
    *,
    variant: str = "today",
) -> None:
    """Render each Decision Pulse fact as its own collapsed section."""

    del variant
    for label, value, note in items:
        normalized = _clean(label, "").casefold()
        marker_class = _MARKER_CLASSES.get(
            normalized,
            "decision-section-generic",
        )
        with st.expander(_expander_label(label, value), expanded=False):
            st.markdown(
                '<span class="decision-pulse-marker '
                f'{escape(marker_class)}" aria-hidden="true"></span>',
                unsafe_allow_html=True,
            )
            st.write(_clean(value))
            if note not in (None, ""):
                st.caption(_clean(note, ""))


def install(app_impl: ModuleType) -> None:
    """Install the Decision Pulse interaction without changing other status lists."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_apply_global_style = app_impl.apply_global_style
    original_status_list = app_impl.status_list

    def apply_global_style(*, dark_mode: bool = True) -> None:
        original_apply_global_style(dark_mode=dark_mode)
        st.markdown(_DECISION_PULSE_CSS, unsafe_allow_html=True)

    def status_list(
        items: Sequence[tuple[str, object, str | None]],
        *,
        variant: str = "history",
    ) -> None:
        materialized = tuple(items)
        if _is_decision_pulse(materialized, variant=variant):
            render_decision_pulse_status_list(
                materialized,
                variant=variant,
            )
            return
        original_status_list(materialized, variant=variant)

    app_impl.apply_global_style = apply_global_style
    app_impl.status_list = status_list
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = [
    "install",
    "render_decision_pulse_status_list",
]
