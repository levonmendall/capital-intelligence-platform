"""Shared responsive process-lens presentation for Today and Environment.

The renderer keeps the two surfaces visually identical while preserving their
separate language and investment meaning. It is presentation-only and has no
investment, sizing, construction, execution, or authority behavior.
"""

from __future__ import annotations

from html import escape
from typing import Sequence


PROCESS_LENS_STYLE = """
<style>
.process-lens-grid {
    box-sizing: border-box;
    margin: 1rem 0 1.35rem;
    padding: 1.15rem;
    border: 1px solid rgba(var(--surface-rgb), .2);
    border-radius: 28px;
    background: linear-gradient(145deg, rgba(10, 17, 30, .96), rgba(7, 12, 23, .96));
    box-shadow: 0 22px 55px rgba(0, 0, 0, .24);
    overflow: hidden;
}
.process-lens-head {
    margin-bottom: 1rem;
}
.process-lens-kicker {
    color: var(--surface-accent);
    font-size: .7rem;
    font-weight: 850;
    letter-spacing: .16em;
    text-transform: uppercase;
    margin-bottom: .42rem;
}
.process-lens-title {
    color: #f7fbff;
    font-size: 1.42rem;
    font-weight: 760;
    letter-spacing: -.025em;
}
.process-lens-cards {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: .72rem;
    align-items: stretch;
}
.process-lens-card {
    box-sizing: border-box;
    position: relative;
    min-width: 0;
    aspect-ratio: 1 / 1;
    padding: .95rem;
    border: 1px solid rgba(var(--surface-rgb), .24);
    border-radius: 20px;
    background: linear-gradient(155deg, rgba(var(--surface-rgb), .09), rgba(var(--surface-rgb-2), .055));
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .035);
    overflow: hidden;
    display: flex;
    flex-direction: column;
}
.process-lens-card::after {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--surface-accent), var(--surface-accent-2), transparent);
}
.process-lens-step {
    color: var(--surface-accent);
    font-size: .7rem;
    font-weight: 850;
    letter-spacing: .13em;
    margin-bottom: .7rem;
}
.process-lens-card-title {
    color: #f7fbff;
    font-size: 1.02rem;
    font-weight: 760;
    line-height: 1.16;
    margin-bottom: .45rem;
}
.process-lens-copy {
    color: #8f9db2;
    font-size: .8rem;
    line-height: 1.42;
    overflow-wrap: anywhere;
}
@media (max-width: 760px) {
    .process-lens-grid {
        padding: .88rem;
        border-radius: 24px;
        overflow: hidden;
    }
    .process-lens-head {
        margin-bottom: .78rem;
    }
    .process-lens-kicker {
        font-size: .62rem;
    }
    .process-lens-title {
        font-size: 1.22rem;
    }
    .process-lens-cards {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: .58rem;
        overflow: visible;
    }
    .process-lens-card {
        width: 100%;
        min-width: 0;
        aspect-ratio: 1 / 1;
        padding: .72rem;
        border-radius: 16px;
    }
    .process-lens-step {
        font-size: .61rem;
        margin-bottom: .48rem;
    }
    .process-lens-card-title {
        font-size: .9rem;
        margin-bottom: .35rem;
    }
    .process-lens-copy {
        font-size: .69rem;
        line-height: 1.34;
    }
}
</style>
"""


def process_lens_markup(
    *,
    variant: str,
    kicker: str,
    title: str,
    aria_label: str,
    steps: Sequence[tuple[str, str]],
) -> str:
    """Return one accessible, shared process-lens DOM tree."""

    safe_variant = "".join(character for character in variant if character.isalnum() or character == "-")
    cards = "".join(
        f"""
        <article class="process-lens-card" role="listitem">
          <div class="process-lens-step">{index:02d}</div>
          <div class="process-lens-card-title">{escape(step_title)}</div>
          <div class="process-lens-copy">{escape(copy)}</div>
        </article>
        """
        for index, (step_title, copy) in enumerate(steps, start=1)
    )
    return f"""
    {PROCESS_LENS_STYLE}
    <section class="surface-story story-{safe_variant} process-lens-grid process-lens-{safe_variant}" aria-label="{escape(aria_label)}">
      <div class="process-lens-head">
        <div class="process-lens-kicker">{escape(kicker)}</div>
        <div class="process-lens-title">{escape(title)}</div>
      </div>
      <div class="process-lens-cards" role="list">
        {cards}
      </div>
    </section>
    """


def render_process_lens(
    streamlit_module: object,
    *,
    variant: str,
    kicker: str,
    title: str,
    aria_label: str,
    steps: Sequence[tuple[str, str]],
) -> None:
    """Render one process lens as a single semantic HTML tree."""

    streamlit_module.html(  # type: ignore[attr-defined]
        process_lens_markup(
            variant=variant,
            kicker=kicker,
            title=title,
            aria_label=aria_label,
            steps=steps,
        )
    )


__all__ = ["PROCESS_LENS_STYLE", "process_lens_markup", "render_process_lens"]
