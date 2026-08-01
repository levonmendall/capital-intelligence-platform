"""Make the four primary Streamlit surfaces communicate distinct information.

Today: current developments, affected assets, transmission channels, and opportunity discovery.
Environment: growth, inflation, rates, liquidity, regime, and cross-asset confirmation.
Portfolio: current capital, CIO decisions, construction, and implementation.
History: prior decisions, outcomes, execution, and learning.

Presentation only. No investment authority, strategy, sizing, or execution changes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

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
    "today": "Today sources",
    "environment": "Environment sources",
    "portfolio": "Portfolio records",
}


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object, fallback: str) -> str:
    return _clean(value) or fallback


def _joined(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return _clean(value) or fallback
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = [_clean(item) for item in value if _clean(item)]
        return " • ".join(values) if values else fallback
    return fallback


def _market_session(snapshot: Mapping[str, object]) -> str:
    state = snapshot.get("market_open")
    return "Open" if state is True else "Closed" if state is False else "Unavailable"


def _coverage(snapshot: Mapping[str, object]) -> str:
    return (
        f"{int(snapshot.get('quote_count', 0) or 0)}/"
        f"{int(snapshot.get('expected_quote_count', 0) or 0)}"
    )


def _section_label(label: str, summary: object) -> str:
    headline = concise._truncate(summary, 118)
    return label.upper() if not headline else f"{label.upper()} · {headline}"


def _render_surface_lens(
    *,
    title: str,
    kicker: str,
    sections: Sequence[tuple[str, str, object, Any]],
) -> None:
    st.markdown(
        '<div class="interactive-lens-head">'
        f'<div class="interactive-lens-kicker">{escape(kicker)}</div>'
        f'<div class="interactive-lens-title">{escape(title)}</div>'
        '<div class="interactive-lens-hint">'
        "Tap a section icon or headline to expand its context."
        "</div></div>",
        unsafe_allow_html=True,
    )
    for marker, label, summary, detail_renderer in sections:
        with st.expander(_section_label(label, summary), expanded=False):
            st.markdown(
                f'<span class="interactive-lens-marker {escape(marker)}" '
                'aria-hidden="true"></span>',
                unsafe_allow_html=True,
            )
            st.write(_clean(summary) or "No additional detail is available.")
            if detail_renderer is not None:
                detail_renderer()


def _asset_focus(items: Sequence[object]) -> str:
    values = list(
        dict.fromkeys(
            _clean(getattr(item, "affected_investments", ""))
            for item in items
            if _clean(getattr(item, "affected_investments", ""))
        )
    )
    return (
        concise._truncate(" • ".join(values[:3]), 190)
        if values
        else "No investment group has a distinct event-driven sensitivity today."
    )


def _transmission_channels(items: Sequence[object]) -> str:
    channels: list[str] = []
    for item in items:
        raw = getattr(item, "impact_channels", ())
        if isinstance(raw, str):
            raw = (raw,)
        if isinstance(raw, Sequence):
            channels.extend(
                _clean(channel).replace("_", " ")
                for channel in raw
                if _clean(channel)
            )
    unique = list(dict.fromkeys(channels))
    if not unique:
        return (
            "Watch whether developments change rates, earnings expectations, "
            "liquidity, or risk appetite."
        )
    return concise._truncate(
        "The main transmission channels are " + ", ".join(unique[:5]) + ".",
        188,
    )


def _implications(readings: object) -> tuple[tuple[object, object], ...]:
    return tuple(concise.base.economic_investment_implications(readings))


def _implication_summary(items: Sequence[tuple[object, object]]) -> str:
    if not items:
        return (
            "Economic evidence is incomplete; asset-class sensitivity remains "
            "unclassified."
        )
    return concise._truncate(
        " • ".join(
            f"{_clean(title)}: {_clean(explanation)}"
            for title, explanation in items[:2]
        ),
        210,
    )


def _render_implications(items: Sequence[tuple[object, object]]) -> None:
    if not items:
        st.caption("No additional asset-class sensitivity detail is available.")
        return
    for index, (title, explanation) in enumerate(items):
        st.markdown(f"**{_clean(title)}**")
        st.write(_clean(explanation))
        if index != len(items) - 1:
            st.divider()


def _filtered_freshness(entries: Sequence[object], surface: str) -> tuple[object, ...]:
    allowed = _SURFACE_FRESHNESS_LABELS.get(surface)
    if allowed is None:
        return tuple(entries)
    return tuple(item for item in entries if getattr(item, "label", "") in allowed)


def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
    """Show only timestamps used by the active surface."""

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
    entries = _filtered_freshness(entries, surface)
    tone, _ = experience._freshness_tone(entries)
    subject = _SURFACE_FRESHNESS_NAMES.get(surface, "Information")
    label = (
        f"{subject} need attention"
        if tone == "attention"
        else f"{subject} are refreshing"
        if tone == "refreshing"
        else f"{subject} are current"
    )
    st.markdown(
        '<div class="information-health '
        f'{escape(tone)}" role="status" aria-live="polite">'
        '<span class="information-health-dot" aria-hidden="true"></span>'
        '<div class="information-health-copy">'
        f'<div class="information-health-label">{escape(label)}</div>'
        f'<div class="information-health-summary">'
        f'{escape(experience._freshness_summary(entries))}</div>'
        "</div></div>",
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
            "Only information used by this tab is shown here. Other timestamps "
            "remain in their own tabs."
        )


def render_today_market_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Explain current external developments without repeating portfolio decisions."""

    del briefing
    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = concise.base.build_today_items(records)
    _render_surface_lens(
        title="Today's investment developments",
        kicker="Today // current information",
        sections=(
            (
                "lens-section-change",
                "What changed",
                concise._event_headline(items),
                lambda: experience._render_event_field_details(
                    items,
                    records,
                    field_name="summary",
                    empty_message=snapshot.detail,
                    include_sources=True,
                ),
            ),
            (
                "lens-section-investors",
                "Assets in focus",
                _asset_focus(items),
                lambda: experience._render_event_field_details(
                    items,
                    records,
                    field_name="affected_investments",
                    empty_message="No additional affected-investment detail is available.",
                ),
            ),
            (
                "lens-section-portfolio",
                "Transmission channels",
                _transmission_channels(items),
                None,
            ),
            (
                "lens-section-watch",
                "What to watch next",
                concise._event_watchlist(items),
                lambda: experience._render_event_field_details(
                    items,
                    records,
                    field_name="what_to_watch",
                    empty_message=(
                        "Watch rates, earnings expectations, liquidity, and "
                        "cross-asset confirmation."
                    ),
                ),
            ),
        ),
    )
    st.caption(
        concise.base._daily_caption(snapshot)
        + " Today explains current external information; portfolio balances and "
        "the CIO decision remain in Portfolio."
    )


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Explain the structural backdrop without repeating portfolio action."""

    del briefing
    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = concise.base.build_economic_event_items(records)
    dashboard = concise.base.load_dashboard_data()
    readings = dashboard.readings
    implications = _implications(readings)
    watchlist = (
        concise._event_watchlist(items)
        if items
        else (
            "Monitor inflation, labor demand, policy guidance, yield-curve shape, "
            "credit conditions, and cross-asset breadth."
        )
    )

    def render_economic_state() -> None:
        st.write(
            concise._truncate(
                concise.base.economic_snapshot_summary(readings),
                220,
            )
        )
        experience._render_event_field_details(
            items,
            records,
            field_name="summary",
            empty_message=snapshot.detail,
            include_sources=True,
        )

    _render_surface_lens(
        title="Economic and market backdrop",
        kicker="Environment // structural conditions",
        sections=(
            (
                "lens-section-change",
                "Economic state",
                concise._economic_headline(readings),
                render_economic_state,
            ),
            (
                "lens-section-investors",
                "Investment transmission",
                concise._economic_investor_lesson(readings),
                lambda: _render_implications(implications),
            ),
            (
                "lens-section-portfolio",
                "Asset-class sensitivity",
                _implication_summary(implications),
                lambda: _render_implications(implications),
            ),
            (
                "lens-section-watch",
                "What to monitor",
                watchlist,
                lambda: experience._render_event_field_details(
                    items,
                    records,
                    field_name="what_to_watch",
                    empty_message=(
                        "Monitor growth, inflation, policy, yields, liquidity, "
                        "and earnings confirmation."
                    ),
                ),
            ),
        ),
    )
    st.caption(
        concise.base._daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Environment describes "
        "the backdrop; current holdings and CIO action remain in Portfolio."
    )


def render_today_opportunity_scan() -> None:
    """Show discovery progress without repeating current portfolio action."""

    snapshot = concise.base.load_opportunity_scan()
    concise.ui.page_header(
        "Opportunity scan",
        (
            "What the governed research funnel found, how far the strongest "
            "alternative progressed, and the main blocker."
        ),
        "SCAN",
    )
    concise.ui.status_list(
        (
            (
                "Strongest alternative",
                snapshot.strongest_alternative,
                "Best relative opportunity identified by the scan.",
            ),
            (
                "Furthest stage reached",
                snapshot.strongest_stage,
                "Process progress; not an approval or trade instruction.",
            ),
            (
                "Main blocker",
                snapshot.main_reason,
                "Primary reason the opportunity did not advance.",
            ),
        ),
        variant="today",
    )
    with st.expander("View opportunity funnel counts", expanded=False):
        concise.ui.metric_grid(
            (
                (
                    "U.S. companies screened",
                    concise.base._count_label(snapshot.broad_assets_screened),
                    "Broad eligible universe",
                ),
                (
                    "Market snapshots",
                    concise.base._count_label(snapshot.snapshot_covered),
                    "Usable initial evidence",
                ),
                (
                    "Companies deepened",
                    concise.base._count_label(snapshot.companies_deepened),
                    "Full company analysis",
                ),
                (
                    "Governed candidates",
                    concise.base._count_label(snapshot.governed_candidates),
                    "Complete candidate evidence",
                ),
                (
                    "Reached CIO queue",
                    concise.base._count_label(snapshot.opportunities_reaching_cio),
                    "Qualified opportunities",
                ),
            ),
            variant="today",
        )
        st.caption(
            f"Scan as of {concise.ui.format_datetime(snapshot.as_of)} · "
            f"production context {snapshot.decision_reference}. {snapshot.detail}"
        )


def _render_today(app: ModuleType, dependencies: object) -> None:
    del dependencies
    briefing = app._latest("daily_cio_briefing")
    live_market = app.load_live_market_console()
    snapshot = concise.base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = concise.base.build_today_items(records)

    app.page_header(
        "Investment world today",
        (
            "Current developments, affected assets, transmission channels, and "
            "the evidence to monitor next."
        ),
        "NOW",
    )
    render_today_market_brief(briefing=briefing)
    render_information_freshness(briefing=briefing, surface="today")
    app.page_header(
        "Market pulse",
        "Live market availability and the current external-information workload.",
        "01",
    )
    app.status_list(
        (
            ("Market session", _market_session(live_market), "Trading-session state."),
            ("Live quote coverage", _coverage(live_market), "Governed coverage."),
            (
                "Developments in focus",
                f"{len(items)} relevant development{'s' if len(items) != 1 else ''}",
                concise._event_headline(items),
            ),
            (
                "Watchlist",
                concise._event_watchlist(items),
                "Evidence to monitor before the next briefing.",
            ),
        ),
        variant="today",
    )
    render_today_opportunity_scan()
    with st.expander("Live market detail", expanded=False):
        app.render_live_market_status()
    with st.expander("How the Today surface works", expanded=False):
        app.surface_story(
            "Today",
            (
                ("Observe", "Collect current market, policy, company, and public developments."),
                ("Filter", "Keep only reliable, investment-relevant information."),
                ("Explain", "Identify affected assets and transmission channels."),
                ("Monitor", "State what evidence should be watched next."),
            ),
        )


def _render_environment(app: ModuleType, dependencies: object) -> None:
    del dependencies
    payload = app._diagnostic_environment()
    environment = None if payload is None else payload.get("environment")
    dashboard = app.load_dashboard_data()
    readings = dashboard.readings
    live_market = app.load_live_market_console()
    briefing = app._latest("daily_cio_briefing")

    app.page_header(
        "Economy and investing",
        (
            "The growth, inflation, rates, liquidity, regime, and cross-asset "
            "backdrop."
        ),
        "ECON",
    )
    render_environment_economic_brief(briefing=briefing)
    render_information_freshness(briefing=briefing, surface="environment")

    unemployment = (
        "Unavailable" if readings is None else f"{readings.unemployment_rate:.1f}%"
    )
    inflation = (
        "Unavailable" if readings is None else f"{readings.inflation_rate:.2f}%"
    )
    policy_rate = (
        "Unavailable" if readings is None else f"{readings.federal_funds_rate:.2f}%"
    )
    yield_curve = (
        "Unavailable"
        if readings is None
        else f"{float(getattr(readings, 'yield_curve_spread', 0.0)):+.2f} pp"
    )
    if isinstance(environment, Mapping):
        regime = _plain(environment.get("regime"), "Unavailable")
        state = _plain(environment.get("headline"), "Environment record available.")
        detail = _plain(environment.get("summary"), "No additional summary available.")
        review = _joined(
            environment.get("review_conditions", ()),
            "Review growth, inflation, policy, liquidity, and cross-asset confirmation.",
        )
    elif live_market.get("status") in {"connected", "partial"} and readings is not None:
        regime = "Not separately classified"
        state = "Provider-backed market and economic evidence is available."
        detail = (
            f"Coverage {_coverage(live_market)} · inflation {inflation} · "
            f"unemployment {unemployment} · policy rate {policy_rate}."
        )
        review = (
            "A material change in growth, inflation, policy, liquidity, credit, "
            "or market breadth would change the environment reading."
        )
    else:
        regime = "Unavailable"
        state = "Environment evidence is incomplete."
        detail = _plain(live_market.get("detail"), str(dashboard.status))
        review = (
            "Provider and macro evidence must recover before the environment "
            "can be treated as complete."
        )

    app.page_header(
        "Environment map",
        "Structural conditions and cross-asset confirmation.",
        "01",
    )
    app.status_list(
        (
            ("Environment state", state, detail),
            ("Regime", regime, "Governed classification when evidence is complete."),
            (
                "Rates and curve",
                f"Policy rate {policy_rate} · 10Y−2Y {yield_curve}",
                "Financing conditions and policy expectations.",
            ),
            (
                "Cross-asset confirmation",
                f"{_market_session(live_market)} · {_coverage(live_market)} coverage",
                "Market breadth used to confirm or challenge the macro reading.",
            ),
        ),
        variant="environment",
    )
    app.page_header(
        "Macro signals",
        "Readings most relevant to growth, inflation, and discount rates.",
        "02",
    )
    app.metric_grid(
        (
            ("Inflation", inflation, "Purchasing power and margins"),
            ("Unemployment", unemployment, "Growth and labor demand"),
            ("Federal funds", policy_rate, "Financing and discount rate"),
            ("10Y − 2Y", yield_curve, "Growth and policy expectations"),
        ),
        variant="environment",
    )
    with st.expander("Conditions that would change the environment reading"):
        st.write(review)
    with st.expander("Cross-asset market detail"):
        app.render_live_environment_market_table()
    with st.expander("How the Environment surface works"):
        app.surface_story(
            "Environment",
            (
                ("Measure", "Read growth, inflation, policy, credit, and liquidity."),
                ("Classify", "Describe the regime without creating a trade signal."),
                ("Confirm", "Compare macro conditions with cross-asset behavior."),
                ("Monitor", "Identify what would change the classification."),
            ),
        )


def install(app_impl: ModuleType) -> None:
    """Install distinct Today and Environment surfaces once."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return
    app_impl.render_information_freshness = render_information_freshness
    app_impl.render_today_market_brief = render_today_market_brief
    app_impl.render_environment_economic_brief = render_environment_economic_brief
    app_impl.render_today_opportunity_scan = render_today_opportunity_scan

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
    "install",
    "render_environment_economic_brief",
    "render_information_freshness",
    "render_today_market_brief",
    "render_today_opportunity_scan",
]
