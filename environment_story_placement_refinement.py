"""Final Today and Environment storytelling layer.

Today is a ranked, current investment briefing. Environment is a structural
macro dashboard. This module is presentation-only and cannot authorize trades.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Iterable, Mapping, Sequence

import streamlit as st

import concise_operating_intelligence_ui as concise


_INSTALLED_KEY = "_capital_intelligence_investor_storytelling_installed"
_CHANNEL_NAMES = {
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
        "Asset prices reflect future cash flows in today's dollars. When required returns "
        "or bond yields rise, distant cash flows become less valuable, so long-duration "
        "bonds and growth stocks can be especially sensitive.",
    ),
    (
        frozenset({"growth", "demand", "earnings"}),
        "Earnings expectations",
        "Markets move on changes in expected profits, not only current results. Stronger "
        "demand can lift revenue and credit quality; weaker demand can pressure cyclical "
        "companies and lower-quality borrowers.",
    ),
    (
        frozenset({"credit", "counterparty", "volatility", "positioning", "sentiment"}),
        "Risk premiums",
        "Investors demand extra return for uncertainty, illiquidity, or default risk. When "
        "that premium rises, credit spreads and volatility often increase while risk-asset "
        "valuations fall.",
    ),
    (
        frozenset({"supply", "commodity", "climate_weather"}),
        "Input-cost transmission",
        "Supply disruptions can raise commodity and transportation costs. Producers may "
        "benefit while companies that consume those inputs can face lower margins and "
        "renewed inflation pressure.",
    ),
    (
        frozenset({"currency"}),
        "Currency translation",
        "Exchange-rate moves change the home-currency value of foreign revenue and assets. "
        "A stronger dollar can pressure overseas earnings translated into dollars while "
        "reducing some imported inflation.",
    ),
    (
        frozenset({"regulation", "geopolitical", "operational", "cyber"}),
        "Event risk",
        "Policy and disruption risks create uneven outcomes. The investment question is "
        "whether an event changes cash flows, financing conditions, liquidity, or the range "
        "of plausible outcomes—not merely whether it sounds important.",
    ),
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _unique(values: Iterable[object], limit: int) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean(value)
        key = text.casefold().strip(" .,;:–—-")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _format_time(value: object) -> str:
    if not isinstance(value, datetime):
        return "Time unavailable"
    return value.astimezone(timezone.utc).strftime("%b %d · %H:%M UTC")


def _age_label(value: object, now: datetime | None = None) -> str:
    if not isinstance(value, datetime):
        return "time unavailable"
    seconds = max(
        0.0,
        ((now or datetime.now(timezone.utc)) - value.astimezone(timezone.utc)).total_seconds(),
    )
    minutes = int(seconds // 60)
    if minutes < 2:
        return "just verified"
    if minutes < 60:
        return f"verified {minutes}m ago"
    hours = minutes // 60
    return f"verified {hours}h ago" if hours < 24 else f"verified {hours // 24}d ago"


def _count(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return "Unavailable"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "Unavailable"


def _session(market: Mapping[str, object]) -> str:
    value = market.get("market_open")
    return "Open" if value is True else "Closed" if value is False else "Unavailable"


def _coverage(market: Mapping[str, object]) -> str:
    return (
        f"{int(market.get('quote_count', 0) or 0)}/"
        f"{int(market.get('expected_quote_count', 0) or 0)}"
    )


def _channels(item: object) -> tuple[str, ...]:
    raw = getattr(item, "impact_channels", ())
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, Sequence):
        return ()
    return _unique(
        (
            _CHANNEL_NAMES.get(
                _clean(channel).lower(),
                _clean(channel).replace("_", " ").title(),
            )
            for channel in raw
        ),
        4,
    )


def _lesson(item: object) -> tuple[str, str]:
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
        "A development matters when it changes expected cash flows, required returns, "
        "liquidity, or the range of potential outcomes. Price movement without one of "
        "those links may be noise rather than new information.",
    )


def _styles() -> None:
    st.markdown(
        """
<style>
.ci-story-health{margin:.15rem 0 1rem}.ci-today,.ci-env-hero{border:1px solid rgba(86,224,255,.2);
 border-radius:24px;padding:1.1rem;background:radial-gradient(circle at 92% 8%,rgba(86,224,255,.12),
 transparent 17rem),linear-gradient(145deg,rgba(14,22,37,.97),rgba(8,13,24,.97));
 box-shadow:0 22px 55px rgba(0,0,0,.27);margin:.35rem 0 1rem}.ci-head{display:flex;
 justify-content:space-between;gap:1rem;align-items:flex-start;padding-bottom:.9rem;
 border-bottom:1px solid rgba(138,157,188,.12)}.ci-kicker{font-size:.66rem;font-weight:850;
 letter-spacing:.14em;text-transform:uppercase;color:#56e0ff}.ci-head h2,.ci-env-hero h2{font-size:clamp(1.4rem,3vw,2.15rem);
 line-height:1.08;letter-spacing:-.035em;color:#f8fafc;margin:.32rem 0 .42rem}.ci-deck{font-size:.89rem;
 line-height:1.58;color:#a7b4c7;max-width:54rem}.ci-chips,.ci-tags{display:flex;flex-wrap:wrap;gap:.38rem}
.ci-chips{justify-content:flex-end}.ci-chip,.ci-tag{padding:.33rem .54rem;border-radius:999px;border:1px solid
 rgba(138,157,188,.16);background:rgba(255,255,255,.025);color:#b8c5d8;font-size:.66rem;font-weight:700}
.ci-primary{padding:1rem 0 .05rem}.ci-meta{display:flex;flex-wrap:wrap;gap:.4rem;font-size:.65rem;
 color:#7f8da3;text-transform:uppercase;letter-spacing:.07em}.ci-rank{color:#56e0ff;font-weight:850}
.ci-title{font-size:clamp(1.28rem,2.6vw,1.9rem);line-height:1.15;letter-spacing:-.027em;color:#fff;
 margin:.52rem 0 .74rem}.ci-three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.68rem}
.ci-box,.ci-story,.ci-panel,.ci-driver,.ci-market{min-width:0;padding:.78rem;border:1px solid rgba(138,157,188,.12);
 border-radius:16px;background:rgba(255,255,255,.022)}.ci-label{font-size:.63rem;font-weight:850;letter-spacing:.1em;
 text-transform:uppercase;color:#56e0ff;margin-bottom:.32rem}.ci-box p,.ci-copy{font-size:.79rem;line-height:1.52;
 color:#c1ccdb;margin:0}.ci-tags{margin-top:.7rem}.ci-story-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));
 gap:.72rem;margin-bottom:1rem}.ci-story{border-radius:19px;background:linear-gradient(145deg,rgba(13,20,34,.94),
 rgba(9,14,25,.94));box-shadow:0 14px 34px rgba(0,0,0,.18)}.ci-story h3,.ci-panel h3{font-size:.94rem;
 color:#f4f8fd;margin:.4rem 0 .55rem}.ci-copy{color:#aeb9c9;margin:.3rem 0}.ci-copy strong{color:#e8eef7}
.ci-pair{display:grid;grid-template-columns:.72fr 1.28fr;gap:.72rem;margin-bottom:1rem}.ci-watch{display:flex;
 gap:.5rem;padding:.45rem 0;border-top:1px solid rgba(138,157,188,.1);font-size:.78rem;color:#b8c4d3}
.ci-watch:first-of-type{border-top:0}.ci-num{color:#56e0ff;font-weight:850}.ci-lesson{font-size:.65rem;
 font-weight:850;letter-spacing:.1em;text-transform:uppercase;color:#9b7cff;margin-bottom:.34rem}.ci-radar{display:grid;
 grid-template-columns:repeat(3,minmax(0,1fr));gap:.58rem}.ci-radar-value{font-size:.88rem;color:#e9f0fa;
 font-weight:760;margin-top:.24rem}.ci-radar-note{font-size:.7rem;color:#8e9db2;line-height:1.4;margin-top:.2rem}
.ci-env-hero{border-color:rgba(82,227,164,.22);background:radial-gradient(circle at 86% 0%,
 rgba(82,227,164,.13),transparent 18rem),linear-gradient(145deg,rgba(12,24,31,.97),rgba(8,15,25,.97))}
.ci-env-hero .ci-kicker,.ci-driver-name{color:#52e3a4}.ci-driver-grid,.ci-market-grid{display:grid;
 grid-template-columns:repeat(4,minmax(0,1fr));gap:.62rem}.ci-driver{border-radius:18px;background:linear-gradient(150deg,
 rgba(13,21,32,.95),rgba(9,14,23,.95))}.ci-driver-top{display:flex;justify-content:space-between;gap:.45rem}
.ci-driver-name{font-size:.65rem;font-weight:850;letter-spacing:.1em;text-transform:uppercase}.ci-state{font-size:.61rem;
 color:#9aabbe;text-align:right}.ci-driver-value{font-size:1.2rem;color:#f7fbff;font-weight:780;margin:.48rem 0}
.ci-driver-copy,.ci-market-copy{font-size:.72rem;line-height:1.45;color:#93a2b6;margin-top:.43rem}
.ci-driver-copy strong{color:#dbe5f1}.ci-transmission{margin:1rem 0;padding:.9rem;border-radius:20px;
 border:1px solid rgba(82,227,164,.16);background:rgba(9,16,25,.8)}.ci-market-name{font-size:.65rem;
 font-weight:850;text-transform:uppercase;letter-spacing:.08em;color:#ffc96b}.ci-market-copy{color:#acb8c8}
@media(max-width:900px){.ci-three{grid-template-columns:1fr}.ci-driver-grid,.ci-market-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:720px){.ci-today,.ci-env-hero{border-radius:19px;padding:.9rem}.ci-head{display:block}.ci-chips{justify-content:flex-start;
 margin-top:.62rem}.ci-story-grid,.ci-pair,.ci-driver-grid,.ci-market-grid,.ci-radar{grid-template-columns:1fr}}
</style>
        """,
        unsafe_allow_html=True,
    )


def _tags(item: object) -> str:
    values = [*_channels(item), _clean(getattr(item, "affected_investments", ""))]
    return "".join(
        f'<span class="ci-tag">{escape(value)}</span>'
        for value in _unique(values, 5)
    )


def _primary(item: object) -> str:
    _, explanation = _lesson(item)
    return (
        '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">Most material development</span>'
        f'<span>{escape(_clean(getattr(item, "source_type", "Public")))} · '
        f'{escape(_clean(getattr(item, "source", "Public source")))}</span>'
        f'<span>{escape(_age_label(getattr(item, "published_at", None)))}</span></div>'
        f'<div class="ci-title">{escape(_clean(getattr(item, "title", "Market development")))}</div>'
        '<div class="ci-three"><div class="ci-box"><div class="ci-label">What happened</div>'
        f'<p>{escape(_clean(getattr(item, "summary", "No concise detail is available.")))}</p></div>'
        '<div class="ci-box"><div class="ci-label">Why it matters</div>'
        f'<p>{escape(explanation)}</p></div><div class="ci-box"><div class="ci-label">How markets may react</div>'
        f'<p>{escape(_clean(getattr(item, "portfolio_lens", "Market effects remain under review.")))}</p></div>'
        f'</div><div class="ci-tags">{_tags(item)}</div></div>'
    )


def _secondary(item: object, rank: int) -> str:
    concept, explanation = _lesson(item)
    return (
        '<article class="ci-story"><div class="ci-meta">'
        f'<span class="ci-rank">Development {rank:02d}</span>'
        f'<span>{escape(_age_label(getattr(item, "published_at", None)))}</span></div>'
        f'<h3>{escape(_clean(getattr(item, "title", "Market development")))}</h3>'
        f'<div class="ci-copy"><strong>What happened:</strong> {escape(_clean(getattr(item, "summary", "")))}</div>'
        f'<div class="ci-copy"><strong>Market impact:</strong> {escape(_clean(getattr(item, "portfolio_lens", "")))}</div>'
        f'<div class="ci-copy"><strong>Investor lesson — {escape(concept)}:</strong> {escape(explanation)}</div>'
        f'<div class="ci-tags">{_tags(item)}</div></article>'
    )


def _watch(items: Sequence[object]) -> tuple[str, ...]:
    values: list[str] = []
    for item in items:
        raw = _clean(getattr(item, "what_to_watch", ""))
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    return _unique(values, 5) or (
        "Treasury yields and central-bank guidance",
        "Earnings expectations and company guidance",
        "Credit spreads, liquidity, and market breadth",
    )


def _research_radar() -> None:
    snapshot = concise.base.load_opportunity_scan()
    cells = (
        ("Assets screened", _count(snapshot.broad_assets_screened), "Broad research coverage."),
        ("Evidence-complete", _count(snapshot.governed_candidates), "Candidates with governed evidence."),
        ("Reached CIO queue", _count(snapshot.opportunities_reaching_cio), "Qualified decision alternatives."),
    )
    markup = "".join(
        '<div class="ci-panel"><div class="ci-label">'
        f'{escape(label)}</div><div class="ci-radar-value">{escape(value)}</div>'
        f'<div class="ci-radar-note">{escape(note)}</div></div>'
        for label, value, note in cells
    )
    st.markdown(
        '<section class="ci-panel"><div class="ci-meta"><span class="ci-rank">Research radar</span>'
        f'<span>As of {_format_time(snapshot.as_of)}</span></div><h3>What the governed opportunity process is finding</h3>'
        f'<div class="ci-radar">{markup}</div><div class="ci-radar" style="margin-top:.58rem">'
        '<div class="ci-panel"><div class="ci-label">Strongest alternative</div>'
        f'<div class="ci-radar-value">{escape(snapshot.strongest_alternative)}</div>'
        f'<div class="ci-radar-note">{escape(snapshot.strongest_stage)}</div></div>'
        '<div class="ci-panel"><div class="ci-label">Why it did not advance</div>'
        f'<div class="ci-radar-value">{escape(snapshot.main_reason)}</div>'
        '<div class="ci-radar-note">Research status, not a portfolio instruction.</div></div></div></section>',
        unsafe_allow_html=True,
    )


def _render_today(app: ModuleType, dependencies: object) -> None:
    del dependencies
    _styles()
    briefing = app._latest("daily_cio_briefing")
    market = app.load_live_market_console()
    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(record for record in snapshot.records if isinstance(record, Mapping))
    items = concise.base.build_today_items(records, limit=3)

    app.page_header(
        "Investment world today",
        "What happened, why investors care, how markets may react, and what evidence matters next.",
        "NOW",
    )
    app.render_information_freshness(briefing=briefing, surface="today")
    hero = (
        '<section class="ci-today"><div class="ci-head"><div><div class="ci-kicker">Today // current developments</div>'
        '<h2>What is moving the investment conversation</h2><div class="ci-deck">Only source-qualified developments '
        'from the last 24 hours appear here. Each story separates the fact, the investment mechanism, and the '
        'possible market reaction so headlines are not mistaken for trading signals.</div></div><div class="ci-chips">'
        f'<span class="ci-chip">Market {_session(market).lower()}</span>'
        f'<span class="ci-chip">{escape(_coverage(market))} governed quotes</span>'
        f'<span class="ci-chip">{escape(_age_label(snapshot.evaluated_at))}</span></div></div>'
    )
    if items:
        hero += _primary(items[0])
    else:
        detail = _clean(snapshot.detail) or "No material, source-qualified event cleared the last-24-hour controls."
        hero += (
            '<div class="ci-primary"><div class="ci-meta"><span class="ci-rank">Quiet-day conclusion</span></div>'
            '<div class="ci-title">No new story earned investor attention.</div><div class="ci-box">'
            f'<div class="ci-label">Why this is useful</div><p>{escape(detail)} A quiet result is more trustworthy '
            'than filling the page with repetitive or low-quality headlines.</p></div></div>'
        )
    st.markdown(hero + "</section>", unsafe_allow_html=True)

    if len(items) > 1:
        st.markdown(
            '<section class="ci-story-grid">'
            + "".join(_secondary(item, rank) for rank, item in enumerate(items[1:], start=2))
            + "</section>",
            unsafe_allow_html=True,
        )
    if items:
        concept, explanation = _lesson(items[0])
        watch_markup = "".join(
            f'<div class="ci-watch"><span class="ci-num">{index:02d}</span><span>{escape(value)}</span></div>'
            for index, value in enumerate(_watch(items), start=1)
        )
        st.markdown(
            '<section class="ci-pair"><div class="ci-panel"><div class="ci-meta"><span class="ci-rank">'
            f'What to watch next</span></div><h3>Evidence that can confirm or reverse the story</h3>{watch_markup}</div>'
            '<div class="ci-panel"><div class="ci-meta"><span class="ci-rank">Investor lesson</span></div>'
            f'<h3>{escape(concept)}</h3><div class="ci-lesson">Learn the mechanism</div>'
            f'<div class="ci-copy">{escape(explanation)}</div></div></section>',
            unsafe_allow_html=True,
        )
    with st.expander("Original source context", expanded=False):
        if not items:
            st.write(_clean(snapshot.detail) or "No source-qualified event is available.")
        for index, item in enumerate(items, start=1):
            st.markdown(f"**{index}. {_clean(getattr(item, 'title', 'Market development'))}**")
            st.write(_clean(getattr(item, "summary", "")))
            st.caption(
                f"{_clean(getattr(item, 'source_type', 'Public'))} source: "
                f"{_clean(getattr(item, 'source', 'Public source'))} · published "
                f"{_format_time(getattr(item, 'published_at', None))}"
            )
    _research_radar()
    with st.expander("Live market operating detail", expanded=False):
        app.render_live_market_status()
    st.caption(
        concise.base._daily_caption(snapshot)
        + " Educational interpretation only. Today explains external developments; holdings "
        "and CIO-authorized actions remain in Portfolio."
    )


def _score(value: object, positive: str, neutral: str, negative: str) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "Evidence incomplete"
    return positive if score >= .25 else negative if score <= -.25 else neutral


def _drivers(dashboard: object, market: Mapping[str, object]) -> tuple[tuple[str, str, str, str, str], ...]:
    readings = getattr(dashboard, "readings", None)
    snapshot = getattr(dashboard, "snapshot", None)
    if readings is None:
        unemployment = inflation = policy = curve = "Unavailable"
        rate_state = "Evidence incomplete"
    else:
        unemployment = f"{float(readings.unemployment_rate):.1f}%"
        inflation = f"{float(readings.inflation_rate):.2f}%"
        policy = f"{float(readings.federal_funds_rate):.2f}%"
        curve = f"{float(readings.yield_curve_spread):+.2f} pp"
        rate_state = "Upward curve" if readings.yield_curve_spread > .15 else (
            "Inverted curve" if readings.yield_curve_spread < -.15 else "Flat curve"
        )
    liquidity_score = None
    if snapshot is not None:
        try:
            liquidity_score = -(float(snapshot.credit) + float(snapshot.volatility)) / 2
        except (TypeError, ValueError):
            pass
    return (
        ("Growth", unemployment, _score(getattr(snapshot, "growth", None), "Supportive", "Mixed", "Soft"),
         "Labor demand and activity shape revenue, earnings, defaults, and cyclical demand.",
         "Cyclical equities, small caps, credit, and consumer sectors."),
        ("Inflation", inflation, _score(getattr(snapshot, "inflation", None), "Elevated pressure", "Balanced", "Disinflationary"),
         "Inflation changes purchasing power, company margins, and the path of interest rates.",
         "Bonds, growth equities, commodities, and inflation hedges."),
        ("Rates", f"{policy} · curve {curve}", rate_state,
         "Policy and market yields set financing costs and the discount rate used to value assets.",
         "Treasuries, long-duration equities, housing, banks, and the dollar."),
        ("Liquidity", f"{_coverage(market)} quotes" if market.get("status") in {"connected", "partial"} else "Evidence incomplete",
         _score(liquidity_score, "Supportive", "Mixed", "Restrictive"),
         "Liquidity and credit conditions determine how easily risk can be financed or sold.",
         "Credit spreads, smaller companies, volatility, and crowded positions."),
    )


def _render_environment(app: ModuleType, dependencies: object) -> None:
    del dependencies
    _styles()
    payload = app._diagnostic_environment()
    environment = payload.get("environment") if isinstance(payload, Mapping) else None
    dashboard = app.load_dashboard_data()
    market = app.load_live_market_console()
    briefing = app._latest("daily_cio_briefing")
    readings = getattr(dashboard, "readings", None)
    drivers = _drivers(dashboard, market)

    regime = _clean(environment.get("regime")) if isinstance(environment, Mapping) else ""
    headline = _clean(environment.get("headline")) if isinstance(environment, Mapping) else ""
    summary = _clean(environment.get("summary")) if isinstance(environment, Mapping) else ""
    review_conditions = environment.get("review_conditions", ()) if isinstance(environment, Mapping) else ()
    regime = regime or "Current macro backdrop"
    headline = headline or (
        "Provider-backed economic evidence is available" if readings is not None else "Economic evidence is incomplete"
    )
    summary = summary or (
        concise.base.economic_snapshot_summary(readings)
        if readings is not None
        else _clean(getattr(dashboard, "status", "")) or "Economic data is unavailable."
    )
    review = " • ".join(_unique(review_conditions, 6)) if isinstance(review_conditions, Sequence) and not isinstance(review_conditions, (str, bytes)) else _clean(review_conditions)
    review = review or "A material change in growth, inflation, policy, credit, liquidity, or cross-asset confirmation would change this backdrop."

    app.page_header(
        "Economy and investing",
        "The growth, inflation, rates, and liquidity backdrop—and how it reaches markets.",
        "ECON",
    )
    app.render_information_freshness(briefing=briefing, surface="environment")
    st.markdown(
        '<section class="ci-env-hero"><div class="ci-kicker">Environment // structural conditions</div>'
        f'<h2>{escape(regime)}</h2><div class="ci-deck"><strong>{escape(headline)}</strong><br>{escape(summary)}</div>'
        '<div class="ci-tags" style="margin-top:.65rem">'
        f'<span class="ci-chip">{escape(_clean(getattr(dashboard, "data_source", "Data unavailable")))}</span>'
        f'<span class="ci-chip">{escape(_age_label(getattr(readings, "evaluated_at", None)))}</span>'
        f'<span class="ci-chip">Market {_session(market).lower()}</span></div></section>',
        unsafe_allow_html=True,
    )
    driver_markup = "".join(
        '<article class="ci-driver"><div class="ci-driver-top">'
        f'<div class="ci-driver-name">{escape(name)}</div><div class="ci-state">{escape(state)}</div></div>'
        f'<div class="ci-driver-value">{escape(value)}</div>'
        f'<div class="ci-driver-copy"><strong>Why markets care:</strong> {escape(why)}</div>'
        f'<div class="ci-driver-copy"><strong>Most sensitive:</strong> {escape(sensitive)}</div></article>'
        for name, value, state, why, sensitive in drivers
    )
    st.markdown(f'<section class="ci-driver-grid">{driver_markup}</section>', unsafe_allow_html=True)

    states = {name: state for name, _, state, _, _ in drivers}
    market_map = (
        ("Equities", f"Growth is {states['Growth'].lower()} while rates are {states['Rates'].lower()}. Earnings support helps, but higher discount rates can limit valuation upside."),
        ("Bonds", f"Inflation is {states['Inflation'].lower()}. Falling inflation or weaker growth generally supports duration; persistent inflation can keep yields elevated."),
        ("Credit", f"Liquidity is {states['Liquidity'].lower()}. Strong growth and easy funding can compress spreads; weaker activity or tighter funding raises default risk."),
        ("Dollar & commodities", "Relative rates influence currencies; growth and supply conditions influence commodities. These markets often confirm or challenge the macro story."),
    )
    market_markup = "".join(
        '<article class="ci-market"><div class="ci-market-name">'
        f'{escape(name)}</div><div class="ci-market-copy">{escape(copy)}</div></article>'
        for name, copy in market_map
    )
    st.markdown(
        '<section class="ci-transmission"><div class="ci-meta"><span class="ci-rank">Cross-asset map</span></div>'
        '<h3 style="color:#f3f8fd;margin:.35rem 0 .6rem">How this backdrop reaches markets</h3>'
        f'<div class="ci-market-grid">{market_markup}</div></section>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<section class="ci-pair"><div class="ci-panel"><div class="ci-kicker">Investor lesson</div>'
        '<h3>Read the economy through four channels</h3><div class="ci-copy">Growth reaches earnings. Inflation reaches '
        'margins and policy. Rates reach financing costs and valuations. Liquidity reaches risk premiums and market depth. '
        'A useful environment view connects these channels instead of treating each release as an isolated headline.</div></div>'
        '<div class="ci-panel"><div class="ci-kicker">What would change the view</div><h3>Conditions that deserve the next review</h3>'
        f'<div class="ci-copy">{escape(review)}</div></div></section>',
        unsafe_allow_html=True,
    )
    with st.expander("Cross-asset market detail", expanded=False):
        app.render_live_environment_market_table()
    st.caption(
        f"Economic readings: {_clean(getattr(dashboard, 'data_source', 'Unavailable'))} · evaluated "
        f"{_format_time(getattr(readings, 'evaluated_at', None))}. Environment explains structural "
        "conditions; daily developments remain in Today and portfolio action remains in Portfolio."
    )


def install(app_impl: ModuleType) -> None:
    """Install last so no earlier refinement can reintroduce duplicate content."""

    if getattr(app_impl, _INSTALLED_KEY, False):
        return

    @st.fragment(run_every="30s")
    def render_today(dependencies: object) -> None:
        _render_today(app_impl, dependencies)

    @st.fragment(run_every="30s")
    def render_environment(dependencies: object) -> None:
        _render_environment(app_impl, dependencies)

    app_impl._render_today = render_today
    app_impl._render_environment = render_environment
    setattr(app_impl, _INSTALLED_KEY, True)


__all__ = ["_age_label", "_drivers", "_lesson", "install"]
