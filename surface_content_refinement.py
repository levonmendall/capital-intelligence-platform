"""Distinct, current, and educational Today and Environment surfaces.

Today is an editorial briefing about the latest material developments and the
mechanisms through which they may affect markets. Environment is a structural
dashboard for growth, inflation, rates, liquidity, and cross-asset sensitivity.

This module changes presentation only. It cannot authorize a candidate, alter a
CIO conclusion, size a position, construct a portfolio, or execute a paper trade.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

import streamlit as st

import concise_operating_intelligence_ui as concise
import ui_experience_refinement as experience


_INSTALLED_STATE_KEY = "_capital_intelligence_distinct_surface_content_installed"
_SURFACE_FRESHNESS_LABELS = {
    "today": frozenset({"Market quotes", "Public events"}),
    "environment": frozenset({"Market quotes", "Economic data"}),
    "portfolio": frozenset({"CIO conclusion", "Portfolio valuation"}),
}
_SURFACE_FRESHNESS_NAMES = {
    "today": "Market and event sources",
    "environment": "Economic and market sources",
    "portfolio": "Portfolio records",
}

_CHANNEL_LABELS = {
    "growth": "Growth",
    "earnings": "Earnings",
    "demand": "Demand",
    "inflation": "Inflation",
    "policy": "Policy",
    "discount_rate": "Discount rates",
    "liquidity": "Liquidity",
    "credit": "Credit",
    "supply": "Supply",
    "commodity": "Commodities",
    "currency": "Currencies",
    "volatility": "Volatility",
    "positioning": "Positioning",
    "sentiment": "Risk appetite",
    "regulation": "Regulation",
    "geopolitical": "Geopolitics",
    "operational": "Operations",
    "cyber": "Cyber risk",
    "climate_weather": "Weather",
    "counterparty": "Counterparty risk",
}

_CONCEPTS = (
    (
        frozenset({"policy", "discount_rate", "inflation", "liquidity"}),
        "Discount rates",
        (
            "Asset prices reflect future cash flows in today's dollars. When required "
            "returns or bond yields rise, distant cash flows become less valuable, so "
            "long-duration bonds and growth stocks can be especially sensitive."
        ),
    ),
    (
        frozenset({"growth", "demand", "earnings"}),
        "Earnings expectations",
        (
            "Markets move on changes in expected profits, not only current results. "
            "Stronger demand can lift revenue and credit quality; weaker demand can "
            "pressure cyclical companies and lower-quality borrowers."
        ),
    ),
    (
        frozenset({"credit", "counterparty", "volatility", "positioning", "sentiment"}),
        "Risk premiums",
        (
            "Investors demand extra return for uncertainty, illiquidity, or default risk. "
            "When that premium rises, credit spreads and volatility often increase while "
            "risk-asset valuations fall."
        ),
    ),
    (
        frozenset({"supply", "commodity", "climate_weather"}),
        "Input-cost transmission",
        (
            "Supply disruptions can raise commodity and transportation costs. Producers "
            "may benefit while companies that consume those inputs can face lower margins "
            "and renewed inflation pressure."
        ),
    ),
    (
        frozenset({"currency"}),
        "Currency translation",
        (
            "Exchange-rate moves change the home-currency value of foreign revenue and "
            "assets. A stronger dollar can pressure overseas earnings translated into "
            "dollars while reducing some imported inflation."
        ),
    ),
    (
        frozenset({"regulation", "geopolitical", "operational", "cyber"}),
        "Event risk",
        (
            "Policy and disruption risks create uneven outcomes. The investment question "
            "is not whether an event sounds important, but whether it changes cash flows, "
            "financing conditions, liquidity, or the range of plausible outcomes."
        ),
    ),
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object, fallback: str) -> str:
    return _clean(value) or fallback


def _joined(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return _clean(value) or fallback
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [_clean(item) for item in value if _clean(item)]
        return " • ".join(dict.fromkeys(values)) if values else fallback
    return fallback


def _unique(values: Iterable[object], *, limit: int | None = None) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        key = text.casefold().strip(" .,;:–—-")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if limit is not None and len(result) >= limit:
            break
    return tuple(result)


def _count_label(value: object) -> str:
    """Format governed funnel counts without depending on private helpers."""

    if isinstance(value, bool) or value is None:
        return "Unavailable"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "Unavailable"


def _market_session(snapshot: Mapping[str, object]) -> str:
    state = snapshot.get("market_open")
    return "Open" if state is True else "Closed" if state is False else "Unavailable"


def _coverage(snapshot: Mapping[str, object]) -> str:
    return (
        f"{int(snapshot.get('quote_count', 0) or 0)}/"
        f"{int(snapshot.get('expected_quote_count', 0) or 0)}"
    )


def _format_source_time(value: datetime | None) -> str:
    if value is None:
        return "Source time unavailable"
    return value.astimezone(timezone.utc).strftime("%b %d · %H:%M UTC")


def _age_label(value: datetime | None, *, now: datetime | None = None) -> str:
    if value is None:
        return "time unavailable"
    evaluated_at = now or datetime.now(timezone.utc)
    seconds = max(0.0, (evaluated_at - value.astimezone(timezone.utc)).total_seconds())
    minutes = int(seconds // 60)
    if minutes < 2:
        return "just verified"
    if minutes < 60:
        return f"verified {minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"verified {hours}h ago"
    return f"verified {hours // 24}d ago"


def _channel_labels(item: object, *, limit: int = 4) -> tuple[str, ...]:
    raw = getattr(item, "impact_channels", ())
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, Sequence):
        return ()
    labels = (
        _CHANNEL_LABELS.get(_clean(channel).lower(), _clean(channel).replace("_", " ").title())
        for channel in raw
    )
    return _unique(labels, limit=limit)


def _concept_for_item(item: object) -> tuple[str, str]:
    channels = frozenset(
        _clean(channel).lower()
        for channel in getattr(item, "impact_channels", ())
        if _clean(channel)
    )
    for required, title, explanation in _CONCEPTS:
        if channels & required:
            return title, explanation
    return (
        "Transmission channels",
        (
            "A development matters to investors when it changes expected cash flows, "
            "required returns, liquidity, or the range of potential outcomes. Price "
            "movement without one of those links may be noise rather than new information."
        ),
    )


def _source_url(item: object, records: Sequence[Mapping[str, Any]]) -> str | None:
    record = concise.base._matching_record(item, records)
    if not isinstance(record, Mapping):
        return None
    return concise.base._record_source_url(record)


def _freshness_entries(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> tuple[object, ...]:
    mandate = None
    if surface == "portfolio":
        try:
            mandate = concise.base.get_mandate_details(
                concise.base.CANONICAL_PORTFOLIO_CODE
            )
        except (OSError, RuntimeError, TypeError, ValueError):
            mandate = None
    entries = concise.base.build_freshness_entries(
        now=datetime.now(timezone.utc),
        market=concise.base.load_live_market_console(),
        dashboard=concise.base.load_dashboard_data(),
        public_snapshot=concise.base.load_public_event_snapshot(),
        briefing=briefing,
        mandate=mandate,
    )
    allowed = _SURFACE_FRESHNESS_LABELS.get(surface)
    if allowed is None:
        return tuple(entries)
    return tuple(item for item in entries if getattr(item, "label", "") in allowed)


def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
    """Show only the source timestamps that power the active surface."""

    entries = _freshness_entries(briefing=briefing, surface=surface)
    tone, _ = experience._freshness_tone(entries)
    subject = _SURFACE_FRESHNESS_NAMES.get(surface, "Information")
    label = {
        "attention": f"{subject} need attention",
        "refreshing": f"{subject} are refreshing",
    }.get(tone, f"{subject} are current")
    summary = experience._freshness_summary(entries)
    st.markdown(
        '<div class="story-source-health '
        f'{escape(tone)}" role="status" aria-live="polite">'
        '<span class="story-source-dot" aria-hidden="true"></span>'
        '<div><div class="story-source-label">'
        f'{escape(label)}</div><div class="story-source-copy">{escape(summary)}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )
    detail_label = {
        "today": "Today source timestamps",
        "environment": "Environment source timestamps",
        "portfolio": "Portfolio record timestamps",
    }.get(surface, "Source freshness and timestamps")
    with st.expander(detail_label, expanded=False):
        concise.ui.metric_grid(
            tuple((item.label, item.state, item.detail) for item in entries),
            variant=surface,
        )
        st.caption(
            "These are the timestamps used by this page. A stale or incomplete source "
            "is labelled rather than silently presented as current."
        )


def _install_story_styles() -> None:
    st.markdown(
        """
<style>
.story-source-health{
  display:flex;align-items:flex-start;gap:.72rem;margin:.25rem 0 1rem;
  padding:.72rem .85rem;border:1px solid rgba(138,157,188,.14);
  border-radius:15px;background:rgba(10,16,28,.68);
}
.story-source-dot{width:.52rem;height:.52rem;border-radius:50%;margin-top:.28rem;
  background:#52e3a4;box-shadow:0 0 14px rgba(82,227,164,.55);flex:0 0 auto}
.story-source-health.attention .story-source-dot{background:#ffc96b;
  box-shadow:0 0 14px rgba(255,201,107,.55)}
.story-source-health.refreshing .story-source-dot{background:#56e0ff;
  box-shadow:0 0 14px rgba(86,224,255,.55)}
.story-source-label{font-size:.73rem;line-height:1.2;font-weight:820;letter-spacing:.08em;
  text-transform:uppercase;color:#dce7f6}
.story-source-copy{font-size:.78rem;line-height:1.45;color:#8492a8;margin-top:.16rem}

.today-editorial{position:relative;overflow:hidden;border:1px solid rgba(86,224,255,.2);
  border-radius:24px;padding:1.2rem;background:
  radial-gradient(circle at 92% 8%,rgba(86,224,255,.12),transparent 17rem),
  linear-gradient(145deg,rgba(14,22,37,.96),rgba(8,13,24,.96));
  box-shadow:0 22px 55px rgba(0,0,0,.28);margin:.35rem 0 1rem}
.today-editorial:before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;
  background:linear-gradient(180deg,#56e0ff,#5b7cff 55%,transparent)}
.today-editorial-head{display:flex;justify-content:space-between;gap:1rem;align-items:flex-start;
  padding:.1rem .2rem 1rem;border-bottom:1px solid rgba(138,157,188,.12)}
.today-editorial-kicker,.environment-kicker{font-size:.68rem;font-weight:850;letter-spacing:.14em;
  text-transform:uppercase;color:#56e0ff}
.today-editorial h2,.environment-regime h2{font-size:clamp(1.45rem,3vw,2.25rem);
  line-height:1.08;letter-spacing:-.035em;color:#f8fafc;margin:.35rem 0 .45rem}
.today-editorial-deck,.environment-regime-copy{font-size:.92rem;line-height:1.62;color:#a7b4c7;
  max-width:55rem}
.today-session{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:.42rem}
.today-chip,.story-tag{display:inline-flex;align-items:center;padding:.36rem .58rem;border-radius:999px;
  border:1px solid rgba(138,157,188,.16);background:rgba(255,255,255,.025);
  color:#b8c5d8;font-size:.68rem;font-weight:700}
.today-primary{padding:1.15rem .2rem .2rem}
.story-meta{display:flex;flex-wrap:wrap;gap:.42rem;align-items:center;font-size:.68rem;
  color:#7f8da3;text-transform:uppercase;letter-spacing:.07em}
.story-rank{color:#56e0ff;font-weight:850}
.today-primary-title{font-size:clamp(1.35rem,2.7vw,2rem);line-height:1.15;
  letter-spacing:-.028em;color:#fff;margin:.55rem 0 .8rem;max-width:62rem}
.story-explanation-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.72rem}
.story-explanation{min-width:0;padding:.82rem;border:1px solid rgba(138,157,188,.12);
  border-radius:16px;background:rgba(255,255,255,.022)}
.story-explanation-label{font-size:.65rem;font-weight:850;letter-spacing:.11em;
  text-transform:uppercase;color:#56e0ff;margin-bottom:.35rem}
.story-explanation p{font-size:.82rem;line-height:1.55;color:#c1ccdb;margin:0}
.story-tags{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.8rem}
.today-secondary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.78rem;
  margin:0 0 1rem}
.today-story-card{position:relative;min-width:0;padding:1rem;border-radius:19px;
  border:1px solid rgba(138,157,188,.14);background:linear-gradient(145deg,
  rgba(13,20,34,.92),rgba(9,14,25,.92));box-shadow:0 14px 34px rgba(0,0,0,.18)}
.today-story-card h3{font-size:1.05rem;line-height:1.28;color:#f4f8fd;margin:.45rem 0 .62rem}
.today-story-card .story-copy{font-size:.8rem;line-height:1.52;color:#aeb9c9;margin:.35rem 0}
.story-copy strong{color:#e8eef7;font-weight:780}
.today-watch-panel{display:grid;grid-template-columns:minmax(0,.68fr) minmax(0,1.32fr);
  gap:.85rem;align-items:stretch;margin:0 0 1rem}
.today-watch-card,.today-learning-card{border-radius:19px;padding:1rem;
  border:1px solid rgba(138,157,188,.14);background:rgba(11,17,29,.85)}
.today-watch-card h3,.today-learning-card h3,.research-radar h3{
  font-size:.92rem;color:#f1f6fc;margin:.25rem 0 .65rem}
.watch-row{display:flex;gap:.58rem;padding:.52rem 0;border-top:1px solid rgba(138,157,188,.1);
  color:#b8c4d3;font-size:.8rem;line-height:1.48}
.watch-row:first-of-type{border-top:0}.watch-index{color:#56e0ff;font-weight:850}
.learning-concept{font-size:.68rem;font-weight:850;letter-spacing:.1em;text-transform:uppercase;
  color:#9b7cff;margin-bottom:.38rem}
.today-learning-card p{font-size:.82rem;line-height:1.58;color:#b8c4d3;margin:0}
.research-radar{border-radius:21px;padding:1rem;border:1px solid rgba(91,124,255,.2);
  background:linear-gradient(145deg,rgba(91,124,255,.08),rgba(10,16,28,.82));margin-bottom:1rem}
.radar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.65rem}
.radar-cell{min-width:0;padding:.72rem;border-radius:14px;background:rgba(255,255,255,.025);
  border:1px solid rgba(138,157,188,.1)}
.radar-wide{grid-column:span 2}
.radar-label{font-size:.64rem;text-transform:uppercase;letter-spacing:.09em;color:#7f8da3;
  font-weight:800}.radar-value{font-size:.92rem;color:#e9f0fa;font-weight:760;margin-top:.28rem;
  line-height:1.35}.radar-note{font-size:.72rem;color:#8e9db2;line-height:1.42;margin-top:.24rem}

.environment-dashboard{margin:.35rem 0 1rem}
.environment-regime{position:relative;overflow:hidden;padding:1.15rem 1.2rem;border-radius:23px;
  border:1px solid rgba(82,227,164,.22);background:
  radial-gradient(circle at 86% 0%,rgba(82,227,164,.13),transparent 18rem),
  linear-gradient(145deg,rgba(12,24,31,.96),rgba(8,15,25,.96));margin-bottom:.82rem}
.environment-kicker{color:#52e3a4}.environment-regime-meta{display:flex;flex-wrap:wrap;
  gap:.42rem;margin-top:.72rem}
.environment-driver-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.68rem}
.environment-driver{min-width:0;padding:.92rem;border-radius:18px;
  border:1px solid rgba(138,157,188,.13);background:linear-gradient(150deg,
  rgba(13,21,32,.94),rgba(9,14,23,.94))}
.driver-top{display:flex;justify-content:space-between;gap:.5rem;align-items:flex-start}
.driver-name{font-size:.68rem;font-weight:850;letter-spacing:.1em;text-transform:uppercase;
  color:#52e3a4}.driver-state{font-size:.63rem;font-weight:760;color:#9aabbe;text-align:right}
.driver-value{font-size:1.32rem;line-height:1.08;color:#f7fbff;font-weight:780;margin:.55rem 0}
.driver-why,.driver-markets{font-size:.74rem;line-height:1.47;color:#93a2b6;margin-top:.5rem}
.driver-why strong,.driver-markets strong{color:#dbe5f1}
.environment-transmission{margin:1rem 0;border-radius:21px;padding:1rem;
  border:1px solid rgba(82,227,164,.16);background:rgba(9,16,25,.78)}
.environment-transmission-head{display:flex;justify-content:space-between;gap:.8rem;
  align-items:flex-end;margin-bottom:.75rem}
.environment-transmission h3{font-size:.95rem;color:#f3f8fd;margin:0}
.environment-transmission p{font-size:.74rem;color:#8796aa;margin:0}
.market-map{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.58rem}
.market-map-card{min-width:0;padding:.72rem;border-radius:14px;border:1px solid rgba(138,157,188,.1);
  background:rgba(255,255,255,.02)}
.market-map-name{font-size:.68rem;font-weight:850;text-transform:uppercase;letter-spacing:.09em;
  color:#ffc96b}.market-map-copy{font-size:.75rem;line-height:1.48;color:#acb8c8;margin-top:.35rem}
.environment-learning{display:grid;grid-template-columns:.62fr 1.38fr;gap:.75rem;margin:0 0 1rem}
.environment-learning-card,.environment-change-card{padding:.95rem;border-radius:18px;
  border:1px solid rgba(138,157,188,.13);background:rgba(10,17,27,.82)}
.environment-learning-card h3,.environment-change-card h3{font-size:.9rem;color:#f1f6fb;
  margin:.2rem 0 .6rem}.environment-learning-card p,.environment-change-card p{
  font-size:.79rem;line-height:1.55;color:#aeb9c8;margin:0}

@media (max-width: 900px){
  .environment-driver-grid,.market-map{grid-template-columns:repeat(2,minmax(0,1fr))}
  .story-explanation-grid{grid-template-columns:1fr}
}
@media (max-width: 720px){
  .today-editorial,.environment-regime{border-radius:19px;padding:.95rem}
  .today-editorial-head,.environment-transmission-head{display:block}
  .today-session{justify-content:flex-start;margin-top:.7rem}
  .today-secondary-grid,.today-watch-panel,.environment-learning{grid-template-columns:1fr}
  .environment-driver-grid,.market-map,.radar-grid{grid-template-columns:1fr}
  .radar-wide{grid-column:auto}
  .today-story-card,.environment-driver,.market-map-card{min-width:0}
  .story-explanation{padding:.72rem}
  .today-primary-title{font-size:1.32rem}
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _render_story_tags(item: object) -> str:
    tags = [
        *_channel_labels(item),
        _clean(getattr(item, "affected_investments", "")),
    ]
    return "".join(
        f'<span class="story-tag">{escape(tag)}</span>'
        for tag in _unique(tags, limit=5)
    )


def _render_primary_story(
    item: object,
    *,
    rank: int,
) -> str:
    concept, lesson = _concept_for_item(item)
    del concept
    source = _clean(getattr(item, "source", "Public source")) or "Public source"
    source_type = _clean(getattr(item, "source_type", "Public")) or "Public"
    published_at = getattr(item, "published_at", None)
    return (
        '<div class="today-primary">'
        '<div class="story-meta">'
        f'<span class="story-rank">Most material story · {rank:02d}</span>'
        f'<span>{escape(source_type)} · {escape(source)}</span>'
        f'<span>{escape(_age_label(published_at))}</span>'
        "</div>"
        f'<div class="today-primary-title">{escape(_clean(getattr(item, "title", "")))}</div>'
        '<div class="story-explanation-grid">'
        '<div class="story-explanation"><div class="story-explanation-label">What happened</div>'
        f'<p>{escape(_clean(getattr(item, "summary", "")))}</p></div>'
        '<div class="story-explanation"><div class="story-explanation-label">Why it matters</div>'
        f'<p>{escape(lesson)}</p></div>'
        '<div class="story-explanation"><div class="story-explanation-label">How markets may react</div>'
        f'<p>{escape(_clean(getattr(item, "portfolio_lens", "")))}</p></div>'
        "</div>"
        f'<div class="story-tags">{_render_story_tags(item)}</div>'
        "</div>"
    )


def _render_secondary_story(item: object, *, rank: int) -> str:
    concept, lesson = _concept_for_item(item)
    source = _clean(getattr(item, "source", "Public source")) or "Public source"
    published_at = getattr(item, "published_at", None)
    return (
        '<article class="today-story-card">'
        '<div class="story-meta">'
        f'<span class="story-rank">Story {rank:02d}</span>'
        f'<span>{escape(_age_label(published_at))}</span></div>'
        f'<h3>{escape(_clean(getattr(item, "title", "")))}</h3>'
        f'<div class="story-copy"><strong>What happened:</strong> '
        f'{escape(_clean(getattr(item, "summary", "")))}</div>'
        f'<div class="story-copy"><strong>Market impact:</strong> '
        f'{escape(_clean(getattr(item, "portfolio_lens", "")))}</div>'
        f'<div class="story-copy"><strong>Investor lesson — {escape(concept)}:</strong> '
        f'{escape(lesson)}</div>'
        f'<div class="story-tags">{_render_story_tags(item)}</div>'
        f'<div class="story-copy">{escape(source)}</div>'
        "</article>"
    )


def _watch_items(items: Sequence[object]) -> tuple[str, ...]:
    watches: list[str] = []
    for item in items:
        raw = _clean(getattr(item, "what_to_watch", ""))
        if not raw:
            continue
        for part in raw.split(","):
            watches.append(part.strip())
    return _unique(watches, limit=5) or (
        "Treasury yields and central-bank guidance",
        "Earnings expectations and company guidance",
        "Credit spreads, liquidity, and market breadth",
    )


def _render_sources(
    items: Sequence[object],
    records: Sequence[Mapping[str, Any]],
    *,
    snapshot: object,
) -> None:
    with st.expander("Original sources and full event context", expanded=False):
        if not items:
            st.write(_plain(getattr(snapshot, "detail", ""), "No source-qualified event is available."))
            return
        for index, item in enumerate(items, start=1):
            source_url = _source_url(item, records)
            st.markdown(f"**{index}. {_clean(getattr(item, 'title', 'Market development'))}**")
            st.write(_clean(getattr(item, "summary", "")))
            st.caption(
                f"{_clean(getattr(item, 'source_type', 'Public'))} source: "
                f"{_clean(getattr(item, 'source', 'Public source'))} · published "
                f"{_format_source_time(getattr(item, 'published_at', None))}"
            )
            if source_url:
                st.markdown(f"[Read original source]({source_url})")
            if index != len(items):
                st.divider()


def _render_today_research_radar() -> None:
    snapshot = concise.base.load_opportunity_scan()
    cells = (
        (
            "Research coverage",
            _count_label(snapshot.broad_assets_screened),
            "Assets observed by the broad scan.",
        ),
        (
            "Evidence-complete candidates",
            _count_label(snapshot.governed_candidates),
            "Candidates with governed evidence.",
        ),
        (
            "Reached CIO queue",
            _count_label(snapshot.opportunities_reaching_cio),
            "Qualified alternatives reaching decision review.",
        ),
    )
    st.markdown(
        '<section class="research-radar" aria-label="Research radar">'
        '<div class="story-meta"><span class="story-rank">Research radar</span>'
        f'<span>As of {escape(concise.ui.format_datetime(snapshot.as_of))}</span></div>'
        '<h3>What the opportunity process is finding</h3>'
        f'<div class="radar-grid">{"".join(
            "<div class=\"radar-cell\">"
            f"<div class=\"radar-label\">{escape(label)}</div>"
            f"<div class=\"radar-value\">{escape(value)}</div>"
            f"<div class=\"radar-note\">{escape(note)}</div></div>"
            for label, value, note in cells
        )}</div>'
        '<div class="radar-grid" style="margin-top:.65rem">'
        '<div class="radar-cell"><div class="radar-label">Strongest alternative</div>'
        f'<div class="radar-value">{escape(snapshot.strongest_alternative)}</div>'
        f'<div class="radar-note">{escape(snapshot.strongest_stage)}</div></div>'
        '<div class="radar-cell radar-wide">'
        '<div class="radar-label">Main reason it did not advance</div>'
        f'<div class="radar-value">{escape(snapshot.main_reason)}</div>'
        '<div class="radar-note">Research status, not a portfolio instruction.</div></div>'
        "</div></section>",
        unsafe_allow_html=True,
    )
    with st.expander("Research funnel detail", expanded=False):
        concise.ui.metric_grid(
            (
                (
                    "Broad assets screened",
                    _count_label(snapshot.broad_assets_screened),
                    "Complete eligible-universe scan",
                ),
                (
                    "Market snapshots",
                    _count_label(snapshot.snapshot_covered),
                    "Usable initial evidence",
                ),
                (
                    "Companies deepened",
                    _count_label(snapshot.companies_deepened),
                    "Full company analysis",
                ),
                (
                    "Governed candidates",
                    _count_label(snapshot.governed_candidates),
                    "Complete candidate evidence",
                ),
                (
                    "Reached CIO queue",
                    _count_label(snapshot.opportunities_reaching_cio),
                    "Qualified opportunities",
                ),
            ),
            variant="today",
        )
        st.caption(
            f"Production context {snapshot.decision_reference}. {snapshot.detail}"
        )


def render_today_market_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
    live_market: Mapping[str, object] | None = None,
) -> None:
    """Render a ranked, source-timestamped explanation of today's market story."""

    del briefing
    _install_story_styles()
    market = live_market or concise.base.load_live_market_console()
    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = concise.base.build_today_items(records, limit=3)
    source_time = getattr(snapshot, "evaluated_at", None)
    session = _market_session(market)
    coverage = _coverage(market)

    hero_head = (
        '<section class="today-editorial" aria-label="Today market story">'
        '<div class="today-editorial-head"><div>'
        '<div class="today-editorial-kicker">Today // ranked by recency, reliability and materiality</div>'
        '<h2>What is moving the investment conversation</h2>'
        '<div class="today-editorial-deck">'
        "Only source-qualified developments from the last 24 hours appear here. "
        "Each story separates the fact, the investment mechanism, and the possible "
        "market reaction so headlines are not mistaken for trading signals."
        '</div></div><div class="today-session">'
        f'<span class="today-chip">Market {escape(session.lower())}</span>'
        f'<span class="today-chip">{escape(coverage)} governed quotes</span>'
        f'<span class="today-chip">{escape(_age_label(source_time))}</span>'
        "</div></div>"
    )
    if items:
        hero_body = _render_primary_story(items[0], rank=1)
    else:
        detail = _plain(
            getattr(snapshot, "detail", ""),
            (
                "No development in the last 24 hours cleared the recency, reliability, "
                "materiality, and investment-relevance controls."
            ),
        )
        hero_body = (
            '<div class="today-primary"><div class="story-meta">'
            '<span class="story-rank">Quiet-day conclusion</span></div>'
            '<div class="today-primary-title">No new story earned investor attention.</div>'
            '<div class="story-explanation"><div class="story-explanation-label">'
            'Why this is useful</div>'
            f'<p>{escape(detail)} A quiet result is more trustworthy than filling the page '
            "with low-quality or repetitive headlines.</p></div></div>"
        )
    st.markdown(hero_head + hero_body + "</section>", unsafe_allow_html=True)

    if items:
        if len(items) > 1:
            st.markdown(
                '<section class="today-secondary-grid" aria-label="Additional market stories">'
                + "".join(
                    _render_secondary_story(item, rank=index)
                    for index, item in enumerate(items[1:], start=2)
                )
                + "</section>",
                unsafe_allow_html=True,
            )
        concept, lesson = _concept_for_item(items[0])
        watches = _watch_items(items)
        st.markdown(
            '<section class="today-watch-panel">'
            '<div class="today-watch-card"><div class="story-meta">'
            '<span class="story-rank">What to watch next</span></div><h3>'
            "Evidence that can confirm or reverse today's story</h3>"
            + "".join(
                f'<div class="watch-row"><span class="watch-index">{index:02d}</span>'
                f'<span>{escape(item)}</span></div>'
                for index, item in enumerate(watches, start=1)
            )
            + '</div><div class="today-learning-card">'
            '<div class="story-meta"><span class="story-rank">Investor lesson</span></div>'
            f'<h3>{escape(concept)}</h3><div class="learning-concept">Learn the mechanism</div>'
            f'<p>{escape(lesson)}</p></div></section>',
            unsafe_allow_html=True,
        )

    _render_sources(items, records, snapshot=snapshot)
    st.caption(
        concise.base._daily_caption(snapshot)
        + " Educational interpretation only. Today explains external developments; "
        "current holdings and CIO-authorized actions remain in Portfolio."
    )


def _score_state(value: object, *, positive: str, neutral: str, negative: str) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "Evidence incomplete"
    if score >= 0.25:
        return positive
    if score <= -0.25:
        return negative
    return neutral


def _driver_cards(dashboard: object, live_market: Mapping[str, object]) -> tuple[tuple[str, str, str, str, str], ...]:
    readings = getattr(dashboard, "readings", None)
    snapshot = getattr(dashboard, "snapshot", None)

    unemployment = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'unemployment_rate', 0.0)):.1f}%"
    )
    inflation = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'inflation_rate', 0.0)):.2f}%"
    )
    policy_rate = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'federal_funds_rate', 0.0)):.2f}%"
    )
    curve = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'yield_curve_spread', 0.0)):+.2f} pp"
    )

    growth_state = _score_state(
        getattr(snapshot, "growth", None),
        positive="Supportive",
        neutral="Mixed",
        negative="Soft",
    )
    inflation_state = _score_state(
        getattr(snapshot, "inflation", None),
        positive="Elevated pressure",
        neutral="Balanced",
        negative="Disinflationary",
    )
    if readings is None:
        rates_state = "Evidence incomplete"
    else:
        spread = float(getattr(readings, "yield_curve_spread", 0.0))
        rates_state = "Upward curve" if spread > 0.15 else "Inverted curve" if spread < -0.15 else "Flat curve"
    liquidity_score = None
    if snapshot is not None:
        try:
            liquidity_score = -(
                float(getattr(snapshot, "credit", 0.0))
                + float(getattr(snapshot, "volatility", 0.0))
            ) / 2.0
        except (TypeError, ValueError):
            liquidity_score = None
    liquidity_state = _score_state(
        liquidity_score,
        positive="Supportive",
        neutral="Mixed",
        negative="Restrictive",
    )
    liquidity_value = (
        f"{_coverage(live_market)} quotes"
        if live_market.get("status") in {"connected", "partial"}
        else "Evidence incomplete"
    )

    return (
        (
            "Growth",
            unemployment,
            growth_state,
            "Labor demand and activity shape revenue, earnings, defaults, and cyclical demand.",
            "Most sensitive: cyclical equities, small caps, credit, and consumer sectors.",
        ),
        (
            "Inflation",
            inflation,
            inflation_state,
            "Inflation changes real purchasing power, company margins, and the path of interest rates.",
            "Most sensitive: bonds, growth equities, commodities, and inflation hedges.",
        ),
        (
            "Rates",
            f"{policy_rate} · curve {curve}",
            rates_state,
            "Policy and market yields set financing costs and the discount rate used to value assets.",
            "Most sensitive: Treasuries, long-duration equities, housing, banks, and the dollar.",
        ),
        (
            "Liquidity",
            liquidity_value,
            liquidity_state,
            "Liquidity and credit conditions determine how easily risk can be financed or sold.",
            "Most sensitive: credit spreads, smaller companies, volatility, and crowded positions.",
        ),
    )


def _environment_market_map(cards: Sequence[tuple[str, str, str, str, str]]) -> tuple[tuple[str, str], ...]:
    states = {name: state for name, _, state, _, _ in cards}
    return (
        (
            "Equities",
            (
                f"Growth is {states.get('Growth', 'mixed').lower()} while rates are "
                f"{states.get('Rates', 'mixed').lower()}. Earnings support helps, but "
                "higher discount rates can limit valuation upside."
            ),
        ),
        (
            "Bonds",
            (
                f"Inflation is {states.get('Inflation', 'mixed').lower()}. Falling inflation "
                "or weaker growth generally supports duration; persistent inflation can keep "
                "yields and price volatility elevated."
            ),
        ),
        (
            "Credit",
            (
                f"Liquidity is {states.get('Liquidity', 'mixed').lower()}. Strong growth and "
                "easy funding can compress spreads, while weaker activity or tighter funding "
                "raises refinancing and default risk."
            ),
        ),
        (
            "Dollar & commodities",
            (
                "Relative interest rates influence currencies; growth and supply conditions "
                "influence commodities. These markets often confirm or challenge the macro story."
            ),
        ),
    )


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
    environment: Mapping[str, Any] | None = None,
    dashboard: object | None = None,
    live_market: Mapping[str, object] | None = None,
) -> None:
    """Render the structural backdrop without repeating today's event feed."""

    del briefing
    _install_story_styles()
    resolved_dashboard = dashboard or concise.base.load_dashboard_data()
    resolved_market = live_market or concise.base.load_live_market_console()
    readings = getattr(resolved_dashboard, "readings", None)
    cards = _driver_cards(resolved_dashboard, resolved_market)
    regime = (
        _plain(environment.get("regime"), "Not separately classified")
        if isinstance(environment, Mapping)
        else "Not separately classified"
    )
    headline = (
        _plain(environment.get("headline"), "Current economic backdrop")
        if isinstance(environment, Mapping)
        else (
            "Provider-backed economic evidence is available"
            if readings is not None
            else "Economic evidence is incomplete"
        )
    )
    summary = (
        _plain(environment.get("summary"), "No additional governed summary is available.")
        if isinstance(environment, Mapping)
        else (
            concise.base.economic_snapshot_summary(readings)
            if readings is not None
            else _plain(getattr(resolved_dashboard, "status", ""), "Economic data is unavailable.")
        )
    )
    evaluated_at = getattr(readings, "evaluated_at", None)
    review = (
        _joined(
            environment.get("review_conditions", ()),
            (
                "A material change in growth, inflation, policy, credit, liquidity, "
                "or cross-asset confirmation would change this backdrop."
            ),
        )
        if isinstance(environment, Mapping)
        else (
            "A material change in growth, inflation, policy, credit, liquidity, "
            "or cross-asset confirmation would change this backdrop."
        )
    )

    st.markdown(
        '<section class="environment-dashboard" aria-label="Environment dashboard">'
        '<div class="environment-regime">'
        '<div class="environment-kicker">Environment // structural conditions, not daily headlines</div>'
        f'<h2>{escape(regime)}</h2>'
        f'<div class="environment-regime-copy"><strong>{escape(headline)}</strong><br>'
        f'{escape(summary)}</div>'
        '<div class="environment-regime-meta">'
        f'<span class="today-chip">{escape(getattr(resolved_dashboard, "data_source", "Data source unavailable"))}</span>'
        f'<span class="today-chip">{escape(_age_label(evaluated_at))}</span>'
        f'<span class="today-chip">Market {_market_session(resolved_market).lower()}</span>'
        "</div></div>"
        '<div class="environment-driver-grid">'
        + "".join(
            '<article class="environment-driver">'
            '<div class="driver-top">'
            f'<div class="driver-name">{escape(name)}</div>'
            f'<div class="driver-state">{escape(state)}</div></div>'
            f'<div class="driver-value">{escape(value)}</div>'
            f'<div class="driver-why"><strong>Why markets care:</strong> {escape(why)}</div>'
            f'<div class="driver-markets"><strong>{escape(markets.split(":")[0])}:</strong>'
            f'{escape(markets.split(":", 1)[1] if ":" in markets else markets)}</div>'
            "</article>"
            for name, value, state, why, markets in cards
        )
        + "</div></section>",
        unsafe_allow_html=True,
    )

    market_map = _environment_market_map(cards)
    st.markdown(
        '<section class="environment-transmission">'
        '<div class="environment-transmission-head"><div>'
        '<h3>How this backdrop reaches markets</h3>'
        '<p>These are transmission mechanisms, not return forecasts.</p></div>'
        '<span class="today-chip">Cross-asset map</span></div>'
        '<div class="market-map">'
        + "".join(
            '<article class="market-map-card">'
            f'<div class="market-map-name">{escape(name)}</div>'
            f'<div class="market-map-copy">{escape(copy)}</div></article>'
            for name, copy in market_map
        )
        + "</div></section>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<section class="environment-learning">'
        '<div class="environment-learning-card">'
        '<div class="environment-kicker">Investor lesson</div>'
        '<h3>Read the economy through four channels</h3>'
        '<p>Growth reaches earnings. Inflation reaches margins and policy. Rates reach '
        "financing costs and valuations. Liquidity reaches risk premiums and market depth. "
        "A useful environment view connects those channels instead of treating each data "
        'release as an isolated headline.</p></div>'
        '<div class="environment-change-card">'
        '<div class="environment-kicker">What would change the view</div>'
        '<h3>Conditions that deserve the next review</h3>'
        f'<p>{escape(review)}</p></div></section>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Economic readings: {getattr(resolved_dashboard, 'data_source', 'Unavailable')} · "
        f"evaluated {_format_source_time(evaluated_at)}. Environment explains the "
        "structural backdrop; daily events remain in Today and portfolio action remains "
        "in Portfolio."
    )


def _render_today(app: ModuleType, dependencies: object) -> None:
    del dependencies
    briefing = app._latest("daily_cio_briefing")
    live_market = app.load_live_market_console()

    app.page_header(
        "Investment world today",
        (
            "What happened, why investors care, how markets may react, and the "
            "evidence that matters next."
        ),
        "NOW",
    )
    render_information_freshness(briefing=briefing, surface="today")
    render_today_market_brief(briefing=briefing, live_market=live_market)
    _render_today_research_radar()
    with st.expander("Live market operating detail", expanded=False):
        app.render_live_market_status()


def _render_environment(app: ModuleType, dependencies: object) -> None:
    del dependencies
    payload = app._diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard = app.load_dashboard_data()
    live_market = app.load_live_market_console()
    briefing = app._latest("daily_cio_briefing")

    app.page_header(
        "Economy and investing",
        (
            "The structural growth, inflation, rates, and liquidity backdrop—and "
            "the channels through which it affects markets."
        ),
        "ECON",
    )
    render_information_freshness(briefing=briefing, surface="environment")
    render_environment_economic_brief(
        briefing=briefing,
        environment=environment if isinstance(environment, Mapping) else None,
        dashboard=dashboard,
        live_market=live_market,
    )
    with st.expander("Cross-asset market detail", expanded=False):
        app.render_live_environment_market_table()


def install(app_impl: ModuleType) -> None:
    """Install the consolidated Today and Environment presentation once."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return
    app_impl.render_information_freshness = render_information_freshness
    app_impl.render_today_market_brief = render_today_market_brief
    app_impl.render_environment_economic_brief = render_environment_economic_brief

    @st.fragment(run_every="30s")
    def render_today(dependencies: object) -> None:
        _render_today(app_impl, dependencies)

    @st.fragment(run_every="30s")
    def render_environment(dependencies: object) -> None:
        _render_environment(app_impl, dependencies)

    app_impl._render_today = render_today
    app_impl._render_environment = render_environment
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = [
    "_age_label",
    "_concept_for_item",
    "_driver_cards",
    "install",
    "render_environment_economic_brief",
    "render_information_freshness",
    "render_today_market_brief",
]
