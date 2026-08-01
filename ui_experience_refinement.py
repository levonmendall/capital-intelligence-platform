"""Second-stage presentation refinements for the investor-facing console.

The module improves responsive layout and information clarity only. It does not
read, score, size, approve, construct, or execute an investment decision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

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


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Render the economic synopsis without repeating the macro metric grid."""

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
    concise.ui.investment_lens_card(
        title="Economic synopsis",
        what_changed=concise._economic_headline(readings),
        why_investors_care=economic_lesson,
        portfolio_effect=portfolio_impact,
        cio_response=action,
        watch_next=watchlist,
        variant="environment",
    )
    with st.expander("Explore the economic investment context", expanded=False):
        concise._render_lens_context(
            what_changed=economic_picture,
            why_investors_care=economic_lesson,
            portfolio_effect=portfolio_impact,
            cio_response=action,
            watch_next=watchlist,
        )
        st.divider()
        st.markdown("#### How the economy reaches investments")
        for title, explanation in concise.base.economic_investment_implications(
            dashboard.readings
        ):
            st.markdown(f"**{title}**")
            st.write(explanation)
        if items:
            st.divider()
            st.markdown("#### Recent economic and policy developments")
            concise._render_event_detail(items, records, briefing)
        else:
            st.caption(snapshot.detail)
        st.caption(f"Portfolio impact: {portfolio_impact} · CIO action: {action}")
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
    app_impl.render_environment_economic_brief = render_environment_economic_brief
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = [
    "install",
    "render_environment_economic_brief",
    "render_information_freshness",
]
