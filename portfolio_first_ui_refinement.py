"""Make Portfolio the primary application surface and lead with capital structure.

Presentation only. This module does not read new evidence, alter a CIO decision,
change portfolio construction, authorize execution, or create real-money authority.
"""

from __future__ import annotations

from functools import wraps
from html import escape
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

import streamlit as st


_INSTALLED_STATE_KEY = "_capital_intelligence_portfolio_first_ui_installed"
_NAVIGATION_KEY = "primary_surface_navigation_portfolio_first_v1"
_PRIMARY_SURFACES = ["Portfolio", "Today", "Environment", "History"]


_CSS = """
<style>
/* The CIO report is the second Portfolio element, directly after capital
   structure. Its icon and complete row are one accessible expansion target. */
div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) {
    margin: .48rem 0 .82rem !important;
    border: 1px solid rgba(var(--surface-rgb), .24) !important;
    border-radius: 1rem !important;
    background: linear-gradient(145deg, rgba(13, 20, 34, .94), rgba(8, 13, 24, .94)) !important;
    overflow: hidden !important;
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary {
    min-height: 4.45rem !important;
    padding: .7rem .82rem !important;
    display: grid !important;
    grid-template-columns: 2.7rem minmax(0, 1fr) auto !important;
    align-items: center !important;
    gap: .76rem !important;
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary::before {
    content: "✓";
    width: 2.5rem;
    height: 2.5rem;
    display: grid;
    place-items: center;
    border: 1px solid rgba(var(--surface-rgb), .32);
    border-radius: .78rem;
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .16), rgba(var(--surface-rgb-2), .08));
    color: var(--surface-accent);
    font-size: 1rem;
    font-weight: 820;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, .05), 0 0 22px rgba(var(--surface-rgb), .08);
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary p {
    margin: 0 !important;
    color: #eef5ff !important;
    font-size: .92rem !important;
    line-height: 1.35 !important;
    font-weight: 740 !important;
}

div[data-testid="stExpander"]:has(.portfolio-cio-report-marker)[open] {
    border-color: rgba(var(--surface-rgb), .34) !important;
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .075), rgba(8, 13, 24, .96)) !important;
}

.portfolio-cio-report-marker {
    display: none;
}

.portfolio-cio-report-meta {
    margin: .2rem 0 .72rem;
    color: #8292a8;
    font-size: .68rem;
    line-height: 1.45;
}

@media (max-width: 760px) {
    div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary {
        min-height: 4.2rem !important;
        grid-template-columns: 2.42rem minmax(0, 1fr) auto !important;
        gap: .6rem !important;
        padding: .62rem .68rem !important;
    }

    div[data-testid="stExpander"]:has(.portfolio-cio-report-marker) summary::before {
        width: 2.28rem;
        height: 2.28rem;
        border-radius: .7rem;
    }
}
</style>
"""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object, fallback: str) -> str:
    return _clean(value) or fallback


def _joined(value: object, fallback: str) -> str:
    if isinstance(value, str):
        return _clean(value) or fallback
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        cleaned = [_clean(item) for item in value if _clean(item)]
        return " • ".join(cleaned) if cleaned else fallback
    return fallback


def _status_title(value: object, fallback: str = "Unavailable") -> str:
    text = _clean(value)
    return text.replace("_", " ").title() if text else fallback


def _briefing_identifier(briefing: Mapping[str, Any] | None) -> str:
    if not isinstance(briefing, Mapping):
        return "Unavailable"
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = _clean(briefing.get(field_name))
        if value:
            return value
    return "Unavailable"


def _render_navigation(options: list[str]) -> tuple[str, bool]:
    requested = [str(option) for option in options]
    choices = [item for item in _PRIMARY_SURFACES if item in requested]
    choices.extend(item for item in requested if item not in choices)
    if not choices:
        raise ValueError("primary navigation requires at least one surface")

    brand, navigation = st.columns(
        (0.42, 5.58),
        gap="small",
        vertical_alignment="center",
    )
    with brand:
        st.markdown(
            '<div class="nav-brand-mark">'
            '<svg viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="m12 3 7 4v10l-7 4-7-4V7z"/>'
            '<path d="m8.5 9 3.5-2 3.5 2v6L12 17l-3.5-2z"/>'
            '</svg></div>',
            unsafe_allow_html=True,
        )
    with navigation:
        selected = st.segmented_control(
            "Primary screens",
            choices,
            selection_mode="single",
            default="Portfolio" if "Portfolio" in choices else choices[0],
            required=True,
            label_visibility="collapsed",
            width="stretch",
            key=_NAVIGATION_KEY,
        )
    return str(selected or choices[0]), True


def _capital_structure(
    app: ModuleType,
    *,
    mandate: Mapping[str, Any],
) -> tuple[float, float, float]:
    nav = float(mandate["nav"])
    cash = float(mandate["cash"])
    invested = max(nav - cash, 0.0)
    deployed = 0.0 if nav <= 0 else invested / nav

    app.page_header(
        "Capital structure",
        "The portfolio value, available cash, current deployment, and total result.",
        "01",
    )
    app.metric_grid(
        (
            ("Portfolio value", app.format_currency(nav), "Canonical NAV"),
            ("Available cash", app.format_currency(cash), "Optionality reserve"),
            ("Capital deployed", f"{deployed:.0%}", "Current exposure"),
            (
                "Total P&L",
                app.format_currency(mandate.get("total_pnl", 0.0)),
                app.format_percent(mandate["total_return"]),
            ),
        ),
        variant="portfolio",
    )
    app.allocation_bar(cash=cash, nav=nav)
    return nav, cash, deployed


def _render_cio_report(
    app: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    mandate: Mapping[str, Any],
    deployed: float,
) -> None:
    holdings = mandate.get("holdings", [])
    posture = "Fully in cash" if deployed <= 0.0000001 else f"{deployed:.0%} invested"
    holdings_summary = (
        "Cash only"
        if not holdings
        else f"{len(holdings)} governed position{'s' if len(holdings) != 1 else ''}"
    )
    decision = _plain(
        briefing.get("portfolio_decision") if isinstance(briefing, Mapping) else None,
        "No new portfolio action is currently authorized.",
    )
    positioning_reason = _plain(
        briefing.get("why_it_matters") if isinstance(briefing, Mapping) else None,
        (
            "Capital remains in its current position until a governed opportunity clears "
            "evidence, risk, cost, liquidity, and construction controls."
        ),
    )
    what_changed = _plain(
        briefing.get("what_changed") if isinstance(briefing, Mapping) else None,
        "No material change was recorded in the latest governed briefing.",
    )
    opportunity_or_risk = _plain(
        briefing.get("opportunity_or_risk") if isinstance(briefing, Mapping) else None,
        "No separate opportunity or risk vector was recorded.",
    )
    change_conditions = _joined(
        briefing.get("evidence_that_changes_conclusion", ())
        if isinstance(briefing, Mapping)
        else (),
        (
            "A stronger, liquid, risk-adjusted opportunity must clear the complete "
            "specialist, CIO, construction, and implementation process."
        ),
    )
    if construction is None:
        implementation_state = "No construction change queued"
        implementation_note = "Existing capital remains in its current state."
    else:
        trades = construction.get("trades", [])
        implementation_state = _status_title(construction.get("status"))
        implementation_note = (
            f"{len(trades)} proposed paper transaction"
            f"{'s' if len(trades) != 1 else ''}."
        )

    with st.expander("CIO report", expanded=False):
        st.markdown(
            '<span class="portfolio-cio-report-marker" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
        app.status_list(
            (
                ("Current posture", posture, holdings_summary),
                ("CIO decision", decision, "Only the CIO can authorize the portfolio action."),
                ("Why capital is positioned this way", positioning_reason, opportunity_or_risk),
                ("Implementation state", implementation_state, implementation_note),
                ("What changed", what_changed, "Latest governed evidence update."),
                ("What could change the decision", change_conditions, "Next governed review conditions."),
            ),
            variant="portfolio",
        )
        if isinstance(briefing, Mapping):
            confidence = briefing.get("confidence")
            confidence_label = (
                "Not scored"
                if confidence is None
                else f"{float(confidence):.0%} confidence"
            )
            candidate = _clean(briefing.get("candidate_identifier")) or "No qualified candidate"
            cycle = _clean(briefing.get("cycle_identifier")) or "Unavailable"
            st.markdown(
                '<div class="portfolio-cio-report-meta">'
                f'Decision {escape(_briefing_identifier(briefing))} · '
                f'Cycle {escape(cycle)} · Candidate {escape(candidate)} · '
                f'{escape(confidence_label)}</div>',
                unsafe_allow_html=True,
            )
        app.render_information_freshness(briefing=briefing, surface="portfolio")


def _is_capital_metric_grid(rows: object, kwargs: Mapping[str, object]) -> bool:
    if str(kwargs.get("variant", "")).lower() != "portfolio":
        return False
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return False
    labels = {
        str(row[0])
        for row in rows
        if isinstance(row, tuple) and len(row) >= 1
    }
    return {
        "Portfolio value",
        "Available cash",
        "Capital deployed",
        "Total P&L",
    }.issubset(labels)


def _render_remaining_portfolio(
    app: ModuleType,
    original: Callable[..., Any],
    dependencies: object,
    *,
    principal: object | None,
) -> None:
    saved = {
        "render_information_freshness": app.render_information_freshness,
        "page_header": app.page_header,
        "status_list": app.status_list,
        "metric_grid": app.metric_grid,
        "allocation_bar": app.allocation_bar,
        "callout_card": app.callout_card,
    }

    def page_header(title: object, *args: object, **kwargs: object) -> object:
        if str(title) in {"Portfolio posture", "Capital structure"}:
            return None
        return saved["page_header"](title, *args, **kwargs)

    def status_list(rows: object, *args: object, **kwargs: object) -> object:
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)):
            labels = {
                str(row[0])
                for row in rows
                if isinstance(row, tuple) and len(row) >= 1
            }
            if "Current posture" in labels and "Portfolio action" in labels:
                return None
        return saved["status_list"](rows, *args, **kwargs)

    def metric_grid(rows: object, *args: object, **kwargs: object) -> object:
        if _is_capital_metric_grid(rows, kwargs):
            return None
        return saved["metric_grid"](rows, *args, **kwargs)

    allocation_suppressed = False

    def allocation_bar(*args: object, **kwargs: object) -> object:
        nonlocal allocation_suppressed
        if not allocation_suppressed:
            allocation_suppressed = True
            return None
        return saved["allocation_bar"](*args, **kwargs)

    def callout_card(title: object, *args: object, **kwargs: object) -> object:
        if str(title) == "Recommended portfolio action":
            return None
        return saved["callout_card"](title, *args, **kwargs)

    app.render_information_freshness = lambda **_kwargs: None
    app.page_header = page_header
    app.status_list = status_list
    app.metric_grid = metric_grid
    app.allocation_bar = allocation_bar
    app.callout_card = callout_card
    try:
        original(dependencies, principal=principal)
    finally:
        for name, value in saved.items():
            setattr(app, name, value)


def install(app_impl: ModuleType) -> None:
    """Install Portfolio-first navigation and hierarchy once."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    original = getattr(app_impl._render_portfolio, "__wrapped__", app_impl._render_portfolio)

    @st.fragment(run_every="30s")
    @wraps(original)
    def render_portfolio(
        dependencies: object,
        *,
        principal: object | None,
    ) -> None:
        construction = app_impl._latest("portfolio_construction")
        briefing = app_impl._latest("daily_cio_briefing")
        mandate = dependencies.get_mandate_details(app_impl.CANONICAL_PORTFOLIO_CODE)
        if mandate is None:
            st.warning("The canonical paper portfolio is unavailable.")
            return

        st.markdown(_CSS, unsafe_allow_html=True)
        _nav, _cash, deployed = _capital_structure(app_impl, mandate=mandate)
        _render_cio_report(
            app_impl,
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )
        _render_remaining_portfolio(
            app_impl,
            original,
            dependencies,
            principal=principal,
        )

    app_impl.PRIMARY_SURFACES = list(_PRIMARY_SURFACES)
    app_impl.render_navigation = _render_navigation
    app_impl._render_portfolio = render_portfolio
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = ["install"]
