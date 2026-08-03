"""Connect Environment readings to their market transmission.

Presentation only: current reading -> economic signal -> market channel -> assets.
The cross-asset map separates structural education from the current backdrop's
likely near-term support or pressure. It does not claim that macro conditions
caused every intraday market move.
"""

from __future__ import annotations

from html import escape
from types import ModuleType
from typing import Mapping, Sequence

import streamlit as st


_INSTALLED_KEY = "_capital_intelligence_environment_driver_education_installed"


def _number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _growth_takeaway(value: float | None) -> str:
    if value is None:
        return "The labor-market reading is unavailable, so its market implication is uncertain."
    if value < 4.0:
        current = f"At {value:.1f}%, unemployment is low and labor demand is relatively tight. "
    elif value < 5.0:
        current = (
            f"At {value:.1f}%, unemployment is consistent with a still-functioning labor market, "
            "although its direction matters more than one observation. "
        )
    else:
        current = f"At {value:.1f}%, labor-market slack is elevated and demand may be weakening. "
    return current + (
        "Lower or stable unemployment usually supports spending, earnings, cyclical equities, and "
        "credit. A sustained rise usually increases recession and default risk. Extremely tight "
        "labor markets can also add wage and inflation pressure."
    )


def _inflation_takeaway(value: float | None) -> str:
    if value is None:
        return "The inflation reading is unavailable, so its rate and valuation effect is uncertain."
    if value < 2.0:
        current = f"At {value:.2f}%, inflation is below the common 2% policy reference point. "
    elif value <= 3.0:
        current = (
            f"At {value:.2f}%, inflation is near the range markets often associate with price "
            "stability. "
        )
    elif value < 5.0:
        current = (
            f"At {value:.2f}%, inflation remains above the common 2% policy reference point, which "
            "can restrain rate-cut expectations. "
        )
    else:
        current = f"At {value:.2f}%, inflation creates substantial purchasing-power and policy pressure. "
    return current + (
        "Lower inflation generally supports bonds and long-duration equities because expected rates "
        "and discount rates can fall. Higher inflation usually pressures those assets, although "
        "commodities and companies with pricing power may benefit. A sharp drop caused by collapsing "
        "demand is less positive for equities."
    )


def _rates_takeaway(policy: float | None, curve: float | None) -> str:
    if policy is None:
        return "The policy-rate reading is unavailable, so financing and valuation effects are uncertain."
    if policy < 2.0:
        current = f"A {policy:.2f}% policy rate represents relatively inexpensive financing. "
    elif policy <= 4.5:
        current = f"A {policy:.2f}% policy rate still imposes a meaningful borrowing and valuation cost. "
    else:
        current = f"A {policy:.2f}% policy rate is strongly restrictive for many borrowers. "
    if curve is None:
        curve_copy = "The yield-curve signal is unavailable. "
    elif curve > 0.15:
        curve_copy = (
            f"The {curve:+.2f} percentage-point curve is upward sloping, a more normal shape that can "
            "improve bank lending economics. "
        )
    elif curve < -0.15:
        curve_copy = (
            f"The {curve:+.2f} percentage-point curve is inverted, a caution signal for future growth "
            "and lending conditions. "
        )
    else:
        curve_copy = f"The {curve:+.2f} percentage-point curve is nearly flat. "
    return current + curve_copy + (
        "Lower rates typically support bonds, housing, and long-duration equities by reducing financing "
        "costs and discount rates. Higher rates pressure those assets, make cash more competitive, and "
        "can support the currency. Rate cuts caused by recession can still hurt cyclical equities."
    )


def _liquidity_takeaway(score: float | None, coverage: str) -> str:
    if score is None:
        current = "The credit-and-volatility financial-conditions composite is unavailable. "
    elif score >= 0.25:
        current = f"The {score:+.2f} composite indicates relatively supportive financial conditions. "
    elif score <= -0.25:
        current = f"The {score:+.2f} composite indicates restrictive financial conditions. "
    else:
        current = f"The {score:+.2f} composite indicates mixed financial conditions. "
    return current + (
        "More supportive liquidity usually narrows credit spreads and helps smaller companies and risk "
        "assets. Tighter liquidity usually widens spreads and raises volatility. "
        f"The separate {coverage}-quote figure measures evidence coverage, not market liquidity."
    )


def _state_bias(state: str, *, positive: str, negative: str) -> float:
    normalized = state.strip().lower()
    if normalized == positive.lower():
        return 1.0
    if normalized == negative.lower():
        return -1.0
    return 0.0


def _rate_bias(policy: float | None, curve: float | None) -> float:
    if policy is None:
        return 0.0
    if policy < 2.0:
        bias = 0.8
    elif policy <= 4.5:
        bias = -0.35
    else:
        bias = -1.0
    if curve is not None and curve < -0.15:
        bias -= 0.25
    elif curve is not None and curve > 0.15:
        bias += 0.1
    return max(min(bias, 1.0), -1.0)


def _bias_label(score: float) -> str:
    if score >= 0.75:
        return "Supportive"
    if score >= 0.2:
        return "Cautiously supportive"
    if score <= -0.75:
        return "Pressured"
    if score <= -0.2:
        return "Cautiously pressured"
    return "Mixed"


def _bias_tone(label: str) -> str:
    normalized = label.lower()
    if "supportive" in normalized:
        return "positive"
    if "pressured" in normalized:
        return "negative"
    return "mixed"


def _driver_rows(
    story: ModuleType,
    dashboard: object,
    market: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    readings = getattr(dashboard, "readings", None)
    snapshot = getattr(dashboard, "snapshot", None)
    unemployment = _number(getattr(readings, "unemployment_rate", None))
    inflation = _number(getattr(readings, "inflation_rate", None))
    policy = _number(getattr(readings, "federal_funds_rate", None))
    curve = _number(getattr(readings, "yield_curve_spread", None))
    credit = _number(getattr(snapshot, "credit", None))
    volatility = _number(getattr(snapshot, "volatility", None))
    liquidity = -(credit + volatility) / 2 if credit is not None and volatility is not None else None

    growth_state = story._score(getattr(snapshot, "growth", None), "Supportive", "Mixed", "Soft")
    inflation_state = story._score(
        getattr(snapshot, "inflation", None), "Elevated pressure", "Balanced", "Disinflationary"
    )
    if curve is None:
        rate_state = "Evidence incomplete"
    elif curve > 0.15:
        rate_state = "Upward curve"
    elif curve < -0.15:
        rate_state = "Inverted curve"
    else:
        rate_state = "Flat curve"
    liquidity_state = story._score(liquidity, "Supportive", "Mixed", "Restrictive")
    coverage = story._coverage(market)

    return (
        {
            "name": "Growth",
            "metric": "Unemployment rate · inverse growth signal",
            "value": f"{unemployment:.1f}%" if unemployment is not None else "Unavailable",
            "state": growth_state,
            "bias": _state_bias(growth_state, positive="Supportive", negative="Soft"),
            "takeaway": _growth_takeaway(unemployment),
            "channel": "Labor demand → spending and earnings",
            "sensitive": "Cyclical equities, small caps, consumer sectors, and credit.",
            "feeds": ("Equities", "Credit"),
        },
        {
            "name": "Inflation",
            "metric": "Inflation rate",
            "value": f"{inflation:.2f}%" if inflation is not None else "Unavailable",
            "state": inflation_state,
            "bias": _state_bias(
                inflation_state,
                positive="Disinflationary",
                negative="Elevated pressure",
            ),
            "takeaway": _inflation_takeaway(inflation),
            "channel": "Prices → policy expectations and margins",
            "sensitive": "Bonds, growth equities, commodities, and inflation hedges.",
            "feeds": ("Bonds", "Equities", "Dollar & commodities"),
        },
        {
            "name": "Rates",
            "metric": "Policy rate · yield-curve spread",
            "value": (
                f"{policy:.2f}% · curve {curve:+.2f} pp"
                if policy is not None and curve is not None
                else "Unavailable"
            ),
            "state": rate_state,
            "bias": _rate_bias(policy, curve),
            "takeaway": _rates_takeaway(policy, curve),
            "channel": "Financing cost → bond prices and valuations",
            "sensitive": "Treasuries, long-duration equities, housing, banks, and the dollar.",
            "feeds": ("Equities", "Bonds", "Dollar & commodities"),
        },
        {
            "name": "Liquidity",
            "metric": "Credit-and-volatility financial-conditions composite",
            "value": f"{liquidity:+.2f}" if liquidity is not None else "Unavailable",
            "state": liquidity_state,
            "bias": _state_bias(liquidity_state, positive="Supportive", negative="Restrictive"),
            "takeaway": _liquidity_takeaway(liquidity, coverage),
            "channel": "Funding conditions → spreads and risk appetite",
            "sensitive": "Credit spreads, smaller companies, volatility, and crowded positions.",
            "feeds": ("Credit", "Equities"),
        },
    )


def _cross_asset_rows(drivers: Sequence[Mapping[str, object]]) -> tuple[dict[str, str], ...]:
    by_name = {str(driver["name"]): driver for driver in drivers}
    growth, inflation = by_name["Growth"], by_name["Inflation"]
    rates, liquidity = by_name["Rates"], by_name["Liquidity"]

    growth_bias = float(growth.get("bias", 0.0))
    inflation_bias = float(inflation.get("bias", 0.0))
    rate_bias = float(rates.get("bias", 0.0))
    liquidity_bias = float(liquidity.get("bias", 0.0))

    equity_label = _bias_label(
        0.9 * growth_bias + 0.7 * rate_bias + 0.5 * liquidity_bias + 0.2 * inflation_bias
    )
    bond_label = _bias_label(0.9 * inflation_bias + rate_bias)
    credit_label = _bias_label(0.8 * growth_bias + 0.8 * liquidity_bias + 0.2 * rate_bias)
    currency_label = "Mixed cross-currents"

    return (
        {
            "name": "Equities",
            "drivers": "Growth + Rates + Liquidity",
            "copy": (
                f"Growth is {str(growth['state']).lower()}, rates show a {str(rates['state']).lower()} "
                f"signal, and liquidity is {str(liquidity['state']).lower()}. Earnings support helps, "
                "while expensive financing or tighter liquidity can limit valuation upside."
            ),
            "today_label": equity_label,
            "today_tone": _bias_tone(equity_label),
            "today_copy": (
                f"The current combination of {str(growth['state']).lower()} growth, "
                f"{str(liquidity['state']).lower()} liquidity, and the present rate backdrop is "
                "supporting the earnings side of equities while limiting how much investors may pay "
                "for distant cash flows. Cyclicals can hold up better than highly rate-sensitive shares."
            ),
        },
        {
            "name": "Bonds",
            "drivers": "Inflation + Rates",
            "copy": (
                f"Inflation is {str(inflation['state']).lower()} and rates show a "
                f"{str(rates['state']).lower()} signal. Falling inflation or lower expected rates "
                "generally supports bond prices; renewed inflation pressure generally hurts them."
            ),
            "today_label": bond_label,
            "today_tone": _bias_tone(bond_label),
            "today_copy": (
                f"With inflation currently {str(inflation['state']).lower()} and financing costs still "
                "meaningful, the backdrop is more challenging for longer-duration bonds. Bond prices "
                "would receive clearer support from softer inflation or lower expected policy rates."
            ),
        },
        {
            "name": "Credit",
            "drivers": "Growth + Liquidity",
            "copy": (
                f"Growth is {str(growth['state']).lower()} and liquidity is "
                f"{str(liquidity['state']).lower()}. Strong earnings and easy funding can compress "
                "spreads; weaker activity or tighter funding raises default and refinancing risk."
            ),
            "today_label": credit_label,
            "today_tone": _bias_tone(credit_label),
            "today_copy": (
                f"The {str(growth['state']).lower()} growth signal is helping corporate cash-flow and "
                f"default expectations today, while {str(liquidity['state']).lower()} liquidity limits "
                "how aggressively spreads can tighten. Lower-quality and refinancing-sensitive issuers "
                "remain the most exposed."
            ),
        },
        {
            "name": "Dollar & commodities",
            "drivers": "Rates + Inflation + Growth",
            "copy": (
                "Higher relative rates can support a currency. Strong growth can support commodity "
                "demand, while inflation and physical supply determine the commodity response."
            ),
            "today_label": currency_label,
            "today_tone": _bias_tone(currency_label),
            "today_copy": (
                f"The rate backdrop can support the dollar, while {str(growth['state']).lower()} growth "
                f"and {str(inflation['state']).lower()} inflation can keep parts of the commodity complex "
                "firm. Energy, metals, and the currency can still diverge because physical supply and "
                "relative central-bank policy matter independently."
            ),
        },
    )


def _render_environment(story: ModuleType, app: ModuleType, dependencies: object) -> None:
    del dependencies
    story._styles()
    st.markdown(
        """
<style>
.ci-driver-metric{margin-top:.5rem;font-size:.61rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#7f91a8}
.ci-driver-takeaway{margin:.72rem 0;padding:.72rem .76rem;border:1px solid rgba(82,227,164,.16);border-left:3px solid #52e3a4;border-radius:12px;background:rgba(82,227,164,.045)}
.ci-driver-takeaway-label{font-size:.61rem;font-weight:850;letter-spacing:.09em;text-transform:uppercase;color:#52e3a4;margin-bottom:.34rem}
.ci-driver-takeaway-copy{font-size:.73rem;line-height:1.52;color:#c2cedc}.ci-driver-path{margin-top:.58rem;font-size:.67rem;line-height:1.45;color:#91a2b7}.ci-driver-path strong{color:#dfe8f2}
.ci-driver-feeds,.ci-market-drivers,.ci-market-evidence{display:flex;gap:.34rem;flex-wrap:wrap;margin-top:.55rem}.ci-driver-feed,.ci-market-driver,.ci-market-evidence-chip{padding:.25rem .48rem;border-radius:999px;border:1px solid rgba(82,227,164,.18);background:rgba(82,227,164,.05);color:#9ddfc5;font-size:.58rem;font-weight:780}
.ci-market-today{margin-top:.78rem;padding:.72rem .78rem;border:1px solid rgba(90,217,255,.17);border-left:3px solid #5ad9ff;border-radius:12px;background:rgba(90,217,255,.045)}
.ci-market-today-top{display:flex;align-items:center;justify-content:space-between;gap:.55rem;flex-wrap:wrap}.ci-market-today-label{font-size:.61rem;font-weight:850;letter-spacing:.09em;text-transform:uppercase;color:#5ad9ff}.ci-market-bias{padding:.24rem .48rem;border-radius:999px;font-size:.58rem;font-weight:820;letter-spacing:.025em;border:1px solid}.ci-market-bias-positive{color:#9de6c8;background:rgba(82,227,164,.08);border-color:rgba(82,227,164,.24)}.ci-market-bias-negative{color:#ffc6a7;background:rgba(255,149,92,.08);border-color:rgba(255,149,92,.24)}.ci-market-bias-mixed{color:#d7c9ff;background:rgba(166,139,255,.08);border-color:rgba(166,139,255,.24)}.ci-market-today-copy{margin-top:.46rem;font-size:.71rem;line-height:1.52;color:#c3cfdd}
</style>
        """,
        unsafe_allow_html=True,
    )
    payload = app._diagnostic_environment()
    environment = payload.get("environment") if isinstance(payload, Mapping) else None
    dashboard = app.load_dashboard_data()
    market = app.load_live_market_console()
    briefing = app._latest("daily_cio_briefing")
    readings = getattr(dashboard, "readings", None)
    drivers = _driver_rows(story, dashboard, market)

    regime = story._clean(environment.get("regime")) if isinstance(environment, Mapping) else ""
    headline = story._clean(environment.get("headline")) if isinstance(environment, Mapping) else ""
    summary = story._clean(environment.get("summary")) if isinstance(environment, Mapping) else ""
    review_conditions = environment.get("review_conditions", ()) if isinstance(environment, Mapping) else ()
    regime = regime or "Current macro backdrop"
    headline = headline or (
        "Provider-backed economic evidence is available" if readings is not None else "Economic evidence is incomplete"
    )
    summary = summary or (
        story.concise.base.economic_snapshot_summary(readings)
        if readings is not None
        else story._clean(getattr(dashboard, "status", "")) or "Economic data is unavailable."
    )
    review = (
        " • ".join(story._unique(review_conditions, 6))
        if isinstance(review_conditions, Sequence) and not isinstance(review_conditions, (str, bytes))
        else story._clean(review_conditions)
    )
    review = review or (
        "A material change in growth, inflation, policy, credit, liquidity, or cross-asset confirmation "
        "would change this backdrop."
    )

    app.page_header(
        "Economy and investing",
        "Read each number, follow its market channel, and see which assets are most exposed.",
        "ECON",
    )
    app.render_information_freshness(briefing=briefing, surface="environment")
    st.markdown(
        '<section class="ci-env-hero"><div class="ci-kicker">Environment // structural conditions</div>'
        f'<h2>{escape(regime)}</h2><div class="ci-deck"><strong>{escape(headline)}</strong><br>{escape(summary)}</div>'
        '<div class="ci-tags" style="margin-top:.65rem">'
        f'<span class="ci-chip">{escape(story._clean(getattr(dashboard, "data_source", "Data unavailable")))}</span>'
        f'<span class="ci-chip">{escape(story._age_label(getattr(readings, "evaluated_at", None)))}</span>'
        f'<span class="ci-chip">Market {story._session(market).lower()}</span></div></section>',
        unsafe_allow_html=True,
    )

    cards = "".join(
        '<article class="ci-driver"><div class="ci-driver-top">'
        f'<div class="ci-driver-name">{escape(str(driver["name"]))}</div>'
        f'<div class="ci-state">{escape(str(driver["state"]))}</div></div>'
        f'<div class="ci-driver-metric">{escape(str(driver["metric"]))}</div>'
        f'<div class="ci-driver-value">{escape(str(driver["value"]))}</div>'
        '<div class="ci-driver-takeaway"><div class="ci-driver-takeaway-label">Market takeaway</div>'
        f'<div class="ci-driver-takeaway-copy">{escape(str(driver["takeaway"]))}</div></div>'
        f'<div class="ci-driver-path"><strong>Market channel:</strong> {escape(str(driver["channel"]))}</div>'
        f'<div class="ci-driver-path"><strong>Most sensitive:</strong> {escape(str(driver["sensitive"]))}</div>'
        '<div class="ci-driver-feeds">'
        + "".join(
            f'<span class="ci-driver-feed">Feeds into {escape(str(asset))}</span>'
            for asset in driver["feeds"]
        )
        + "</div></article>"
        for driver in drivers
    )
    st.markdown(f'<section class="ci-driver-grid">{cards}</section>', unsafe_allow_html=True)

    market_cards = "".join(
        '<article class="ci-market"><div class="ci-market-name">'
        f'{escape(row["name"])}</div><div class="ci-market-drivers">'
        + "".join(
            f'<span class="ci-market-driver">{escape(part.strip())}</span>'
            for part in row["drivers"].split("+")
        )
        + f'</div><div class="ci-market-copy">{escape(row["copy"])}</div>'
        + '<div class="ci-market-today"><div class="ci-market-today-top">'
        + '<span class="ci-market-today-label">Affecting markets today</span>'
        + f'<span class="ci-market-bias ci-market-bias-{escape(row["today_tone"])}">{escape(row["today_label"])}</span>'
        + f'</div><div class="ci-market-today-copy">{escape(row["today_copy"])}</div></div></article>'
        for row in _cross_asset_rows(drivers)
    )
    st.markdown(
        '<section class="ci-transmission"><div class="ci-meta"><span class="ci-rank">Cross-asset map</span></div>'
        '<h3 style="color:#f3f8fd;margin:.35rem 0 .35rem">How this backdrop reaches markets</h3>'
        '<div class="ci-copy" style="margin-bottom:.5rem"><strong>Where the four readings meet:</strong> '
        'the labels below point back to the driver cards above, so each market conclusion shows which '
        'economic readings produced it.</div>'
        '<div class="ci-copy" style="margin-bottom:.55rem"><strong>Affecting markets today:</strong> '
        'the highlighted block in each card summarizes the near-term support or pressure implied by the '
        'current backdrop. It is an interpretation of current conditions, not proof that macro data caused '
        'every intraday price move.</div>'
        '<div class="ci-market-evidence">'
        f'<span class="ci-market-evidence-chip">Session {escape(story._session(market).lower())}</span>'
        f'<span class="ci-market-evidence-chip">{escape(story._coverage(market))} live quotes</span>'
        '</div>'
        f'<div class="ci-market-grid">{market_cards}</div></section>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<section class="ci-pair"><div class="ci-panel"><div class="ci-kicker">Investor lesson</div>'
        '<h3>Connect the page from number to asset</h3><div class="ci-copy"><strong>1. Read the number.</strong> '
        'Identify what is measured. <strong>2. Read the direction.</strong> A rising or falling value can matter more '
        'than its level. <strong>3. Follow the channel.</strong> Growth reaches earnings, inflation reaches policy, '
        'rates reach financing and valuations, and liquidity reaches risk premiums. <strong>4. Find the asset.</strong> '
        'Example: lower inflation → lower expected rates → lower yields and discount rates → potential support for '
        'bonds and long-duration equities.</div></div>'
        '<div class="ci-panel"><div class="ci-kicker">What would change the view</div><h3>Conditions that deserve the next review</h3>'
        f'<div class="ci-copy">{escape(review)}</div></div></section>',
        unsafe_allow_html=True,
    )
    with st.expander("Cross-asset market detail", expanded=False):
        app.render_live_environment_market_table()
    st.caption(
        f"Economic readings: {story._clean(getattr(dashboard, 'data_source', 'Unavailable'))} · evaluated "
        f"{story._format_time(getattr(readings, 'evaluated_at', None))}. Environment explains structural "
        "conditions and the current backdrop's market implications; daily developments remain in Today "
        "and portfolio action remains in Portfolio."
    )


def install(story: ModuleType) -> None:
    """Install the connected educational renderer before final surface ownership."""

    if getattr(story, _INSTALLED_KEY, False):
        return

    def render_environment(app: ModuleType, dependencies: object) -> None:
        _render_environment(story, app, dependencies)

    story._render_environment = render_environment
    setattr(story, _INSTALLED_KEY, True)


__all__ = ["_bias_label", "_cross_asset_rows", "_driver_rows", "install"]
