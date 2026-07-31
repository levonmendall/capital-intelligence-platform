"""Concise synopsis-first presentation for the four operating surfaces.

Each surface keeps one portfolio-first summary visible and places supporting
market, economic, opportunity, accountability, and freshness detail behind
collapsed expanders. This module changes presentation only; it grants no
candidate, sizing, construction, execution, policy, or real-money authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

import operating_intelligence_ui as base
import premium_ui as ui
from educational_market_briefing_ui import economic_portfolio_lens


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: object, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    shortened = text[: max(1, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (shortened or text[: max(1, limit - 1)]) + "…"


def _briefing_value(
    briefing: Mapping[str, Any] | None,
    field_name: str,
    fallback: str,
    *,
    limit: int,
) -> str:
    value = briefing.get(field_name) if isinstance(briefing, Mapping) else None
    return _truncate(_clean(value) or fallback, limit)


def _decision_reference(briefing: Mapping[str, Any] | None) -> str:
    return base._briefing_reference(briefing)


def _event_headline(items: Sequence[object]) -> str:
    if not items:
        return "No new development cleared the relevance threshold today."
    primary = _truncate(getattr(items[0], "title", "Market development"), 108)
    remaining = len(items) - 1
    if remaining <= 0:
        return primary
    suffix = "development" if remaining == 1 else "developments"
    return f"{primary} · {remaining} other portfolio-relevant {suffix}."


def _event_portfolio_fallback(items: Sequence[object]) -> str:
    impacts = [
        _clean(getattr(item, "portfolio_lens", ""))
        for item in items[:2]
        if _clean(getattr(item, "portfolio_lens", ""))
    ]
    return _truncate(
        " ".join(impacts)
        or "The current information does not independently justify changing the portfolio.",
        180,
    )


def _event_watchlist(items: Sequence[object]) -> str:
    watches: list[str] = []
    seen: set[str] = set()
    for item in items[:4]:
        watch = _truncate(getattr(item, "what_to_watch", ""), 96)
        key = _clean(watch).casefold().strip(" .…")
        if not key or key in seen:
            continue
        seen.add(key)
        watches.append(watch)
        if len(watches) == 2:
            break
    if not watches:
        return "Watch rates, earnings expectations, liquidity, and cross-asset confirmation."
    return _truncate(" • ".join(watches), 176)


def _daily_investor_lesson(items: Sequence[object]) -> str:
    affected = [
        _clean(getattr(item, "affected_investments", ""))
        for item in items[:3]
        if _clean(getattr(item, "affected_investments", ""))
    ]
    if affected:
        return _truncate(
            "The main transmission is through " + ", ".join(affected) + ". "
            "The relevant question is whether the event changes expected return, risk, or liquidity.",
            220,
        )
    return (
        "Daily events matter only when they change expected growth, interest rates, risk appetite, "
        "liquidity, or the relative attractiveness of an investable asset."
    )


def _economic_investor_lesson(readings: object) -> str:
    if readings is None:
        return (
            "Economic data matters through four channels: company earnings, interest rates, inflation, "
            "and liquidity. Incomplete data should not create a portfolio conclusion."
        )
    spread = float(getattr(readings, "yield_curve_spread", 0.0))
    curve = "upward sloping" if spread > 0 else "inverted" if spread < 0 else "flat"
    return (
        f"Growth affects earnings, inflation affects purchasing power and margins, and policy rates affect "
        f"discount rates and financing costs. The 10-year minus 2-year curve is {curve} ({spread:+.2f} pp)."
    )


def _economic_headline(readings: object) -> str:
    if readings is None:
        return "The latest economic picture is incomplete, so no standalone conclusion is warranted."
    return (
        f"Inflation {float(getattr(readings, 'inflation_rate', 0.0)):.2f}% · "
        f"unemployment {float(getattr(readings, 'unemployment_rate', 0.0)):.1f}% · "
        f"policy rate {float(getattr(readings, 'federal_funds_rate', 0.0)):.2f}% · "
        f"10Y−2Y {float(getattr(readings, 'yield_curve_spread', 0.0)):+.2f} pp."
    )


def _render_lens_context(
    *,
    what_changed: object,
    why_investors_care: object,
    portfolio_effect: object,
    cio_response: object,
    watch_next: object,
) -> None:
    sections = (
        ("What changed", what_changed),
        ("Why investors care", why_investors_care),
        ("Portfolio effect", portfolio_effect),
        ("CIO response", cio_response),
        ("What to watch next", watch_next),
    )
    for index, (label, value) in enumerate(sections):
        st.markdown(f"**{label}**")
        st.write(_clean(value) or "No additional detail is available.")
        if index != len(sections) - 1:
            st.divider()


def _render_event_detail(
    items: Sequence[object],
    records: Sequence[Mapping[str, Any]],
    briefing: Mapping[str, Any] | None,
) -> None:
    if not items:
        st.info("No additional portfolio-relevant development is available for this period.")
        return
    decision_reference = _decision_reference(briefing)
    for index, item in enumerate(items, start=1):
        record = base._matching_record(item, records)
        source_url = base._record_source_url(record) if isinstance(record, Mapping) else None
        st.markdown(f"**{index}. {_clean(item.title)}**")
        st.write(f"**What changed:** {_clean(item.summary)}")
        st.write(f"**Why investors care:** {_clean(item.affected_investments)}")
        st.write(f"**Portfolio connection:** {_clean(item.portfolio_lens)}")
        st.write(f"**What to watch next:** {_clean(item.what_to_watch)}")
        st.caption(
            f"CIO relevance: {base.classify_event_cio_relevance(item, briefing)} · "
            f"Most affected: {_clean(item.affected_investments)} · "
            f"Watch next: {_clean(item.what_to_watch)}"
        )
        st.caption(
            f"Decision reference: {decision_reference} · {item.source_type} source: "
            f"{item.source} · Published {item.published_at.strftime('%b %d · %H:%M UTC')}"
        )
        if source_url is not None:
            st.markdown(f"[Read original source]({source_url})")
        if index != len(items):
            st.divider()


def render_today_market_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = base.build_today_items(records)
    portfolio_impact = _briefing_value(
        briefing,
        "why_it_matters",
        _event_portfolio_fallback(items),
        limit=210,
    )
    action = _briefing_value(
        briefing,
        "portfolio_decision",
        "No portfolio change is authorized from these developments alone.",
        limit=150,
    )
    ui.page_header(
        "Investment world today",
        "The few daily developments that matter, explained through their investment and portfolio effect.",
        "NOW",
    )
    event_headline = _event_headline(items)
    investor_lesson = _daily_investor_lesson(items)
    watchlist = _event_watchlist(items)
    ui.investment_lens_card(
        title="Daily investment synopsis",
        what_changed=event_headline,
        why_investors_care=investor_lesson,
        portfolio_effect=portfolio_impact,
        cio_response=action,
        watch_next=watchlist,
        variant="today",
    )
    # Portfolio impact: visible in the synopsis. CIO action: visible in the synopsis.
    with st.expander("Explore today's investment context", expanded=False):
        _render_lens_context(
            what_changed=event_headline,
            why_investors_care=investor_lesson,
            portfolio_effect=portfolio_impact,
            cio_response=action,
            watch_next=watchlist,
        )
        st.divider()
        st.markdown("#### Developments and original sources")
        _render_event_detail(items, records, briefing)
        st.caption(f"Portfolio impact: {portfolio_impact} · CIO action: {action}")
    st.caption(
        base._daily_caption(snapshot)
        + " Educational context only; headlines cannot alter the CIO conclusion or authorize a paper trade."
    )


def render_environment_economic_brief(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = base.load_public_event_snapshot()
    records = tuple(item for item in snapshot.records if isinstance(item, Mapping))
    items = base.build_economic_event_items(records)
    dashboard = base.load_dashboard_data()
    economic_picture = _truncate(base.economic_snapshot_summary(dashboard.readings), 220)
    portfolio_fallback = _truncate(economic_portfolio_lens(dashboard.readings), 210)
    portfolio_impact = _briefing_value(
        briefing,
        "why_it_matters",
        portfolio_fallback,
        limit=210,
    )
    action = _briefing_value(
        briefing,
        "portfolio_decision",
        "The economic reading remains evidence for the CIO process, not a standalone trade signal.",
        limit=150,
    )
    readings = dashboard.readings
    ui.page_header(
        "Economy and investing",
        "Current economic data, why markets care, and how the evidence reaches the portfolio.",
        "ECON",
    )
    if readings is not None:
        ui.metric_grid(
            (
                ("Inflation", f"{readings.inflation_rate:.2f}%", "Purchasing power and margins"),
                ("Unemployment", f"{readings.unemployment_rate:.1f}%", "Growth and labor demand"),
                ("Federal funds", f"{readings.federal_funds_rate:.2f}%", "Financing and discount rate"),
                ("10Y − 2Y", f"{readings.yield_curve_spread:+.2f} pp", "Growth and policy expectations"),
            ),
            variant="environment",
        )
    economic_lesson = _economic_investor_lesson(readings)
    watchlist = _event_watchlist(items)
    ui.investment_lens_card(
        title="Economic synopsis",
        what_changed=_economic_headline(readings),
        why_investors_care=economic_lesson,
        portfolio_effect=portfolio_impact,
        cio_response=action,
        watch_next=watchlist,
        variant="environment",
    )
    # Portfolio impact: visible in the synopsis. CIO action: visible in the synopsis.
    with st.expander("Explore the economic investment context", expanded=False):
        _render_lens_context(
            what_changed=economic_picture,
            why_investors_care=economic_lesson,
            portfolio_effect=portfolio_impact,
            cio_response=action,
            watch_next=watchlist,
        )
        st.divider()
        st.markdown("#### How the economy reaches investments")
        for title, explanation in base.economic_investment_implications(dashboard.readings):
            st.markdown(f"**{title}**")
            st.write(explanation)
        if items:
            st.divider()
            st.markdown("#### Recent economic and policy developments")
            _render_event_detail(items, records, briefing)
        else:
            st.caption(snapshot.detail)
        st.caption(f"Portfolio impact: {portfolio_impact} · CIO action: {action}")
    st.caption(
        base._daily_caption(snapshot)
        + f" Economic readings: {dashboard.data_source}. Educational interpretation only; "
        "the governed CIO process separately determines whether portfolio action is justified."
    )


def render_today_opportunity_scan(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    snapshot = base.load_opportunity_scan()
    action = _briefing_value(
        briefing,
        "portfolio_decision",
        "Maintain the current portfolio until an opportunity clears the full process.",
        limit=130,
    )
    ui.page_header(
        "Opportunity scan",
        "The strongest alternative found, how far it progressed, and why capital did or did not move.",
        "SCAN",
    )
    ui.callout_card(
        "Opportunity synopsis",
        (
            f"Strongest alternative: {snapshot.strongest_alternative}. "
            f"{_truncate(snapshot.strongest_stage, 110)}."
        ),
        (
            f"Portfolio impact: {_truncate(snapshot.main_reason, 170)} · "
            f"CIO action: {action}"
        ),
    )
    with st.expander("View opportunity scan detail"):
        ui.metric_grid(
            (
                ("U.S. companies screened", base._count_label(snapshot.broad_assets_screened), "Broad eligible universe"),
                ("Market snapshots", base._count_label(snapshot.snapshot_covered), "Usable initial evidence"),
                ("Companies deepened", base._count_label(snapshot.companies_deepened), "Full company analysis"),
                ("Governed candidates", base._count_label(snapshot.governed_candidates), "Complete candidate evidence"),
                ("Reached CIO queue", base._count_label(snapshot.opportunities_reaching_cio), "Qualified opportunities"),
            ),
            variant="today",
        )
        st.write(f"**Main reason capital did not advance:** {snapshot.main_reason}")
        st.caption(
            f"Scan as of {ui.format_datetime(snapshot.as_of)} · production context "
            f"{snapshot.decision_reference} · CIO decision {_decision_reference(briefing)}. "
            f"{snapshot.detail}"
        )


def render_history_decision_accountability() -> None:
    snapshot = base.load_decision_accountability()
    ui.page_header(
        "Decision accountability",
        "What later outcomes suggest about the decision process without turning hindsight into trading authority.",
        "LEARN",
    )
    ui.callout_card(
        "Accountability synopsis",
        f"What the record is teaching: {_truncate(snapshot.lesson, 210)}",
        (
            "Portfolio impact: this evidence can prompt governed process review, but it cannot "
            "change current holdings or authorize execution."
        ),
    )
    with st.expander("View decision-accountability detail"):
        ui.metric_grid(
            (
                ("Awaiting evaluation", f"{snapshot.awaiting_evaluation:,}", "Decision horizon not matured"),
                ("Avoided losses", f"{snapshot.avoided_losses:,}", "Rejected and later lagged cash"),
                ("Missed opportunities", f"{snapshot.missed_opportunities:,}", "Rejected and later beat cash"),
                ("Supported gains", f"{snapshot.supported_gains:,}", "Qualified and later beat cash"),
                ("Supported losses", f"{snapshot.supported_losses:,}", "Qualified and later lagged cash"),
                ("Neutral", f"{snapshot.neutral_outcomes:,}", "No material edge versus cash"),
            ),
            variant="history",
        )
        st.caption(snapshot.detail)
        if snapshot.recent_outcomes:
            frame = pd.DataFrame(
                {
                    "Observed": ui.format_datetime(item.get("observed_at")),
                    "Symbol": item.get("symbol"),
                    "Original disposition": base._outcome_label(item.get("disposition")),
                    "Outcome": base._outcome_label(item.get("outcome")),
                    "Excess return vs cash": (
                        None
                        if base._safe_float(item.get("excess_return_vs_cash")) is None
                        else f"{float(item['excess_return_vs_cash']):.2%}"
                    ),
                }
                for item in snapshot.recent_outcomes
            )
            st.dataframe(frame, use_container_width=True, hide_index=True)


def _freshness_summary(entries: Sequence[object]) -> str:
    current = sum(getattr(item, "state", "") == "Current" for item in entries)
    waiting = sum(getattr(item, "state", "") == "Awaiting refresh" for item in entries)
    needs_attention = len(entries) - current - waiting
    parts = [f"{current} current"]
    if waiting:
        parts.append(f"{waiting} awaiting refresh")
    if needs_attention:
        parts.append(f"{needs_attention} need attention")
    return " · ".join(parts)


def render_information_freshness(
    *,
    briefing: Mapping[str, Any] | None,
    surface: str,
) -> None:
    now = datetime.now(timezone.utc)
    market = base.load_live_market_console()
    dashboard = base.load_dashboard_data()
    public_snapshot = base.load_public_event_snapshot()
    try:
        mandate = base.get_mandate_details(base.CANONICAL_PORTFOLIO_CODE)
    except (OSError, RuntimeError, TypeError, ValueError):
        mandate = None
    entries = base.build_freshness_entries(
        now=now,
        market=market,
        dashboard=dashboard,
        public_snapshot=public_snapshot,
        briefing=briefing,
        mandate=mandate,
    )
    st.caption(f"Information status · {_freshness_summary(entries)}")
    with st.expander("Information freshness details"):
        ui.metric_grid(
            tuple((item.label, item.state, item.detail) for item in entries),
            variant=surface,
        )
        st.caption(
            f"The CIO and canonical portfolio roll at {base._schedule_label()}; market, "
            "economic, and public-event sources retain their own timestamps."
        )


__all__ = [
    "render_environment_economic_brief",
    "render_history_decision_accountability",
    "render_information_freshness",
    "render_today_market_brief",
    "render_today_opportunity_scan",
]
