"""Keep the Today process lens visible and horizontal at the top of the surface.

This presentation adapter moves the existing Observe / Explain / Resolve / Act
story out of its bottom-page expander and renders the four stages in one
horizontal lane. It changes layout only and does not read, score, qualify, size,
construct, execute, or authorize an investment decision.
"""

from __future__ import annotations

from contextlib import nullcontext
from functools import wraps
from html import escape
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


def _today_story_markup(steps: Sequence[tuple[str, str]]) -> str:
    cards = "".join(
        f"""
        <article class="today-lens-card" role="listitem">
          <div class="today-lens-step">{index:02d}</div>
          <div class="today-lens-title">{escape(title)}</div>
          <div class="today-lens-copy">{escape(copy)}</div>
        </article>
        """
        for index, (title, copy) in enumerate(steps, start=1)
    )
    return f"""
    <style>
      .today-lens-horizontal{{
        margin:1rem 0 1.35rem;
        padding:1.45rem;
        border:1px solid rgba(var(--surface-rgb),.18);
        border-radius:28px;
        background:linear-gradient(145deg,rgba(10,17,30,.96),rgba(7,12,23,.96));
        box-shadow:0 22px 55px rgba(0,0,0,.24);
        overflow:hidden;
      }}
      .today-lens-kicker{{
        color:var(--surface-accent);
        font-size:.72rem;
        font-weight:850;
        letter-spacing:.16em;
        text-transform:uppercase;
        margin-bottom:.55rem;
      }}
      .today-lens-heading{{
        color:#f7fbff;
        font-size:1.45rem;
        font-weight:760;
        letter-spacing:-.025em;
        margin-bottom:1.15rem;
      }}
      .today-lens-row{{
        display:grid;
        grid-template-columns:repeat(4,minmax(0,1fr));
        gap:.75rem;
        align-items:stretch;
      }}
      .today-lens-card{{
        position:relative;
        min-width:0;
        min-height:10.4rem;
        padding:1rem 1rem 1.15rem;
        border:1px solid rgba(var(--surface-rgb),.22);
        border-radius:20px;
        background:linear-gradient(155deg,rgba(var(--surface-rgb),.08),rgba(var(--surface-rgb-2),.055));
        box-shadow:inset 0 1px 0 rgba(255,255,255,.035);
        overflow:hidden;
      }}
      .today-lens-card:after{{
        content:"";
        position:absolute;
        left:0;
        right:0;
        bottom:0;
        height:3px;
        background:linear-gradient(90deg,var(--surface-accent),var(--surface-accent-2),transparent);
      }}
      .today-lens-step{{
        color:var(--surface-accent);
        font-size:.72rem;
        font-weight:850;
        letter-spacing:.13em;
        margin-bottom:.8rem;
      }}
      .today-lens-title{{
        color:#f7fbff;
        font-size:1.05rem;
        font-weight:760;
        margin-bottom:.5rem;
      }}
      .today-lens-copy{{
        color:#8f9db2;
        font-size:.84rem;
        line-height:1.48;
      }}
      @media (max-width:760px){{
        .today-lens-horizontal{{padding:1.2rem 1rem 1rem}}
        .today-lens-row{{
          display:flex;
          flex-wrap:nowrap;
          gap:.7rem;
          overflow-x:auto;
          overflow-y:hidden;
          scroll-snap-type:x mandatory;
          scrollbar-width:none;
          overscroll-behavior-x:contain;
          -webkit-overflow-scrolling:touch;
          padding:.05rem .05rem .65rem;
        }}
        .today-lens-row::-webkit-scrollbar{{display:none}}
        .today-lens-card{{
          flex:0 0 min(76vw,17rem);
          min-height:9.6rem;
          scroll-snap-align:start;
        }}
      }}
    </style>
    <section class="surface-story story-today today-lens-horizontal" aria-label="Today decision process">
      <div class="today-lens-kicker">Decision pulse</div>
      <div class="today-lens-heading">Today lens</div>
      <div class="today-lens-row" role="list" aria-label="Observe, explain, resolve, and act">
        {cards}
      </div>
    </section>
    """


def _render_today_story(streamlit_module: object) -> None:
    # st.html preserves nested semantic elements as one DOM tree. st.markdown
    # can split nested block-level HTML, which would detach the cards from the
    # horizontal row and defeat the mobile overflow behavior.
    streamlit_module.html(_today_story_markup(_TODAY_STEPS))  # type: ignore[attr-defined]


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
            _render_today_story(app_impl.st)

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
