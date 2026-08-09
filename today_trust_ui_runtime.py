"""Trust-first, compact presentation for the Today surface.

This adapter changes investor-facing presentation only. It does not create or
modify evidence, qualify candidates, change specialist or CIO authority, alter
thresholds or sizing, construct a portfolio, execute a trade, or authorize real
money.

The runtime intentionally separates three concepts that were previously easy to
confuse in the interface:

* the U.S.-listed implementation session versus continuously traded spot crypto;
* when public sources were checked versus when an event was actually published;
* successive opportunity-funnel cohorts versus unrelated coverage counts.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

import streamlit as st

import concise_operating_intelligence_ui as concise


_INSTALLED_KEY = "_capital_intelligence_today_trust_ui_installed"
_RETENTION_ORIGINAL = "_capital_intelligence_today_story_retention_original"

_CSS = """
<style>
/* Today should begin with information, not chrome. Keep the global design
   language while reducing this surface's opening header by roughly one third. */
.surface-today + .compact-surface-head{margin:.2rem 0 .48rem!important;padding:0 .05rem .15rem!important}
.surface-today + .compact-surface-head .surface-head-icon{width:1.86rem!important;height:1.86rem!important;border-radius:.62rem!important}
.surface-today + .compact-surface-head .surface-head-icon svg{width:.98rem!important;height:.98rem!important}
.surface-today + .compact-surface-head h1{font-size:1.48rem!important}
.surface-today + .compact-surface-head p{font-size:.75rem!important;line-height:1.36!important;margin-top:.22rem!important}
.surface-today + .compact-surface-head .surface-head-meta{margin-top:.4rem!important;font-size:.59rem!important}

.ci-trust-strip{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.48rem;margin:.18rem 0 .68rem}
.ci-trust-cell,.ci-compact-card,.ci-funnel-stage{min-width:0;border:1px solid rgba(138,157,188,.16);background:linear-gradient(145deg,rgba(14,21,35,.94),rgba(7,12,22,.94));box-shadow:0 10px 26px rgba(0,0,0,.2)}
.ci-trust-cell{padding:.65rem .72rem;border-radius:.8rem}
.ci-trust-label,.ci-compact-kicker,.ci-funnel-label{font-size:.57rem;font-weight:850;letter-spacing:.11em;text-transform:uppercase;color:var(--surface-accent)}
.ci-trust-value{margin-top:.2rem;font-size:.76rem;line-height:1.35;color:#eaf2fb;font-weight:650}
.ci-trust-note{margin-top:.16rem;font-size:.61rem;line-height:1.35;color:#75869c}

.ci-development-list{display:grid;gap:.48rem;margin:.18rem 0 .7rem}
.ci-compact-card{border-radius:.88rem;padding:.72rem .78rem}
.ci-development-meta{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center;font-size:.57rem;line-height:1.25;text-transform:uppercase;letter-spacing:.06em;color:#708197}
.ci-development-badge{color:var(--surface-accent);font-weight:850}
.ci-development-title{margin:.34rem 0 .3rem;font-size:.94rem;line-height:1.22;color:#f6f9fd;font-weight:690;letter-spacing:-.015em}
.ci-development-copy{font-size:.72rem;line-height:1.43;color:#a9b6c8}

.ci-impact{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,.65fr);gap:.5rem;margin:.18rem 0 .72rem}
.ci-impact .ci-compact-card{border-color:rgba(var(--surface-rgb),.22)}
.ci-impact-copy{margin-top:.32rem;font-size:.75rem;line-height:1.45;color:#c3cfde}
.ci-impact-action{margin-top:.32rem;font-size:.8rem;line-height:1.4;color:#f1f6fb;font-weight:670}

.ci-funnel{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.38rem;margin:.18rem 0 .5rem}
.ci-funnel-stage{position:relative;border-radius:.76rem;padding:.6rem .62rem;min-height:5.3rem}
.ci-funnel-stage:not(:last-child):after{content:"›";position:absolute;right:-.31rem;top:50%;transform:translateY(-50%);z-index:4;color:#60738e;font-size:.92rem}
.ci-funnel-value{margin:.42rem 0 .18rem;font-size:1rem;line-height:1.1;color:#f8fbff;font-weight:720;overflow-wrap:anywhere}
.ci-funnel-note{font-size:.57rem;line-height:1.3;color:#718299}
.ci-funnel-warning{color:#ffc96b!important}
.ci-funnel-foot{font-size:.65rem;line-height:1.42;color:#8090a5;margin:.28rem 0 .7rem}

.ci-watch-compact{display:grid;gap:.28rem;margin:.2rem 0 .68rem}
.ci-watch-row{display:grid;grid-template-columns:1.6rem minmax(0,1fr);gap:.45rem;align-items:start;padding:.48rem .58rem;border:1px solid rgba(138,157,188,.13);border-radius:.72rem;background:rgba(255,255,255,.018);font-size:.7rem;line-height:1.4;color:#aebacd}
.ci-watch-index{color:var(--surface-accent);font-size:.6rem;font-weight:850;letter-spacing:.06em}

@media(max-width:760px){
  /* The four primary tabs remain available and accessible, but the decorative
     brand cell no longer consumes a second sticky-nav column on a phone. */
  div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark){display:block!important;padding:.08rem!important;margin-bottom:.32rem!important;border-radius:.72rem!important;top:max(.16rem,env(safe-area-inset-top,0px))!important}
  div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)>div[data-testid="stColumn"]:has(.nav-brand-mark){display:none!important}
  div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)>div[data-testid="stColumn"]{width:100%!important;min-width:0!important}
  div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) [data-testid="stButtonGroup"] button{min-height:2.22rem!important;padding:.2rem .18rem!important;font-size:clamp(.61rem,2.65vw,.72rem)!important}
  .surface-today + .compact-surface-head{margin:.1rem 0 .34rem!important}
  .surface-today + .compact-surface-head .compact-surface-row{gap:.58rem!important}
  .surface-today + .compact-surface-head .surface-head-icon{width:1.7rem!important;height:1.7rem!important}
  .surface-today + .compact-surface-head h1{font-size:1.3rem!important}
  .surface-today + .compact-surface-head p{font-size:.7rem!important}
  .surface-today + .compact-surface-head .surface-head-meta{display:none!important}
  .ci-trust-strip{grid-template-columns:1fr;gap:.34rem}
  .ci-trust-cell{padding:.56rem .62rem}
  .ci-impact{grid-template-columns:1fr}
  .ci-funnel{grid-template-columns:1fr 1fr;gap:.34rem}
  .ci-funnel-stage{min-height:4.55rem}
  .ci-funnel-stage:not(:last-child):after{display:none}
  .ci-funnel-stage:last-child{grid-column:1/-1}
}
</style>
"""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: object, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]) + "…"


def _time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _age(value: object, *, now: datetime | None = None) -> str:
    parsed = _time(value)
    if parsed is None:
        return "time unavailable"
    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seconds = max((evaluated_at - parsed).total_seconds(), 0.0)
    minutes = int(seconds // 60)
    if minutes < 2:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def market_session_summary(market: Mapping[str, object]) -> str:
    """State the listed-market clock without falsely closing continuous crypto."""

    state = market.get("market_open")
    listed = "open" if state is True else "closed" if state is False else "unavailable"
    return f"U.S. listed session {listed} · direct spot crypto trades 24/7"


def source_timing_label(
    checked_at: object,
    observed_at: object,
    *,
    now: datetime | None = None,
) -> str:
    """Keep retrieval/check recency separate from an event's publication date."""

    checked = _time(checked_at)
    observed = _time(observed_at)
    checked_label = (
        "Sources check unavailable"
        if checked is None
        else f"Sources checked {_age(checked, now=now)}"
    )
    observed_label = (
        "observation date unavailable"
        if observed is None
        else f"observation published {observed.strftime('%b %d, %Y · %H:%M UTC')}"
    )
    return f"{checked_label} · {observed_label}"


def source_health_summary(
    *,
    state: object,
    checked_at: object,
    current_count: int,
    retained_count: int,
    now: datetime | None = None,
) -> str:
    """Describe source health independently from whether a story qualified."""

    evaluated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    checked = _time(checked_at)
    normalized = _clean(state).lower()
    interval_seconds = max(
        60,
        _safe_int(os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_INTERVAL_SECONDS"))
        or 1800,
    )
    freshness_limit = timedelta(seconds=max(3600, interval_seconds * 2))
    if normalized != "available":
        return "Source coverage incomplete"
    if checked is None:
        return "Source check time unavailable"
    if evaluated_at - checked > freshness_limit:
        return f"Source check overdue · last checked {_age(checked, now=evaluated_at)}"
    if current_count > 0:
        noun = "development" if current_count == 1 else "developments"
        return f"Sources current · {current_count} current {noun}"
    if retained_count > 0:
        return "Sources current · no new qualifying developments; prior verified context retained"
    return "Sources current · no new development cleared the relevance controls"


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def opportunity_funnel_stages(snapshot: object) -> tuple[tuple[str, str, str, bool], ...]:
    """Return a truthful ordered funnel and flag impossible downstream counts.

    The five displayed cohorts map directly to the persisted opportunity snapshot:
    broad observation, usable initial market evidence, selected deeper analysis,
    complete governed candidate evidence, and the qualified CIO queue. The UI never
    silently clamps an inconsistent persisted count.
    """

    raw = (
        ("Universe observed", _safe_int(getattr(snapshot, "broad_assets_screened", None)), "Broad governed scan"),
        ("Usable snapshots", _safe_int(getattr(snapshot, "snapshot_covered", None)), "Initial evidence available"),
        ("Deep analysis", _safe_int(getattr(snapshot, "companies_deepened", None)), "Selected for deeper review"),
        ("Evidence complete", _safe_int(getattr(snapshot, "governed_candidates", None)), "Governed candidate package"),
        ("Reached CIO", _safe_int(getattr(snapshot, "opportunities_reaching_cio", None)), "Qualified decision alternatives"),
    )
    result: list[tuple[str, str, str, bool]] = []
    previous: int | None = None
    upstream_valid = True
    for label, value, note in raw:
        inconsistent = bool(
            upstream_valid
            and previous is not None
            and value is not None
            and value > previous
        )
        if inconsistent:
            result.append(
                (
                    label,
                    "Check needed",
                    f"Reported {value:,} exceeds the upstream cohort of {previous:,}.",
                    True,
                )
            )
            upstream_valid = False
        else:
            result.append(
                (
                    label,
                    "Unavailable" if value is None else f"{value:,}",
                    note,
                    False,
                )
            )
        if value is not None:
            previous = value
    return tuple(result)


def _portfolio_impact(
    briefing: Mapping[str, Any] | None,
    items: Sequence[object],
) -> tuple[str, str]:
    event_fallback = " ".join(
        _clean(getattr(item, "portfolio_lens", ""))
        for item in items[:2]
        if _clean(getattr(item, "portfolio_lens", ""))
    )
    impact = concise._briefing_value(
        briefing,
        "why_it_matters",
        event_fallback
        or "The current external information does not independently justify changing portfolio exposure.",
        limit=230,
    )
    action = concise._briefing_value(
        briefing,
        "portfolio_decision",
        "No portfolio change is authorized from these developments alone.",
        limit=155,
    )
    return impact, action


def _render_state_strip(
    market: Mapping[str, object],
    snapshot: object,
    *,
    current_count: int,
    retained_count: int,
    observed_at: object,
) -> None:
    coverage = (
        f"{int(market.get('quote_count', 0) or 0)}/"
        f"{int(market.get('expected_quote_count', 0) or 0)}"
    )
    health = source_health_summary(
        state=getattr(snapshot, "state", "unavailable"),
        checked_at=getattr(snapshot, "evaluated_at", None),
        current_count=current_count,
        retained_count=retained_count,
    )
    timing = source_timing_label(
        getattr(snapshot, "evaluated_at", None),
        observed_at,
    )
    cells = (
        ("Market state", market_session_summary(market), "Listed implementation clock is separate from continuous spot-crypto trading."),
        ("Briefing health", health, "A current source check does not imply that a new story qualified."),
        ("Implementation coverage", f"{coverage} listed quotes", timing),
    )
    markup = "".join(
        '<div class="ci-trust-cell">'
        f'<div class="ci-trust-label">{escape(label)}</div>'
        f'<div class="ci-trust-value">{escape(value)}</div>'
        f'<div class="ci-trust-note">{escape(note)}</div></div>'
        for label, value, note in cells
    )
    st.markdown(f'<section class="ci-trust-strip">{markup}</section>', unsafe_allow_html=True)


def _render_developments(
    items: Sequence[object],
    *,
    retained: bool,
) -> None:
    if not items:
        st.markdown(
            '<section class="ci-compact-card"><div class="ci-compact-kicker">Current developments</div>'
            '<div class="ci-development-title">No new development earned a current briefing slot.</div>'
            '<div class="ci-development-copy">The interface leaves the section quiet rather than treating an empty or low-relevance headline set as an investment signal.</div></section>',
            unsafe_allow_html=True,
        )
        return
    cards: list[str] = []
    for index, item in enumerate(items[:3], start=1):
        badge = "Retained verified context" if retained else f"Development {index:02d}"
        source = _clean(getattr(item, "source", "Public source")) or "Public source"
        published_at = getattr(item, "published_at", None)
        cards.append(
            '<article class="ci-compact-card">'
            '<div class="ci-development-meta">'
            f'<span class="ci-development-badge">{escape(badge)}</span>'
            f'<span>{escape(source)}</span><span>published {escape(_age(published_at))}</span></div>'
            f'<div class="ci-development-title">{escape(_clean(getattr(item, "title", "Market development")))}</div>'
            f'<div class="ci-development-copy">{escape(_truncate(getattr(item, "summary", "No concise detail is available."), 260))}</div>'
            '</article>'
        )
    st.markdown(
        '<section class="ci-development-list">' + "".join(cards) + "</section>",
        unsafe_allow_html=True,
    )


def _render_portfolio_panel(
    briefing: Mapping[str, Any] | None,
    items: Sequence[object],
) -> None:
    impact, action = _portfolio_impact(briefing, items)
    st.markdown(
        '<section class="ci-impact">'
        '<div class="ci-compact-card"><div class="ci-compact-kicker">Portfolio impact</div>'
        f'<div class="ci-impact-copy">{escape(impact)}</div></div>'
        '<div class="ci-compact-card"><div class="ci-compact-kicker">CIO response</div>'
        f'<div class="ci-impact-action">{escape(action)}</div></div></section>',
        unsafe_allow_html=True,
    )


def _render_funnel(operating_ui: ModuleType) -> None:
    snapshot = operating_ui.load_opportunity_scan()
    stages = opportunity_funnel_stages(snapshot)
    markup = "".join(
        '<div class="ci-funnel-stage">'
        f'<div class="ci-funnel-label">{escape(label)}</div>'
        f'<div class="ci-funnel-value{" ci-funnel-warning" if warning else ""}">{escape(value)}</div>'
        f'<div class="ci-funnel-note{" ci-funnel-warning" if warning else ""}">{escape(note)}</div></div>'
        for label, value, note, warning in stages
    )
    strongest = _clean(getattr(snapshot, "strongest_alternative", "Unavailable")) or "Unavailable"
    stage = _clean(getattr(snapshot, "strongest_stage", ""))
    blocker = _clean(getattr(snapshot, "main_reason", ""))
    st.markdown(
        '<div class="section-header"><div><h3>CIO / research funnel</h3>'
        '<p>Each number is one successive cohort; an impossible downstream count is flagged instead of normalized away.</p></div></div>'
        f'<section class="ci-funnel">{markup}</section>'
        f'<div class="ci-funnel-foot"><strong>Strongest alternative:</strong> {escape(strongest)} · {escape(stage)}'
        + (f' · <strong>Main blocker:</strong> {escape(blocker)}' if blocker else "")
        + '</div>',
        unsafe_allow_html=True,
    )


def _render_watch(story_ui: ModuleType, items: Sequence[object]) -> None:
    watches = tuple(story_ui._watch(items)) if items else (
        "Treasury yields and central-bank guidance",
        "Earnings expectations and company guidance",
        "Credit spreads, liquidity, and cross-asset confirmation",
    )
    markup = "".join(
        '<div class="ci-watch-row">'
        f'<div class="ci-watch-index">{index:02d}</div><div>{escape(_clean(value))}</div></div>'
        for index, value in enumerate(watches[:5], start=1)
    )
    st.markdown(
        '<div class="section-header"><div><h3>What to watch next</h3>'
        '<p>Evidence that could confirm, weaken, or reverse the current investment story.</p></div></div>'
        f'<section class="ci-watch-compact">{markup}</section>',
        unsafe_allow_html=True,
    )


def _render_explanation_detail(story_ui: ModuleType, items: Sequence[object]) -> None:
    with st.expander("Why these developments matter", expanded=False):
        if not items:
            st.write("No current development requires an expanded investment explanation.")
            return
        for index, item in enumerate(items, start=1):
            concept, lesson = story_ui._lesson(item)
            why = _clean(getattr(item, "why_it_matters", "")) or lesson
            reaction = _clean(getattr(item, "portfolio_lens", "")) or "Market reaction remains under review."
            exposure = _clean(getattr(item, "affected_investments", "")) or "No distinct exposure identified."
            watch = _clean(getattr(item, "what_to_watch", "")) or "Watch for confirming evidence."
            st.markdown(f"**{index}. {_clean(getattr(item, 'title', 'Market development'))}**")
            st.write(f"**Why it matters:** {why}")
            st.write(f"**How markets may react:** {reaction}")
            st.write(f"**Most directly exposed:** {exposure}")
            st.write(f"**What would confirm or reverse it:** {watch}")
            st.caption(f"Investor concept: {concept} · {lesson}")
            if index != len(items):
                st.divider()


def _render_source_detail(
    operating_ui: ModuleType,
    snapshot: object,
    records: Sequence[Mapping[str, Any]],
    items: Sequence[object],
) -> None:
    with st.expander("Sources and timing", expanded=False):
        checked_at = getattr(snapshot, "evaluated_at", None)
        if not items:
            st.write(
                source_timing_label(checked_at, None)
                + ". No current source-qualified development is displayed."
            )
            return
        for index, item in enumerate(items, start=1):
            published_at = getattr(item, "published_at", None)
            st.markdown(f"**{index}. {_clean(getattr(item, 'title', 'Market development'))}**")
            st.caption(source_timing_label(checked_at, published_at))
            st.caption(
                f"{_clean(getattr(item, 'source_type', 'Public'))} source: "
                f"{_clean(getattr(item, 'source', 'Public source'))}"
            )
            record = operating_ui._matching_record(item, records)
            source_url = (
                operating_ui._record_source_url(record)
                if isinstance(record, Mapping)
                else None
            )
            if source_url is not None:
                st.markdown(f"[Read original source]({source_url})")
            if index != len(items):
                st.divider()


def _final_today_renderer(
    app_impl: ModuleType,
    event_ui: ModuleType,
    operating_ui: ModuleType,
    story_ui: ModuleType,
):
    def render_today(active_app: ModuleType, dependencies: object) -> None:
        del dependencies
        story_ui._styles()
        st.markdown(_CSS, unsafe_allow_html=True)
        briefing = active_app._latest("daily_cio_briefing")
        market = active_app.load_live_market_console()
        if not isinstance(market, Mapping):
            market = {}
        snapshot = operating_ui.load_public_event_snapshot()
        records = tuple(
            record
            for record in getattr(snapshot, "records", ())
            if isinstance(record, Mapping)
        )
        now = datetime.now(timezone.utc)
        retained_builder = operating_ui.build_today_items
        original_builder = getattr(
            retained_builder,
            _RETENTION_ORIGINAL,
            retained_builder,
        )
        current_items = tuple(original_builder(records, now=now, limit=3))
        items = tuple(retained_builder(records, now=now, limit=3))
        retained = not current_items and bool(items)
        observed_at = (
            getattr(items[0], "published_at", None)
            if items
            else None
        )

        active_app.page_header(
            "Investment world today",
            "Market state, material developments, portfolio impact, the CIO research funnel, and the evidence to watch next.",
            "NOW",
        )
        _render_state_strip(
            market,
            snapshot,
            current_count=len(current_items),
            retained_count=len(items) if retained else 0,
            observed_at=observed_at,
        )
        _render_developments(items, retained=retained)
        _render_portfolio_panel(briefing, items)
        _render_funnel(operating_ui)
        _render_watch(story_ui, items)
        _render_explanation_detail(story_ui, items)
        _render_source_detail(operating_ui, snapshot, records, items)
        with st.expander("Live market operating detail", expanded=False):
            active_app.render_live_market_status()
        retention_note = (
            " No new development cleared the current 24-hour controls; prior verified context is shown with its original publication time."
            if retained
            else ""
        )
        st.caption(
            concise.base._daily_caption(snapshot)
            + retention_note
            + " Today is informational only; holdings and CIO-authorized actions remain governed by the Portfolio and canonical decision records."
        )

    return render_today


def install(
    app_impl: ModuleType,
    event_ui: ModuleType,
    operating_ui: ModuleType,
    story_ui: ModuleType,
) -> None:
    """Install after Today retention and before primary-surface route isolation."""

    story_ui._render_today = _final_today_renderer(
        app_impl,
        event_ui,
        operating_ui,
        story_ui,
    )
    setattr(app_impl, _INSTALLED_KEY, True)


__all__ = [
    "install",
    "market_session_summary",
    "opportunity_funnel_stages",
    "source_health_summary",
    "source_timing_label",
]
