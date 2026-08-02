"""Make secondary Today developments use the lead-story visual hierarchy.

This module is presentation-only. It preserves event selection and interpretation
while making Development 02 and Development 03 full-width, structured stories
with the same three explanatory panels as the most material development.
"""

from __future__ import annotations

from html import escape
from types import ModuleType

import streamlit as st


_INSTALLED_KEY = "_capital_intelligence_secondary_story_format_installed"


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def install(story: ModuleType | None = None) -> None:
    """Install the full-width secondary development format."""

    if story is None:
        import environment_story_placement_refinement as story_module

        story = story_module

    if getattr(story, _INSTALLED_KEY, False):
        return

    original_styles = story._styles

    def styles() -> None:
        original_styles()
        st.markdown(
            """
<style>
.ci-story-grid{grid-template-columns:1fr;gap:1rem}
.ci-story.ci-story-feature{padding:1rem 1.05rem;border-radius:22px;
 border-color:rgba(86,224,255,.18);background:linear-gradient(145deg,
 rgba(13,20,34,.96),rgba(9,14,25,.96));box-shadow:0 18px 42px rgba(0,0,0,.22)}
.ci-story-feature .ci-title{font-size:clamp(1.2rem,2.5vw,1.75rem);margin:.55rem 0 .76rem}
.ci-story-feature .ci-three{margin-top:.1rem}
@media(max-width:720px){.ci-story.ci-story-feature{padding:.9rem}.ci-story-feature .ci-title{font-size:1.2rem}}
</style>
            """,
            unsafe_allow_html=True,
        )

    def secondary(item: object, rank: int) -> str:
        why = _clean(getattr(item, "why_it_matters", ""))
        if not why:
            _, why = story._lesson(item)
        source_type = _clean(getattr(item, "source_type", "Public")) or "Public"
        source = _clean(getattr(item, "source", "Public source")) or "Public source"
        title = _clean(getattr(item, "title", "Market development"))
        summary = _clean(getattr(item, "summary", "No concise detail is available."))
        reaction = _clean(
            getattr(item, "portfolio_lens", "Market effects remain under review.")
        )
        exposure = _clean(getattr(item, "affected_investments", ""))
        tag_markup = story._tags(item)
        exposure_markup = (
            '<div class="ci-copy" style="margin-top:.72rem"><strong>Most directly exposed:</strong> '
            f'{escape(exposure)}</div>'
            if exposure
            else ""
        )
        return (
            '<article class="ci-story ci-story-feature"><div class="ci-meta">'
            f'<span class="ci-rank">Development {rank:02d}</span>'
            f'<span>{escape(source_type)} · {escape(source)}</span>'
            f'<span>{escape(story._age_label(getattr(item, "published_at", None)))}</span></div>'
            f'<div class="ci-title">{escape(title)}</div>'
            '<div class="ci-three"><div class="ci-box"><div class="ci-label">What happened</div>'
            f'<p>{escape(summary)}</p></div>'
            '<div class="ci-box"><div class="ci-label">Why it matters</div>'
            f'<p>{escape(why)}</p></div>'
            '<div class="ci-box"><div class="ci-label">How markets may react</div>'
            f'<p>{escape(reaction)}</p></div></div>'
            f'{exposure_markup}'
            + (f'<div class="ci-tags">{tag_markup}</div>' if tag_markup else "")
            + "</article>"
        )

    story._styles = styles
    story._secondary = secondary
    setattr(story, _INSTALLED_KEY, True)


__all__ = ["install"]
