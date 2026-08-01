"""Second-stage presentation refinements for the investor-facing console.

The module improves responsive layout and information clarity only. It does not
read, score, size, approve, construct, or execute an investment decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

import streamlit as st

import concise_operating_intelligence_ui as concise


_INSTALLED_STATE_KEY = "_capital_intelligence_ui_experience_refinement_installed"


_EXPERIENCE_CSS = """
<style>
/* Streamlit reserves a tall header and main-container inset even after its
   controls are hidden. Remove both so the product starts with its own rail. */
[data-testid="stHeader"] {
    display: none !important;
}

.block-container,
[data-testid="stMainBlockContainer"] {
    padding-top: max(.38rem, env(safe-area-inset-top, 0px)) !important;
}

/* Keep the brand and the four primary surfaces in one compact sticky rail.
   Streamlit otherwise stacks the two columns on narrow screens. */
div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) {
    position: sticky !important;
    top: max(.28rem, env(safe-area-inset-top, 0px)) !important;
    z-index: 90 !important;
    display: grid !important;
    grid-template-columns: 2.65rem minmax(0, 1fr) !important;
    align-items: center !important;
    gap: .42rem !important;
    width: 100% !important;
    margin: 0 0 .55rem !important;
    padding: .18rem !important;
    border: 1px solid rgba(138, 157, 188, .18) !important;
    border-radius: 1rem !important;
    background: rgba(7, 12, 22, .91) !important;
    box-shadow: 0 14px 34px rgba(0, 0, 0, .3) !important;
    backdrop-filter: blur(24px) saturate(125%) !important;
    -webkit-backdrop-filter: blur(24px) saturate(125%) !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) > div[data-testid="stColumn"] {
    width: 100% !important;
    min-width: 0 !important;
    flex: none !important;
    padding: 0 !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) [data-testid="stButtonGroup"] {
    position: static !important;
    top: auto !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    border: 0 !important;
    border-radius: .78rem !important;
    background: transparent !important;
    box-shadow: none !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
}

div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) .nav-brand-mark {
    width: 2.48rem !important;
    height: 2.48rem !important;
    margin: 0 !important;
    border-radius: .78rem !important;
}

/* Replace a low-emphasis caption with an immediate, accessible source-health
   signal. Full timestamps and source-level detail remain in the expander. */
.information-health {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: .68rem;
    margin: .22rem 0 .62rem;
    padding: .68rem .78rem;
    border: 1px solid rgba(138, 157, 188, .18);
    border-radius: .9rem;
    background: linear-gradient(135deg, rgba(255, 255, 255, .028), rgba(255, 255, 255, .012));
}

.information-health-dot {
    width: .62rem;
    height: .62rem;
    border-radius: 50%;
    background: var(--surface-accent);
    box-shadow: 0 0 14px rgba(var(--surface-rgb), .68);
}

.information-health.attention {
    border-color: rgba(255, 201, 107, .28);
    background: linear-gradient(135deg, rgba(255, 201, 107, .075), rgba(255, 255, 255, .012));
}

.information-health.attention .information-health-dot {
    background: #ffc96b;
    box-shadow: 0 0 14px rgba(255, 201, 107, .62);
}

.information-health.refreshing .information-health-dot {
    background: #7f9dff;
    box-shadow: 0 0 14px rgba(127, 157, 255, .62);
}

.information-health-copy {
    min-width: 0;
}

.information-health-label {
    color: #eef6ff;
    font-size: .72rem;
    line-height: 1.2;
    font-weight: 760;
    letter-spacing: .01em;
}

.information-health-summary {
    margin-top: .18rem;
    color: #8494aa;
    font-size: .68rem;
    line-height: 1.38;
}

/* Each portfolio-lens row is now its own collapsed control. The icon sits
   inside the clickable summary so tapping either the icon or copy expands the
   information in its proper section. */
.interactive-lens-head {
    margin: .3rem 0 .44rem;
    padding: 1rem 1.08rem .94rem;
    border: 1px solid rgba(var(--surface-rgb), .2);
    border-radius: 1rem;
    background: linear-gradient(145deg, rgba(10, 16, 28, .96), rgba(8, 13, 24, .94));
    box-shadow: 0 18px 42px rgba(0, 0, 0, .24);
}

.interactive-lens-kicker {
    color: var(--surface-accent);
    font-size: .66rem;
    line-height: 1.2;
    font-weight: 820;
    letter-spacing: .14em;
    text-transform: uppercase;
}

.interactive-lens-title {
    margin-top: .52rem;
    color: #f4f8ff;
    font-size: 1.08rem;
    line-height: 1.25;
    font-weight: 760;
    letter-spacing: -.018em;
}

.interactive-lens-hint {
    margin-top: .32rem;
    color: #8292a8;
    font-size: .72rem;
    line-height: 1.42;
}

div[data-testid="stExpander"]:has(.interactive-lens-marker) {
    margin: .36rem 0 !important;
    border: 1px solid rgba(138, 157, 188, .18) !important;
    border-radius: .92rem !important;
    background: linear-gradient(135deg, rgba(13, 20, 34, .9), rgba(8, 14, 25, .9)) !important;
    overflow: hidden !important;
    box-shadow: none !important;
}

div[data-testid="stExpander"]:has(.interactive-lens-marker) summary {
    min-height: 4.72rem !important;
    padding: .68rem .82rem !important;
    display: grid !important;
    grid-template-columns: 2.7rem minmax(0, 1fr) auto !important;
    align-items: center !important;
    gap: .78rem !important;
}

div[data-testid="stExpander"]:has(.interactive-lens-marker) summary::before {
    content: "↗";
    width: 2.5rem;
    height: 2.5rem;
    display: grid;
    place-items: center;
    border: 1px solid rgba(var(--surface-rgb), .3);
    border-radius: .78rem;
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .14), rgba(var(--surface-rgb-2), .08));
    color: var(--surface-accent);
    font-size: 1rem;
    font-weight: 760;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .05), 0 0 22px rgba(var(--surface-rgb), .06);
}

div[data-testid="stExpander"]:has(.lens-section-investors) summary::before {
    content: "◎";
}

div[data-testid="stExpander"]:has(.lens-section-portfolio) summary::before {
    content: "⌂";
}

div[data-testid="stExpander"]:has(.lens-section-cio) summary::before {
    content: "✓";
}

div[data-testid="stExpander"]:has(.lens-section-watch) summary::before {
    content: "↗";
}

div[data-testid="stExpander"]:has(.interactive-lens-marker) summary p {
    margin: 0 !important;
    color: #aebbd0 !important;
    font-size: .88rem !important;
    line-height: 1.45 !important;
    font-weight: 650 !important;
}

div[data-testid="stExpander"]:has(.interactive-lens-marker)[open] {
    border-color: rgba(var(--surface-rgb), .3) !important;
    background: linear-gradient(135deg, rgba(var(--surface-rgb), .075), rgba(8, 14, 25, .94)) !important;
}

div[data-testid="stExpander"]:has(.interactive-lens-marker) [data-testid="stExpanderDetails"] {
    padding: 0 .98rem .96rem 4.25rem !important;
}

.interactive-lens-marker {
    display: none;
}

@media (max-width: 760px) {
    .block-container,
    [data-testid="stMainBlockContainer"] {
        padding-top: max(.28rem, env(safe-area-inset-top, 0px)) !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) {
        grid-template-columns: 2.42rem minmax(0, 1fr) !important;
        gap: .3rem !important;
        margin-bottom: .42rem !important;
        padding: .14rem !important;
        border-radius: .9rem !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) .nav-brand-mark {
        width: 2.28rem !important;
        height: 2.28rem !important;
        border-radius: .7rem !important;
    }

    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) [data-testid="stButtonGroup"] button {
        min-height: 2.68rem !important;
        padding-left: .28rem !important;
        padding-right: .28rem !important;
        font-size: clamp(.65rem, 2.75vw, .78rem) !important;
    }

    .compact-surface-head {
        margin-top: .48rem !important;
    }

    .information-health {
        gap: .58rem;
        margin-bottom: .5rem;
        padding: .62rem .68rem;
    }

    .information-health-label {
        font-size: .7rem;
    }

    .information-health-summary {
        font-size: .66rem;
    }

    .interactive-lens-head {
        padding: .88rem .9rem .82rem;
        border-radius: .92rem;
    }

    .interactive-lens-title {
        font-size: 1rem;
    }

    div[data-testid="stExpander"]:has(.interactive-lens-marker) summary {
        min-height: 4.45rem !important;
        grid-template-columns: 2.45rem minmax(0, 1fr) auto !important;
        gap: .62rem !important;
        padding: .62rem .68rem !important;
    }

    div[data-testid="stExpander"]:has(.interactive-lens-marker) summary::before {
        width: 2.3rem;
        height: 2.3rem;
        border-radius: .7rem;
    }

    div[data-testid="stExpander"]:has(.interactive-lens-marker) summary p {
        font-size: .82rem !important;
        line-height: 1.42 !important;
    }

    div[data-testid="stExpander"]:has(.interactive-lens-marker) [data-testid="stExpanderDetails"] {
        padding: 0 .76rem .82rem .76rem !important;
    }
}
</style>
"""


def _freshness_counts(entries: Sequence[object]) -> tuple[int, int, int]:
    current = sum(getattr(item, "state", "") == "Current" for item in entries)
    refreshing = sum(
        getattr(item, "state", "") == "Awaiting refresh" for item in entries
    )
    attention = max(len(entries) - current - refreshing, 0)
    return current, refreshing, attention


def _freshness_summary(entries: Sequence[object]) -> str:
    current, refreshing, attention = _freshness_counts(entries)
    parts = [f"{current} current"]
    if refreshing:
        parts.append(f"{refreshing} refreshing")
    if attention:
        parts.append(f"{attention} need attention")
    return " · ".join(parts)


def _freshness_tone(entries: Sequence[object]) -> tuple[str, str]:
    _current, refreshing, attention = _freshness_counts(entries)
    if attention:
        return "attention", "Some information needs attention"
    if refreshing:
        return "refreshing", "Information refresh is in progress"
    return "current", "Information is current"


def _section_label(label: str, summary: object) -> str:
    headline = concise._truncate(summary, 118)
    return label.upper() if not headline else f"{label.upper()} · {headline}"


def _render_interactive_lens(
    *,
    title: str,
    variant: str,
    sections: Sequence[
        tuple[str, str, object, Callable[[], None] | None]
    ],
) -> None:
    profile = concise.ui.surface_profile(variant.title())
    st.markdown(
        '<div class="interactive-lens-head">'
        f'<div class="interactive-lens-kicker">{escape(profile.kicker)} // portfolio lens</div>'
        f'<div class="interactive-lens-title">{escape(title)}</div>'
        '<div class="interactive-lens-hint">Tap a section icon or headline to expand its context.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    for marker_class, label, summary, detail_renderer in sections:
        with st.expander(_section_label(label, summary), expanded=False):
            st.markdown(
                f'<span class="interactive-lens-marker {escape(marker_class)}" aria-hidden="true"></span>',
                unsafe_allow_html=True,
            )
            st.write(concise._clean(summary) or "No additional detail is available.")
            if detail_renderer is not None:
                detail_renderer()


def _render_event_field_details(
    items: Sequence[object],
    records: Sequence[Mapping[str, Any]],
    *,
    field_name: str,
    empty_message: str,
    include_sources: bool = False,
) -> None:
    if not items:
        st.caption(empty_message)
        return
    for index, item in enumerate(items, start=1):
        title = concise._clean(getattr(item, "title", "Market development"))
        detail = concise._clean(getattr(item, field_name, ""))
        st.markdown(f"**{index}. {title}**")
        st.write(detail or "No additional detail is available.")
        if include_sources:
            record = concise.base._matching_record(item, records)
            source_url = (
                concise.base._record_source_url(record)
                if isinstance(record, Mapping)
                else None
            )
            published_at = getattr(item, "published_at", None)
            published = (
                published_at.strftime("%b %d · %H:%M UTC")
                if hasattr(published_at, "strftime")
                else "time unavailable"
            )
            st.caption(
                f"{concise._clean(getattr(item, 'source_type', 'Public'))} source: "
                f"{concise._clean(getattr(item, 'source', 'Unknown'))} · Published {published}"
            )
            if source_url is not None:
                st.markdown(f"[Read original source]({source_url})")
        if index != len(items):
            st.divider()


def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
    """Render a compact source-health signal with full detail on demand."""

    now = datetime.now(timezone.utc)
    market = concise.base.load_live_market_console()
    dashboard = concise.base.load_dashboard_data()
    public_snapshot = concise.base.load_public_event_snapshot()
    try:
        mandate = concise.base.get_mandate_details(
            concise.base.CANONICAL_PORTFOLIO_CODE
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        mandate = None
    entries = concise.base.build_freshness_entries(
        now=now,
        market=market,
        dashboard=dashboard,
        public_snapshot=public_snapshot,
        briefing=briefing,
        mandate=mandate,
    )
    tone, label = _freshness_tone(entries)
    summary = _freshness_summary(entries)
    st.markdown(
        '<div class="information-health '
        f'{escape(tone)}" role="status" aria-live="polite">'
        '<span class="information-health-dot" aria-hidden="true"></span>'
        '<div class="information-health-copy">'
        f'<div class="information-health-label">{escape(label)}</div>'
        f'<div class="information-health-summary">{escape(summary)}</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    with st.expander("Source freshness and timestamps", expanded=False):
        concise.ui.metric_grid(
            tuple((item.label, item.state, item.detail) for item in entries),
            variant=surface,
        )
        st.caption(
            f"The CIO and canonical portfolio roll at {concise.base._schedule_label()}; "
            "market, economic, and public-event sources retain their own timestamps."
        )


def render_today_market_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Render the daily lens as five independently expandable sections."""

    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(
        item for item in snapshot.records if isinstance(item, Mapping)
    )
    items = concise.base.build_today_items(records)
    portfolio_impact = concise._briefing_value(
        briefing,
        "why_it_matters",
        concise._event_portfolio_fallback(items),
        limit=210,
    )
    action = concise._briefing_value(
        briefing,
        "portfolio_decision",
        "No portfolio change is authorized from these developments alone.",
        limit=150,
    )
    concise.ui.page_header(
        "Investment world today",
        "The few daily developments that matter, explained through their investment and portfolio effect.",
        "NOW",
    )
    event_headline = concise._event_headline(items)
    investor_lesson = concise._daily_investor_lesson(items)
    watchlist = concise._event_watchlist(items)

    def render_cio_detail() -> None:
        st.caption(
            f"Decision reference: {concise._decision_reference(briefing)}. "
            "Daily information can inform the CIO process but cannot independently authorize a portfolio change."
        )

    _render_interactive_lens(
        title="Daily investment synopsis",
        variant="today",
        sections=(
            (
                "lens-section-change",
                "What changed",
                event_headline,
                lambda: _render_event_field_details(
                    items,
                    records,
                    field_name="summary",
                    empty_message=snapshot.detail,
                    include_sources=True,
                ),
            ),
            (
                "lens-section-investors",
                "Why investors care",
                investor_lesson,
                lambda: _render_event_field_details(
                    items,
                    records,
                    field_name="affected_investments",
                    empty_message=(
                        "No additional investment-transmission detail is available for this period."
                    ),
                ),
            ),
            (
                "lens-section-portfolio",
                "Portfolio effect",
                portfolio_impact,
                lambda: _render_event_field_details(
                    items,
                    records,
                    field_name="portfolio_lens",
                    empty_message=(
                        "The current information does not independently justify changing the portfolio."
                    ),
                ),
            ),
            (
                "lens-section-cio",
                "CIO response",
                action,
                render_cio_detail,
            ),
            (
                "lens-section-watch",
                "What to watch next",
                watchlist,
                lambda: _render_event_field_details(
                    items,
                    records,
                    field_name="what_to_watch",
                    empty_message=(
                        "Watch rates, earnings expectations, liquidity, and cross-asset confirmation."
                    ),
                ),
            ),
        ),
    )
    st.caption(
        concise.base._daily_caption(snapshot)
        + " Educational context only; headlines cannot alter the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Render the economic synopsis as five independently expandable sections."""

    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(
        item for item in snapshot.records if isinstance(item, Mapping)
    )
    items = concise.base.build_economic_event_items(records)
    dashboard = concise.base.load_dashboard_data()
    economic_picture = concise._truncate(
        concise.base.economic_snapshot_summary(dashboard.readings),
        220,
    )
    portfolio_fallback = concise._truncate(
        concise.economic_portfolio_lens(dashboard.readings),
        210,
    )
    portfolio_impact = concise._briefing_value(
        briefing,
        "why_it_matters",
        portfolio_fallback,
        limit=210,
    )
    action = concise._briefing_value(
        briefing,
        "portfolio_decision",
        "The economic reading remains evidence for the CIO process, not a standalone trade signal.",
        limit=150,
    )
    readings = dashboard.readings
    concise.ui.page_header(
        "Economy and investing",
        "Current economic data, why markets care, and how the evidence reaches the portfolio.",
        "ECON",
    )
    economic_lesson = concise._economic_investor_lesson(readings)
    watchlist = concise._event_watchlist(items)

    def render_economic_change_detail() -> None:
        st.write(economic_picture)
        _render_event_field_details(
            items,
            records,
            field_name="summary",
            empty_message=snapshot.detail,
            include_sources=True,
        )

    def render_economic_transmission_detail() -> None:
        implications = concise.base.economic_investment_implications(
            dashboard.readings
        )
        if not implications:
            st.caption("No additional economic-transmission detail is available.")
            return
        for index, (title, explanation) in enumerate(implications):
            st.markdown(f"**{title}**")
            st.write(explanation)
            if index != len(implications) - 1:
                st.divider()

    def render_portfolio_detail() -> None:
        if portfolio_fallback != portfolio_impact:
            st.caption(f"Economic portfolio lens: {portfolio_fallback}")
        st.caption(
            "Economic evidence reaches the portfolio only through the governed specialist, CIO, and construction process."
        )

    def render_cio_detail() -> None:
        st.caption(
            f"Decision reference: {concise._decision_reference(briefing)}. "
            "The economic reading cannot independently authorize a trade."
        )

    _render_interactive_lens(
        title="Economic synopsis",
        variant="environment",
        sections=(
            (
                "lens-section-change",
                "What changed",
                concise._economic_headline(readings),
                render_economic_change_detail,
            ),
            (
                "lens-section-investors",
                "Why investors care",
                economic_lesson,
                render_economic_transmission_detail,
            ),
            (
                "lens-section-portfolio",
                "Portfolio effect",
                portfolio_impact,
                render_portfolio_detail,
            ),
            (
                "lens-section-cio",
                "CIO response",
                action,
                render_cio_detail,
            ),
            (
                "lens-section-watch",
                "What to watch next",
                watchlist,
                lambda: _render_event_field_details(
                    items,
                    records,
                    field_name="what_to_watch",
                    empty_message=(
                        "Watch growth, inflation, policy rates, yields, liquidity, and earnings confirmation."
                    ),
                ),
            ),
        ),
    )
    st.caption(
        concise.base._daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Educational interpretation only; "
        "the governed CIO process separately determines whether portfolio action is justified."
    )


def install(app_impl: ModuleType) -> None:
    """Install the responsive and information-density refinements once."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original_apply_global_style = app_impl.apply_global_style

    def apply_global_style(*, dark_mode: bool = True) -> None:
        original_apply_global_style(dark_mode=dark_mode)
        st.markdown(_EXPERIENCE_CSS, unsafe_allow_html=True)

    app_impl.apply_global_style = apply_global_style
    app_impl.render_information_freshness = render_information_freshness
    app_impl.render_today_market_brief = render_today_market_brief
    app_impl.render_environment_economic_brief = render_environment_economic_brief
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = [
    "install",
    "render_environment_economic_brief",
    "render_information_freshness",
    "render_today_market_brief",
]
