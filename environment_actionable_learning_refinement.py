"""Make the lower Environment section current, actionable, and easier to scan.

Presentation only. The refinement replaces the dense generic investor lesson with a
current signal -> transmission -> asset example and replaces the vague review note
with explicit evidence conditions for Growth, Inflation, Rates, and Liquidity.
It does not change evidence, forecasts, CIO authority, construction, or execution.
"""

from __future__ import annotations

from functools import wraps
from html import escape
from types import ModuleType
from typing import Mapping, Sequence

import environment_driver_education_runtime as driver_runtime


_INSTALLED_KEY = "_capital_intelligence_environment_actionable_learning_installed"
_LEGACY_SECTION_MARKERS = (
    '<div class="ci-kicker">Investor lesson</div>',
    '<div class="ci-kicker">What would change the view</div>',
)


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _focus_driver(
    drivers: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    """Select the most directional current driver, with market-impact tie breaks."""

    if not drivers:
        return {
            "name": "Environment",
            "value": "Unavailable",
            "state": "Evidence incomplete",
            "bias": 0.0,
            "channel": "Evidence -> market expectations",
            "feeds": ("Cross-asset markets",),
        }
    priority = {"Inflation": 4, "Rates": 3, "Liquidity": 2, "Growth": 1}
    return max(
        drivers,
        key=lambda row: (
            abs(float(row.get("bias", 0.0))),
            priority.get(_clean(row.get("name")), 0),
        ),
    )


def _watch_rows(
    drivers: Sequence[Mapping[str, object]],
) -> tuple[dict[str, str], ...]:
    """Translate each driver state into one concrete next-review condition."""

    by_name = {_clean(row.get("name")): row for row in drivers}

    growth = by_name.get("Growth", {})
    growth_state = _clean(growth.get("state")) or "Evidence incomplete"
    if growth_state == "Supportive":
        growth_trigger = "Unemployment rises toward 5% or the growth state turns soft."
        growth_impact = "That would weaken earnings expectations and increase default risk."
    elif growth_state == "Soft":
        growth_trigger = "Unemployment falls below 5% and the growth trend stops weakening."
        growth_impact = "That would reduce recession risk and improve the case for cyclicals and credit."
    else:
        growth_trigger = "Labor data establishes a sustained improving or weakening trend."
        growth_impact = "That would clarify the direction for cyclical equities and corporate credit."

    inflation = by_name.get("Inflation", {})
    inflation_state = _clean(inflation.get("state")) or "Evidence incomplete"
    if inflation_state == "Elevated pressure":
        inflation_trigger = "Inflation moves into the 2–3% range without growth collapsing."
        inflation_impact = "That would improve the backdrop for bonds and long-duration equities."
    elif inflation_state == "Disinflationary":
        inflation_trigger = "Inflation reaccelerates above 3% on a sustained basis."
        inflation_impact = "That would reduce rate-cut expectations and pressure rate-sensitive assets."
    else:
        inflation_trigger = "Inflation breaks sustainably outside the 2–3% range."
        inflation_impact = "That would reset policy expectations, margins, and valuation pressure."

    rates = by_name.get("Rates", {})
    rates_state = _clean(rates.get("state")) or "Evidence incomplete"
    if rates_state == "Inverted curve":
        rates_trigger = "The curve turns clearly positive while policy rates ease."
        rates_impact = "That would improve lending conditions if growth remains intact."
    elif rates_state == "Upward curve":
        rates_trigger = "The curve flattens or inverts while policy remains restrictive."
        rates_impact = "That would increase caution around future growth, banks, and refinancing."
    elif rates_state == "Flat curve":
        rates_trigger = "The curve moves above +0.15 pp or below −0.15 pp."
        rates_impact = "That would resolve the current ambiguous growth and bank-lending signal."
    else:
        rates_trigger = "Complete policy-rate and yield-curve evidence becomes available."
        rates_impact = "That is required before the financing and valuation signal can be trusted."

    liquidity = by_name.get("Liquidity", {})
    liquidity_state = _clean(liquidity.get("state")) or "Evidence incomplete"
    if liquidity_state == "Supportive":
        liquidity_trigger = "The financial-conditions composite deteriorates below −0.25."
        liquidity_impact = "That would raise spread, volatility, and smaller-company funding risk."
    elif liquidity_state == "Restrictive":
        liquidity_trigger = "The financial-conditions composite improves above −0.25."
        liquidity_impact = "That would reduce funding stress and support credit and smaller companies."
    else:
        liquidity_trigger = "The composite breaks above +0.25 or below −0.25."
        liquidity_impact = "That would confirm meaningfully easier or tighter financial conditions."

    return (
        {
            "name": "Growth",
            "state": growth_state,
            "value": _clean(growth.get("value")) or "Unavailable",
            "trigger": growth_trigger,
            "impact": growth_impact,
        },
        {
            "name": "Inflation",
            "state": inflation_state,
            "value": _clean(inflation.get("value")) or "Unavailable",
            "trigger": inflation_trigger,
            "impact": inflation_impact,
        },
        {
            "name": "Rates",
            "state": rates_state,
            "value": _clean(rates.get("value")) or "Unavailable",
            "trigger": rates_trigger,
            "impact": rates_impact,
        },
        {
            "name": "Liquidity",
            "state": liquidity_state,
            "value": _clean(liquidity.get("value")) or "Unavailable",
            "trigger": liquidity_trigger,
            "impact": liquidity_impact,
        },
    )


def _learning_html(drivers: Sequence[Mapping[str, object]]) -> str:
    focus = _focus_driver(drivers)
    feeds = focus.get("feeds", ())
    assets = (
        " · ".join(_clean(value) for value in feeds if _clean(value))
        if isinstance(feeds, Sequence) and not isinstance(feeds, (str, bytes))
        else _clean(feeds)
    ) or "Cross-asset markets"
    watch_cards = "".join(
        '<article class="ci-review-card">'
        '<div class="ci-review-top">'
        f'<span class="ci-review-name">{escape(row["name"])}</span>'
        f'<span class="ci-review-state">{escape(row["value"])} · {escape(row["state"])}</span>'
        '</div>'
        '<div class="ci-review-label">Watch for</div>'
        f'<div class="ci-review-trigger">{escape(row["trigger"])}</div>'
        f'<div class="ci-review-impact">{escape(row["impact"])}</div>'
        '</article>'
        for row in _watch_rows(drivers)
    )
    return (
        """
<style>
.ci-learning-shell,.ci-review-shell{margin-top:1rem;border:1px solid rgba(93,217,255,.16);border-radius:22px;overflow:hidden;background:linear-gradient(145deg,rgba(16,27,37,.96),rgba(8,15,25,.96));box-shadow:0 18px 45px rgba(0,0,0,.18)}
.ci-learning-head,.ci-review-head{padding:1rem 1.05rem .35rem}.ci-learning-kicker,.ci-review-kicker{font-size:.62rem;font-weight:850;letter-spacing:.14em;text-transform:uppercase;color:#5ad9ff}.ci-learning-title,.ci-review-title{margin:.38rem 0 .25rem;color:#f5f8fc;font-size:1.08rem;line-height:1.25}.ci-learning-subtitle,.ci-review-subtitle{color:#91a2b7;font-size:.72rem;line-height:1.48}
.ci-learning-flow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:.65rem;padding:.7rem 1.05rem 1rem}.ci-learning-step{min-width:0;padding:.82rem;border:1px solid rgba(255,255,255,.075);border-radius:16px;background:rgba(255,255,255,.025)}.ci-learning-step-label{display:flex;align-items:center;gap:.42rem;font-size:.61rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:#8fa1b7}.ci-learning-step-number{display:inline-grid;place-items:center;width:1.35rem;height:1.35rem;border-radius:999px;background:rgba(82,227,164,.1);border:1px solid rgba(82,227,164,.24);color:#8fe7c2}.ci-learning-step-main{margin-top:.55rem;color:#edf4fa;font-size:.82rem;font-weight:780;line-height:1.38}.ci-learning-step-copy{margin-top:.3rem;color:#9eacbd;font-size:.69rem;line-height:1.48}.ci-learning-context{margin:0 1.05rem 1.05rem;padding:.72rem .8rem;border-left:3px solid #52e3a4;border-radius:0 12px 12px 0;background:rgba(82,227,164,.055);color:#afbdcc;font-size:.69rem;line-height:1.5}.ci-learning-context strong{color:#dff8ed}
.ci-review-shell{border-color:rgba(82,227,164,.15)}.ci-review-kicker{color:#52e3a4}.ci-review-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.65rem;padding:.72rem 1.05rem 1.05rem}.ci-review-card{min-width:0;padding:.82rem;border:1px solid rgba(255,255,255,.075);border-radius:16px;background:rgba(255,255,255,.022)}.ci-review-top{display:flex;align-items:flex-start;justify-content:space-between;gap:.55rem}.ci-review-name{color:#eef5fb;font-size:.79rem;font-weight:820}.ci-review-state{max-width:62%;text-align:right;color:#8ea1b6;font-size:.58rem;line-height:1.35}.ci-review-label{margin-top:.62rem;color:#52e3a4;font-size:.58rem;font-weight:850;letter-spacing:.09em;text-transform:uppercase}.ci-review-trigger{margin-top:.27rem;color:#dce7f1;font-size:.72rem;font-weight:720;line-height:1.45}.ci-review-impact{margin-top:.36rem;color:#93a4b7;font-size:.66rem;line-height:1.45}
.ci-env-boundary{margin:.72rem 0 .1rem;padding:.68rem .78rem;border:1px solid rgba(255,255,255,.065);border-radius:13px;background:rgba(255,255,255,.018);color:#6f8197;font-size:.63rem;line-height:1.48}.ci-env-boundary strong{color:#8fa4bb}.ci-env-boundary span{display:block;margin-top:.18rem}
@media(max-width:760px){.ci-learning-shell,.ci-review-shell{border-radius:18px}.ci-learning-head,.ci-review-head{padding:.9rem .9rem .3rem}.ci-learning-flow,.ci-review-grid{grid-template-columns:1fr;padding:.62rem .9rem .9rem}.ci-learning-context{margin:0 .9rem .9rem}.ci-learning-title,.ci-review-title{font-size:1rem}.ci-learning-step,.ci-review-card{padding:.78rem}.ci-review-state{max-width:58%}}
</style>
        """
        '<section class="ci-learning-shell">'
        '<div class="ci-learning-head"><div class="ci-learning-kicker">How to read today’s backdrop</div>'
        '<h3 class="ci-learning-title">Signal → market channel → exposed assets</h3>'
        '<div class="ci-learning-subtitle">A faster way to turn economic data into an investment interpretation without treating it as a trade instruction.</div></div>'
        '<div class="ci-learning-flow">'
        '<article class="ci-learning-step"><div class="ci-learning-step-label"><span class="ci-learning-step-number">1</span>Current signal</div>'
        f'<div class="ci-learning-step-main">{escape(_clean(focus.get("name")))}</div>'
        f'<div class="ci-learning-step-copy">{escape(_clean(focus.get("value")))} · {escape(_clean(focus.get("state")))}</div></article>'
        '<article class="ci-learning-step"><div class="ci-learning-step-label"><span class="ci-learning-step-number">2</span>How it travels</div>'
        f'<div class="ci-learning-step-main">{escape(_clean(focus.get("channel")))}</div>'
        '<div class="ci-learning-step-copy">Follow the economic mechanism before looking at the asset response.</div></article>'
        '<article class="ci-learning-step"><div class="ci-learning-step-label"><span class="ci-learning-step-number">3</span>Markets exposed</div>'
        f'<div class="ci-learning-step-main">{escape(assets)}</div>'
        '<div class="ci-learning-step-copy">These markets are most sensitive to this driver; actual price moves still require market confirmation.</div></article>'
        '</div>'
        f'<div class="ci-learning-context"><strong>Current example:</strong> {escape(_clean(focus.get("name")))} is the strongest directional driver in this snapshot. The flow explains why markets may be sensitive; it does not authorize a portfolio change.</div>'
        '</section>'
        '<section class="ci-review-shell"><div class="ci-review-head"><div class="ci-review-kicker">Next review triggers</div>'
        '<h3 class="ci-review-title">What could change the backdrop</h3>'
        '<div class="ci-review-subtitle">Specific evidence thresholds that would justify re-evaluating the current interpretation.</div></div>'
        f'<div class="ci-review-grid">{watch_cards}</div></section>'
    )


def _boundary_html(story: ModuleType, dashboard: object) -> str:
    readings = getattr(dashboard, "readings", None)
    source = _clean(getattr(dashboard, "data_source", "Unavailable")) or "Unavailable"
    evaluated = story._format_time(getattr(readings, "evaluated_at", None))
    return (
        '<div class="ci-env-boundary"><strong>Evidence note</strong>'
        f'<span>{escape(source)} · evaluated {escape(evaluated)}</span>'
        '<span>Environment interprets structural conditions. Daily developments remain in Today, and governed portfolio decisions remain in Portfolio.</span></div>'
    )


class _StreamlitProxy:
    def __init__(self, streamlit_module: ModuleType, replacement_html: str, boundary_html: str) -> None:
        self._streamlit = streamlit_module
        self._replacement_html = replacement_html
        self._boundary_html = boundary_html

    def __getattr__(self, name: str) -> object:
        return getattr(self._streamlit, name)

    def markdown(self, body: object, *args: object, **kwargs: object) -> object:
        text = str(body)
        if all(marker in text for marker in _LEGACY_SECTION_MARKERS):
            return self._streamlit.markdown(
                self._replacement_html,
                unsafe_allow_html=True,
            )
        return self._streamlit.markdown(body, *args, **kwargs)

    def expander(self, label: object, *args: object, **kwargs: object) -> object:
        refined = (
            "Explore supporting market data"
            if str(label) == "Cross-asset market detail"
            else label
        )
        return self._streamlit.expander(refined, *args, **kwargs)

    def caption(self, body: object, *args: object, **kwargs: object) -> object:
        if str(body).startswith("Economic readings:"):
            return self._streamlit.markdown(
                self._boundary_html,
                unsafe_allow_html=True,
            )
        return self._streamlit.caption(body, *args, **kwargs)


def install(story: ModuleType) -> None:
    """Install the actionable lower-section refinement exactly once."""

    if getattr(story, _INSTALLED_KEY, False):
        return

    original = story._render_environment

    @wraps(original)
    def render_environment(app: ModuleType, dependencies: object) -> None:
        dashboard = app.load_dashboard_data()
        market = app.load_live_market_console()
        drivers = driver_runtime._driver_rows(story, dashboard, market)
        original_streamlit = driver_runtime.st
        original_dashboard_loader = app.load_dashboard_data
        original_market_loader = app.load_live_market_console
        driver_runtime.st = _StreamlitProxy(
            original_streamlit,
            _learning_html(drivers),
            _boundary_html(story, dashboard),
        )
        app.load_dashboard_data = lambda: dashboard
        app.load_live_market_console = lambda: market
        try:
            original(app, dependencies)
        finally:
            driver_runtime.st = original_streamlit
            app.load_dashboard_data = original_dashboard_loader
            app.load_live_market_console = original_market_loader

    story._render_environment = render_environment
    setattr(story, _INSTALLED_KEY, True)


__all__ = ["_focus_driver", "_learning_html", "_watch_rows", "install"]
