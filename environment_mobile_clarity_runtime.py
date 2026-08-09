"""Make Environment concise on mobile without changing governed evidence.

This is a presentation-only final Environment renderer. It keeps the existing
provider-backed driver calculations and cross-asset interpretation, but leads with
one synthesized conclusion, keeps the four driver and market states scan-friendly,
and moves the longer educational explanations behind collapsed controls.

It cannot create evidence, change thresholds, rank candidates, authorize a CIO
decision, construct a portfolio, execute a trade, or authorize real money.
"""

from __future__ import annotations

from functools import wraps
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

import streamlit as st

import environment_actionable_learning_refinement as learning
import environment_driver_education_runtime as driver_runtime


_INSTALLED_KEY = "_capital_intelligence_environment_mobile_clarity_installed"


_CSS = """
<style>
/* Environment summary: answer first, details on demand. */
.ci-env-now{
    margin:.18rem 0 .7rem;
    padding:.9rem 1rem;
    border:1px solid rgba(82,227,164,.24);
    border-radius:18px;
    background:linear-gradient(145deg,rgba(82,227,164,.075),rgba(9,16,25,.9));
    box-shadow:0 14px 34px rgba(0,0,0,.16);
}
.ci-env-now-kicker,.ci-env-section-kicker{
    color:#52e3a4;
    font-size:.61rem;
    font-weight:850;
    letter-spacing:.12em;
    text-transform:uppercase;
}
.ci-env-now-title{
    margin:.3rem 0 .28rem;
    color:#f5f9fc;
    font-size:clamp(1.02rem,2.3vw,1.35rem);
    line-height:1.25;
    font-weight:800;
    letter-spacing:-.018em;
}
.ci-env-now-copy{
    color:#aebccc;
    font-size:.76rem;
    line-height:1.5;
}
.ci-env-source-row{
    display:flex;
    flex-wrap:wrap;
    gap:.34rem;
    margin-top:.62rem;
}
.ci-env-source-chip{
    padding:.27rem .48rem;
    border:1px solid rgba(138,157,188,.16);
    border-radius:999px;
    background:rgba(255,255,255,.022);
    color:#92a3b8;
    font-size:.59rem;
    font-weight:720;
}
.ci-env-source-chip.current{
    color:#9de6c8;
    border-color:rgba(82,227,164,.2);
    background:rgba(82,227,164,.05);
}
.ci-env-section-head{
    display:flex;
    align-items:flex-end;
    justify-content:space-between;
    gap:.7rem;
    margin:.78rem 0 .48rem;
}
.ci-env-section-title{
    color:#f0f5fb;
    font-size:.9rem;
    line-height:1.3;
    font-weight:790;
}
.ci-env-section-note{
    color:#72839a;
    font-size:.6rem;
    line-height:1.35;
    text-align:right;
}
/* Keep the existing canonical class names so browser ownership checks still
   identify Environment as the same structural surface. */
.ci-driver-grid,.ci-market-grid{
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:.56rem;
}
.ci-driver,.ci-market{
    min-width:0;
    padding:.68rem;
    border:1px solid rgba(138,157,188,.13);
    border-radius:15px;
    background:linear-gradient(150deg,rgba(13,21,32,.94),rgba(9,14,23,.94));
}
.ci-driver-top,.ci-env-market-top{
    display:flex;
    justify-content:space-between;
    align-items:flex-start;
    gap:.35rem;
}
.ci-driver-name,.ci-market-name{
    color:#52e3a4;
    font-size:.6rem;
    font-weight:850;
    letter-spacing:.09em;
    text-transform:uppercase;
}
.ci-market-name{color:#ffc96b}
.ci-state,.ci-env-market-bias{
    color:#92a2b6;
    font-size:.55rem;
    line-height:1.25;
    text-align:right;
}
.ci-driver-value{
    margin:.42rem 0 .22rem;
    color:#f6f9fc;
    font-size:1.02rem;
    line-height:1.2;
    font-weight:800;
}
.ci-env-driver-one-line,.ci-env-market-one-line{
    color:#8fa0b4;
    font-size:.63rem;
    line-height:1.4;
}
.ci-env-market-bias{
    padding:.2rem .38rem;
    border-radius:999px;
    border:1px solid rgba(138,157,188,.16);
    white-space:normal;
}
.ci-env-market-bias-positive{
    color:#9de6c8;
    border-color:rgba(82,227,164,.25);
    background:rgba(82,227,164,.06);
}
.ci-env-market-bias-negative{
    color:#ffc6a7;
    border-color:rgba(255,149,92,.25);
    background:rgba(255,149,92,.06);
}
.ci-env-market-bias-mixed{
    color:#d7c9ff;
    border-color:rgba(166,139,255,.25);
    background:rgba(166,139,255,.06);
}
.ci-transmission{
    margin:.75rem 0 .62rem;
    padding:.74rem;
    border:1px solid rgba(82,227,164,.15);
    border-radius:17px;
    background:rgba(9,16,25,.72);
}
.ci-transmission h3{
    margin:.26rem 0 .46rem;
    color:#f2f7fb;
    font-size:.96rem;
}
.ci-env-transmission-copy{
    margin-bottom:.58rem;
    color:#8fa0b4;
    font-size:.66rem;
    line-height:1.45;
}
.ci-env-detail-card{
    margin:.42rem 0;
    padding:.72rem;
    border:1px solid rgba(138,157,188,.12);
    border-radius:14px;
    background:rgba(255,255,255,.018);
}
.ci-env-detail-top{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:.55rem;
}
.ci-env-detail-name{
    color:#edf4fb;
    font-size:.74rem;
    font-weight:820;
}
.ci-env-detail-state{
    color:#8fa1b6;
    font-size:.57rem;
    text-align:right;
}
.ci-env-detail-label{
    margin-top:.54rem;
    color:#52e3a4;
    font-size:.56rem;
    font-weight:850;
    letter-spacing:.08em;
    text-transform:uppercase;
}
.ci-env-detail-copy{
    margin-top:.2rem;
    color:#a9b7c8;
    font-size:.67rem;
    line-height:1.5;
}
.ci-env-detail-tags{
    display:flex;
    flex-wrap:wrap;
    gap:.3rem;
    margin-top:.48rem;
}
.ci-env-detail-tag{
    padding:.23rem .42rem;
    border:1px solid rgba(82,227,164,.16);
    border-radius:999px;
    color:#96d8be;
    background:rgba(82,227,164,.04);
    font-size:.55rem;
    font-weight:720;
}
.ci-env-review-grid{
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:.48rem;
}
.ci-env-boundary{
    margin:.66rem 0 .1rem;
    padding:.58rem .68rem;
    border:1px solid rgba(255,255,255,.06);
    border-radius:12px;
    background:rgba(255,255,255,.015);
    color:#708198;
    font-size:.59rem;
    line-height:1.45;
}
.ci-env-boundary strong{color:#8fa4bb}
.ci-env-boundary span{display:block;margin-top:.14rem}

@media(max-width:900px){
    .ci-driver-grid,.ci-market-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:760px){
    /* Give all four primary labels the full phone width and reduce sticky chrome. */
    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark){
        display:block!important;
        padding:.08rem!important;
        margin-bottom:.24rem!important;
        border-radius:.72rem!important;
        top:max(.16rem,env(safe-area-inset-top,0px))!important;
    }
    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)>div[data-testid="stColumn"]:has(.nav-brand-mark){
        display:none!important;
    }
    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark)>div[data-testid="stColumn"]{
        width:100%!important;
        min-width:0!important;
    }
    div[data-testid="stHorizontalBlock"]:has(.nav-brand-mark) [data-testid="stButtonGroup"] button{
        min-height:2.2rem!important;
        padding:.18rem .14rem!important;
        font-size:clamp(.6rem,2.55vw,.71rem)!important;
    }
    /* The surface identity remains visible, but governance badges and decorative
       art no longer consume the first phone screen. */
    .hero-shell{margin-bottom:.18rem!important;border-radius:21px!important}
    .hero-card{min-height:0!important;padding:.9rem .98rem!important;border-radius:20px!important}
    .hero-grid{grid-template-columns:1fr!important;gap:.25rem!important}
    .surface-visual{display:none!important}
    .hero-copy{margin-top:.44rem!important;font-size:.84rem!important;line-height:1.48!important}
    .hero-meta{display:none!important}
    .block-container{padding-top:.28rem!important;padding-bottom:2rem!important}

    .ci-env-now{margin-top:.05rem;padding:.78rem .82rem;border-radius:15px}
    .ci-env-now-copy{font-size:.7rem;line-height:1.46}
    .ci-env-source-row{margin-top:.5rem}
    .ci-env-section-head{margin:.62rem 0 .4rem;align-items:flex-start}
    .ci-env-section-note{max-width:42%}
    .ci-driver-grid,.ci-market-grid{
        grid-template-columns:repeat(2,minmax(0,1fr))!important;
        gap:.44rem!important;
    }
    .ci-driver,.ci-market{padding:.58rem;border-radius:13px}
    .ci-driver-value{font-size:.91rem;margin:.34rem 0 .18rem}
    .ci-env-driver-one-line,.ci-env-market-one-line{font-size:.58rem;line-height:1.34}
    .ci-driver-name,.ci-market-name{font-size:.55rem;letter-spacing:.07em}
    .ci-state,.ci-env-market-bias{font-size:.51rem}
    .ci-transmission{margin:.62rem 0 .52rem;padding:.62rem;border-radius:15px}
    .ci-transmission h3{font-size:.88rem;margin:.22rem 0 .38rem}
    .ci-env-transmission-copy{font-size:.61rem;margin-bottom:.46rem}
    .ci-env-review-grid{grid-template-columns:1fr}
}
</style>
"""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _driver_by_name(
    drivers: Sequence[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    return {_clean(row.get("name")): row for row in drivers}


def _market_by_name(
    markets: Sequence[Mapping[str, str]],
) -> dict[str, Mapping[str, str]]:
    return {_clean(row.get("name")): row for row in markets}


def _environment_summary(
    drivers: Sequence[Mapping[str, object]],
    markets: Sequence[Mapping[str, str]],
) -> tuple[str, str]:
    """Synthesize existing classifications without creating a new investment signal."""

    by_driver = _driver_by_name(drivers)
    by_market = _market_by_name(markets)
    growth = _clean(by_driver.get("Growth", {}).get("state")) or "evidence incomplete"
    inflation = _clean(by_driver.get("Inflation", {}).get("state")) or "evidence incomplete"
    rates = _clean(by_driver.get("Rates", {}).get("state")) or "evidence incomplete"
    liquidity = _clean(by_driver.get("Liquidity", {}).get("state")) or "evidence incomplete"

    if growth == "Supportive" and inflation == "Elevated pressure":
        title = "Growth-supportive, but rate-sensitive"
    elif growth == "Supportive":
        title = "Constructive growth backdrop with cross-currents"
    elif growth == "Soft":
        title = "Growth-sensitive backdrop warrants caution"
    elif "incomplete" in " ".join((growth, inflation, rates, liquidity)).lower():
        title = "Environment evidence is incomplete"
    else:
        title = "Mixed macro backdrop"

    market_parts: list[str] = []
    for name in ("Equities", "Bonds", "Credit", "Dollar & commodities"):
        row = by_market.get(name)
        if row is None:
            continue
        label = _clean(row.get("today_label"))
        if label:
            market_parts.append(f"{name.lower()} {label.lower()}")
    market_sentence = ", ".join(market_parts)
    copy = (
        f"Growth is {growth.lower()}, inflation is {inflation.lower()}, rates show a "
        f"{rates.lower()} signal, and liquidity is {liquidity.lower()}."
    )
    if market_sentence:
        copy += f" The current cross-asset interpretation is {market_sentence}."
    return title, copy


def _source_chips(story: ModuleType, dashboard: object, market: Mapping[str, object]) -> str:
    readings = getattr(dashboard, "readings", None)
    source = _clean(getattr(dashboard, "data_source", "Unavailable")) or "Unavailable"
    age = story._age_label(getattr(readings, "evaluated_at", None))
    session = story._session(market)
    coverage = story._coverage(market)
    current_class = " current" if readings is not None else ""
    return (
        '<div class="ci-env-source-row">'
        f'<span class="ci-env-source-chip{current_class}">{escape(source)}</span>'
        f'<span class="ci-env-source-chip{current_class}">{escape(age)}</span>'
        f'<span class="ci-env-source-chip">Market {escape(session.lower())}</span>'
        f'<span class="ci-env-source-chip">{escape(coverage)} live quotes</span>'
        '</div>'
    )


def _compact_driver_cards(drivers: Sequence[Mapping[str, object]]) -> str:
    cards = []
    for row in drivers:
        channel = _clean(row.get("channel"))
        cards.append(
            '<article class="ci-driver"><div class="ci-driver-top">'
            f'<div class="ci-driver-name">{escape(_clean(row.get("name")))}</div>'
            f'<div class="ci-state">{escape(_clean(row.get("state")))}</div></div>'
            f'<div class="ci-driver-value">{escape(_clean(row.get("value")))}</div>'
            f'<div class="ci-env-driver-one-line">{escape(channel)}</div></article>'
        )
    return '<section class="ci-driver-grid">' + "".join(cards) + "</section>"


def _compact_market_cards(markets: Sequence[Mapping[str, str]]) -> str:
    cards = []
    for row in markets:
        tone = _clean(row.get("today_tone")) or "mixed"
        cards.append(
            '<article class="ci-market"><div class="ci-env-market-top">'
            f'<div class="ci-market-name">{escape(_clean(row.get("name")))}</div>'
            f'<div class="ci-env-market-bias ci-env-market-bias-{escape(tone)}">'
            f'{escape(_clean(row.get("today_label")))}</div></div>'
            f'<div class="ci-env-market-one-line">{escape(_clean(row.get("drivers")))}</div></article>'
        )
    return '<div class="ci-market-grid">' + "".join(cards) + "</div>"


def _driver_detail_html(drivers: Sequence[Mapping[str, object]]) -> str:
    blocks: list[str] = []
    for row in drivers:
        feeds = row.get("feeds", ())
        feed_values = (
            list(feeds)
            if isinstance(feeds, Sequence) and not isinstance(feeds, (str, bytes))
            else ()
        )
        tags = "".join(
            f'<span class="ci-env-detail-tag">Feeds into {escape(_clean(value))}</span>'
            for value in feed_values
            if _clean(value)
        )
        blocks.append(
            '<article class="ci-env-detail-card"><div class="ci-env-detail-top">'
            f'<span class="ci-env-detail-name">{escape(_clean(row.get("name")))}</span>'
            f'<span class="ci-env-detail-state">{escape(_clean(row.get("value")))} · '
            f'{escape(_clean(row.get("state")))}</span></div>'
            f'<div class="ci-env-detail-label">{escape(_clean(row.get("metric")))}</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("takeaway")))}</div>'
            '<div class="ci-env-detail-label">Market channel</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("channel")))}</div>'
            '<div class="ci-env-detail-label">Most sensitive</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("sensitive")))}</div>'
            f'<div class="ci-env-detail-tags">{tags}</div></article>'
        )
    return "".join(blocks)


def _market_detail_html(markets: Sequence[Mapping[str, str]]) -> str:
    blocks: list[str] = []
    for row in markets:
        tone = _clean(row.get("today_tone")) or "mixed"
        blocks.append(
            '<article class="ci-env-detail-card"><div class="ci-env-detail-top">'
            f'<span class="ci-env-detail-name">{escape(_clean(row.get("name")))}</span>'
            f'<span class="ci-env-market-bias ci-env-market-bias-{escape(tone)}">'
            f'{escape(_clean(row.get("today_label")))}</span></div>'
            '<div class="ci-env-detail-label">Structural relationship</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("copy")))}</div>'
            '<div class="ci-env-detail-label">Current backdrop</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("today_copy")))}</div>'
            '<div class="ci-env-detail-label">Drivers</div>'
            f'<div class="ci-env-detail-copy">{escape(_clean(row.get("drivers")))}</div>'
            '</article>'
        )
    return "".join(blocks)


def _review_html(drivers: Sequence[Mapping[str, object]]) -> str:
    rows = learning._watch_rows(drivers)
    cards = "".join(
        '<article class="ci-env-detail-card">'
        '<div class="ci-env-detail-top">'
        f'<span class="ci-env-detail-name">{escape(row["name"])}</span>'
        f'<span class="ci-env-detail-state">{escape(row["value"])} · {escape(row["state"])}</span>'
        '</div><div class="ci-env-detail-label">Watch for</div>'
        f'<div class="ci-env-detail-copy">{escape(row["trigger"])}</div>'
        f'<div class="ci-env-detail-copy">{escape(row["impact"])}</div></article>'
        for row in rows
    )
    focus = learning._focus_driver(drivers)
    feeds = focus.get("feeds", ())
    assets = (
        " · ".join(_clean(value) for value in feeds if _clean(value))
        if isinstance(feeds, Sequence) and not isinstance(feeds, (str, bytes))
        else _clean(feeds)
    ) or "Cross-asset markets"
    lesson = (
        '<article class="ci-env-detail-card">'
        '<div class="ci-env-detail-name">How to read the backdrop</div>'
        '<div class="ci-env-detail-label">1 · Current signal</div>'
        f'<div class="ci-env-detail-copy">{escape(_clean(focus.get("name")))} · '
        f'{escape(_clean(focus.get("value")))} · {escape(_clean(focus.get("state")))}</div>'
        '<div class="ci-env-detail-label">2 · How it travels</div>'
        f'<div class="ci-env-detail-copy">{escape(_clean(focus.get("channel")))}</div>'
        '<div class="ci-env-detail-label">3 · Markets exposed</div>'
        f'<div class="ci-env-detail-copy">{escape(assets)}</div>'
        '</article>'
    )
    return lesson + f'<div class="ci-env-review-grid">{cards}</div>'


def _latest_quote_label(market: Mapping[str, object]) -> str:
    value = market.get("latest_quote_at")
    return _clean(value) or "Unavailable"


def _render_environment(story: ModuleType, app: ModuleType, dependencies: object) -> None:
    del dependencies
    story._styles()
    st.markdown(_CSS, unsafe_allow_html=True)

    payload = app._diagnostic_environment()
    environment = payload.get("environment") if isinstance(payload, Mapping) else None
    dashboard = app.load_dashboard_data()
    market = app.load_live_market_console()
    briefing = app._latest("daily_cio_briefing")
    readings = getattr(dashboard, "readings", None)
    drivers = driver_runtime._driver_rows(story, dashboard, market)
    markets = driver_runtime._cross_asset_rows(drivers)
    title, summary = _environment_summary(drivers, markets)

    governed_headline = (
        _clean(environment.get("headline"))
        if isinstance(environment, Mapping)
        else ""
    )
    governed_summary = (
        _clean(environment.get("summary"))
        if isinstance(environment, Mapping)
        else ""
    )
    if governed_headline and governed_summary:
        summary = f"{summary} Governed context: {governed_headline}. {governed_summary}"

    st.markdown(
        '<section class="ci-env-hero ci-env-now">'
        '<div class="ci-env-now-kicker">Current environment</div>'
        f'<div class="ci-env-now-title">{escape(title)}</div>'
        f'<div class="ci-env-now-copy">{escape(summary)}</div>'
        f'{_source_chips(story, dashboard, market)}</section>',
        unsafe_allow_html=True,
    )

    if readings is None:
        st.error(
            "Economic evidence is incomplete. The Environment interpretation should not "
            "be treated as complete until provider-backed readings recover."
        )
    elif str(market.get("status") or "").strip().lower() not in {"connected", "partial"}:
        st.warning(
            "Economic readings are available, but live cross-asset implementation data "
            "is unavailable. Market confirmation is therefore incomplete."
        )

    st.markdown(
        '<div class="ci-env-section-head"><div>'
        '<div class="ci-env-section-kicker">Four macro drivers</div>'
        '<div class="ci-env-section-title">What matters now</div></div>'
        '<div class="ci-env-section-note">Tap detail only when you want the full explanation.</div></div>',
        unsafe_allow_html=True,
    )
    st.markdown(_compact_driver_cards(drivers), unsafe_allow_html=True)

    with st.expander("Explore economic driver detail", expanded=False):
        st.markdown(_driver_detail_html(drivers), unsafe_allow_html=True)

    st.markdown(
        '<section class="ci-transmission"><div class="ci-env-section-kicker">Cross-asset map</div>'
        '<h3>How this backdrop reaches markets</h3>'
        '<div class="ci-env-transmission-copy">The status on each card is the existing '
        'current-backdrop interpretation. It explains support or pressure; it is not a '
        'portfolio instruction and does not claim macro data caused every price move.</div>'
        f'{_compact_market_cards(markets)}</section>',
        unsafe_allow_html=True,
    )

    with st.expander("Explore cross-asset detail", expanded=False):
        st.markdown(_market_detail_html(markets), unsafe_allow_html=True)

    with st.expander("How to read this backdrop and what could change it", expanded=False):
        st.markdown(_review_html(drivers), unsafe_allow_html=True)

    with st.expander("Sources and supporting market data", expanded=False):
        source = _clean(getattr(dashboard, "data_source", "Unavailable")) or "Unavailable"
        evaluated = story._format_time(getattr(readings, "evaluated_at", None))
        st.write(f"Economic source: {source}")
        st.write(f"Economic evidence evaluated: {evaluated}")
        st.write(f"Market session: {story._session(market)}")
        st.write(f"Live quote coverage: {story._coverage(market)}")
        st.write(f"Latest live quote: {_latest_quote_label(market)}")
        app.render_live_environment_market_table()

    decision_reference = "Unavailable"
    if isinstance(briefing, Mapping):
        decision_reference = _clean(
            briefing.get("decision_identifier")
            or briefing.get("identifier")
            or briefing.get("cycle_identifier")
        ) or "Unavailable"
    st.markdown(
        '<div class="ci-env-boundary"><strong>Evidence note</strong>'
        f'<span>{escape(_clean(getattr(dashboard, "data_source", "Unavailable")))} · '
        f'evaluated {escape(story._format_time(getattr(readings, "evaluated_at", None)))}</span>'
        '<span>Environment interprets structural conditions and current cross-asset '
        'implications. Daily developments remain in Today; governed portfolio decisions '
        f'remain in Portfolio · decision reference {escape(decision_reference)}.</span></div>',
        unsafe_allow_html=True,
    )


def install(story: ModuleType) -> None:
    """Install the compact Environment renderer exactly once, after older layers."""

    if getattr(story, _INSTALLED_KEY, False):
        return

    original = story._render_environment

    @wraps(original, updated=())
    def render_environment(app: ModuleType, dependencies: object) -> None:
        _render_environment(story, app, dependencies)

    story._render_environment = render_environment
    setattr(story, _INSTALLED_KEY, True)


__all__ = [
    "_compact_driver_cards",
    "_compact_market_cards",
    "_environment_summary",
    "install",
]
