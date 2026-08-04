"""Move the complete CIO report off the primary Portfolio surface.

The Portfolio page keeps a compact, accessible link containing only the current
CIO conclusion. The link opens a dedicated query-parameter view with the full
governed report, monitoring conditions, implementation state, freshness, and
lineage. Presentation only: this module cannot alter evidence, decisions,
construction, execution, portfolio state, or real-money authority.
"""

from __future__ import annotations

import re
from functools import wraps
from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

import cio_report_backdrop_refinement as backdrop
import current_cio_report_trigger_refinement as trigger


_INSTALLED_STATE_KEY = "_capital_intelligence_cio_report_detail_installed"
_VIEW_QUERY_KEY = "view"
_VIEW_QUERY_VALUE = "cio-report"

_CSS = """
<style>
.cio-report-link-card {
    display: grid;
    grid-template-columns: 2.65rem minmax(0, 1fr) auto;
    align-items: center;
    gap: .78rem;
    margin: .5rem 0 .9rem;
    padding: .78rem .86rem;
    border: 1px solid rgba(var(--surface-rgb), .25);
    border-radius: 1rem;
    background: linear-gradient(145deg, rgba(13, 20, 34, .94), rgba(8, 13, 24, .94));
    color: inherit !important;
    text-decoration: none !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,.04), 0 14px 34px rgba(0,0,0,.18);
    transition: border-color 150ms ease, transform 150ms ease, background 150ms ease;
}
.cio-report-link-card:hover,
.cio-report-link-card:focus-visible {
    border-color: rgba(var(--surface-rgb), .45);
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .09), rgba(8, 13, 24, .96));
    transform: translateY(-1px);
    outline: none;
}
.cio-report-link-icon {
    width: 2.55rem;
    height: 2.55rem;
    display: grid;
    place-items: center;
    border: 1px solid rgba(var(--surface-rgb), .34);
    border-radius: .78rem;
    background: linear-gradient(145deg, rgba(var(--surface-rgb), .17), rgba(var(--surface-rgb-2), .08));
    color: var(--surface-accent);
    font-size: 1rem;
    font-weight: 850;
}
.cio-report-link-copy { min-width: 0; }
.cio-report-link-kicker {
    color: var(--surface-accent);
    font-size: .64rem;
    font-weight: 820;
    letter-spacing: .09em;
    text-transform: uppercase;
}
.cio-report-link-title {
    margin-top: .22rem;
    color: #f3f7fd;
    font-size: .94rem;
    line-height: 1.35;
    font-weight: 760;
}
.cio-report-link-meta {
    margin-top: .24rem;
    color: #8190a6;
    font-size: .67rem;
    line-height: 1.35;
}
.cio-report-link-arrow {
    color: var(--surface-accent);
    font-size: 1.22rem;
    font-weight: 760;
}
.cio-report-back-link {
    display: inline-flex;
    align-items: center;
    gap: .38rem;
    margin: .3rem 0 .35rem;
    color: var(--surface-accent) !important;
    font-size: .72rem;
    font-weight: 760;
    text-decoration: none !important;
}
.cio-report-back-link:hover,
.cio-report-back-link:focus-visible { text-decoration: underline !important; }
.cio-monitoring-list {
    display: grid;
    gap: .42rem;
    margin: .2rem 0 .95rem;
}
.cio-monitoring-item {
    display: grid;
    grid-template-columns: 1.8rem minmax(0, 1fr);
    gap: .62rem;
    align-items: start;
    padding: .66rem .72rem;
    border: 1px solid rgba(138,157,188,.16);
    border-radius: .82rem;
    background: rgba(255,255,255,.018);
    color: #b9c5d6;
    font-size: .76rem;
    line-height: 1.5;
}
.cio-monitoring-seq {
    color: var(--surface-accent);
    font-size: .64rem;
    font-weight: 820;
    letter-spacing: .06em;
}
@media (max-width: 760px) {
    .cio-report-link-card {
        grid-template-columns: 2.42rem minmax(0, 1fr) auto;
        gap: .62rem;
        padding: .68rem .72rem;
    }
    .cio-report-link-icon { width: 2.3rem; height: 2.3rem; }
    .cio-report-link-title { font-size: .86rem; }
    .cio-report-link-meta { font-size: .63rem; }
    .cio-monitoring-item { font-size: .72rem; }
}
</style>
"""


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object, fallback: str) -> str:
    return _clean(value) or fallback


def _status_title(value: object, fallback: str = "Unavailable") -> str:
    text = _clean(value)
    return text.replace("_", " ").title() if text else fallback


def _query_value(streamlit_module: ModuleType, key: str) -> str:
    params = getattr(streamlit_module, "query_params", {})
    try:
        value = params.get(key, "")
    except (AttributeError, TypeError, ValueError):
        return ""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        value = value[0] if value else ""
    return _clean(value)


def report_requested(streamlit_module: ModuleType) -> bool:
    return _query_value(streamlit_module, _VIEW_QUERY_KEY) == _VIEW_QUERY_VALUE


def _decision_identifier(briefing: Mapping[str, Any] | None) -> str:
    if not isinstance(briefing, Mapping):
        return "Unavailable"
    for field_name in ("decision_identifier", "identifier", "cycle_identifier"):
        value = _clean(briefing.get(field_name))
        if value:
            return value
    return "Unavailable"


def _posture(mandate: Mapping[str, Any], deployed: float) -> tuple[str, str]:
    holdings = mandate.get("holdings", [])
    posture = "Fully in cash" if deployed <= 0.0000001 else f"{deployed:.0%} invested"
    holding_count = len(holdings) if isinstance(holdings, Sequence) else 0
    detail = (
        "Cash only"
        if holding_count == 0
        else f"{holding_count} governed position{'s' if holding_count != 1 else ''}"
    )
    return posture, detail


def _implementation(construction: Mapping[str, Any] | None) -> tuple[str, str, int]:
    if not isinstance(construction, Mapping):
        return "No construction change queued", "Existing capital remains unchanged.", 0
    transactions = construction.get("trades", [])
    count = len(transactions) if isinstance(transactions, Sequence) else 0
    state = _status_title(construction.get("status"))
    detail = f"{count} proposed paper transaction{'s' if count != 1 else ''}."
    return state, detail, count


def _confidence(briefing: Mapping[str, Any] | None) -> str:
    value = briefing.get("confidence") if isinstance(briefing, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Not scored"
    return f"{float(value):.0%}"


def _condition_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(
            _clean(item)
            for item in re.split(r"\s*[•\n]+\s*", value)
            if _clean(item)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[str] = []
        for item in value:
            result.extend(_condition_values(item))
        return tuple(result)
    return ()


def _monitoring_conditions(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if isinstance(briefing, Mapping):
        for field_name in (
            "what_is_being_monitored",
            "what_to_watch",
            "monitoring",
            "watchlist",
            "evidence_that_changes_conclusion",
        ):
            values.extend(_condition_values(briefing.get(field_name)))
    environment = backdrop._environment_record(app)
    values.extend(_condition_values(environment.get("review_conditions")))

    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold().strip(" .,;:–—-")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return tuple(unique) or (
        "A superior liquid opportunity clears every decision threshold.",
        "Growth, inflation, policy, liquidity, earnings, or cross-asset evidence changes materially.",
        "Evidence quality, freshness, downside risk, or implementation feasibility deteriorates.",
    )


def _render_link(
    streamlit_module: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    mandate: Mapping[str, Any],
    deployed: float,
) -> None:
    decision = trigger._current_report_title(briefing)
    posture, _posture_detail = _posture(mandate, deployed)
    implementation_state, _implementation_detail, _count = _implementation(construction)
    streamlit_module.markdown(
        (
            '<a class="cio-report-link-card" href="?view=cio-report" target="_self" '
            'aria-label="View full CIO report">'
            '<span class="cio-report-link-icon" aria-hidden="true">✓</span>'
            '<span class="cio-report-link-copy">'
            '<span class="cio-report-link-kicker">Current CIO report</span>'
            f'<span class="cio-report-link-title">{escape(decision)}</span>'
            f'<span class="cio-report-link-meta">{escape(posture)} · '
            f'{escape(implementation_state)} · Open complete decision record</span>'
            '</span><span class="cio-report-link-arrow" aria-hidden="true">→</span></a>'
        ),
        unsafe_allow_html=True,
    )


def _render_monitoring(streamlit_module: ModuleType, conditions: Sequence[str]) -> None:
    rows = "".join(
        '<div class="cio-monitoring-item">'
        f'<span class="cio-monitoring-seq">{index:02d}</span>'
        f'<span>{escape(condition)}</span></div>'
        for index, condition in enumerate(conditions, start=1)
    )
    streamlit_module.markdown(
        f'<div class="cio-monitoring-list">{rows}</div>',
        unsafe_allow_html=True,
    )


def _render_full_report(
    app: ModuleType,
    streamlit_module: ModuleType,
    *,
    briefing: Mapping[str, Any] | None,
    construction: Mapping[str, Any] | None,
    mandate: Mapping[str, Any],
    deployed: float,
) -> None:
    posture, posture_detail = _posture(mandate, deployed)
    implementation_state, implementation_detail, transaction_count = _implementation(construction)
    decision = _plain(
        briefing.get("portfolio_decision") if isinstance(briefing, Mapping) else None,
        "No new portfolio action is currently authorized.",
    )
    what_changed = _plain(
        briefing.get("what_changed") if isinstance(briefing, Mapping) else None,
        "No material change was recorded in the latest governed briefing.",
    )
    opportunity_or_risk = _plain(
        briefing.get("opportunity_or_risk") if isinstance(briefing, Mapping) else None,
        "No separate opportunity or risk vector was recorded.",
    )
    positioning_reason = _plain(
        briefing.get("why_it_matters") if isinstance(briefing, Mapping) else None,
        (
            "Capital remains in its current position until a governed opportunity "
            "clears evidence, risk, cost, liquidity, and construction controls."
        ),
    )
    market_backdrop = backdrop._current_market_backdrop(app, briefing)
    conditions = _monitoring_conditions(app, briefing)
    candidate = (
        _clean(briefing.get("candidate_identifier"))
        if isinstance(briefing, Mapping)
        else ""
    ) or "No qualified candidate"
    cycle = (
        _clean(briefing.get("cycle_identifier"))
        if isinstance(briefing, Mapping)
        else ""
    ) or "Unavailable"

    streamlit_module.markdown(
        '<a class="cio-report-back-link" href="?" target="_self">← Back to Portfolio</a>',
        unsafe_allow_html=True,
    )
    app.page_header(
        "Full CIO report",
        "The complete governed decision, evidence context, monitoring conditions, implementation state, and audit lineage.",
        "CIO",
    )
    app.callout_card(
        "CIO decision",
        decision,
        "Only the CIO can authorize a portfolio action; this report does not create execution authority.",
    )
    app.metric_grid(
        (
            ("Portfolio posture", posture, posture_detail),
            ("Decision confidence", _confidence(briefing), "Governed assessment"),
            ("Implementation state", implementation_state, implementation_detail),
            ("Paper transactions", transaction_count, "Proposed, not live-money execution"),
        ),
        variant="portfolio",
    )

    app.page_header(
        "Decision context",
        "The backdrop, evidence change, and portfolio rationale behind the current conclusion.",
        "01",
    )
    app.status_list(
        (
            (
                "Current market backdrop",
                market_backdrop,
                "Current governed market, economic, and implementation-data setting.",
            ),
            ("What changed", what_changed, "Latest governed evidence update."),
            (
                "Why capital is positioned this way",
                positioning_reason,
                opportunity_or_risk,
            ),
        ),
        variant="portfolio",
    )

    app.page_header(
        "Monitoring and reversal conditions",
        "Distinct evidence that could confirm, weaken, or change the current CIO conclusion.",
        "02",
    )
    _render_monitoring(streamlit_module, conditions)

    app.page_header(
        "Decision lineage",
        "Identifiers and source-health references needed to audit the current report.",
        "03",
    )
    app.status_list(
        (
            ("Decision", _decision_identifier(briefing), "Canonical decision reference"),
            ("Cycle", cycle, "Governed evaluation cycle"),
            ("Candidate", candidate, "Current decision candidate"),
            (
                "Construction",
                _clean(construction.get("identifier"))
                if isinstance(construction, Mapping)
                else "Not required",
                "Paper construction reference",
            ),
        ),
        variant="portfolio",
    )
    app.render_information_freshness(briefing=briefing, surface="portfolio")
    streamlit_module.caption(
        "This dedicated report is a read-only presentation of existing governed records. "
        "It cannot change the CIO conclusion, portfolio construction, or paper execution."
    )


def install(portfolio_first: ModuleType) -> None:
    """Install the compact Portfolio link and dedicated full-report route."""

    if getattr(portfolio_first, _INSTALLED_STATE_KEY, False):
        return

    original_capital = portfolio_first._capital_structure
    original_report = portfolio_first._render_cio_report

    @wraps(original_capital)
    def capital_structure(
        app: ModuleType,
        *,
        mandate: Mapping[str, Any],
    ) -> tuple[float, float, float]:
        if not report_requested(portfolio_first.st):
            return original_capital(app, mandate=mandate)
        nav = float(mandate["nav"])
        cash = float(mandate["cash"])
        invested = max(nav - cash, 0.0)
        deployed = 0.0 if nav <= 0 else invested / nav
        return nav, cash, deployed

    @wraps(original_report)
    def render_cio_report(
        app: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
        mandate: Mapping[str, Any],
        deployed: float,
    ) -> None:
        streamlit_module = portfolio_first.st
        streamlit_module.markdown(_CSS, unsafe_allow_html=True)
        if report_requested(streamlit_module):
            _render_full_report(
                app,
                streamlit_module,
                briefing=briefing,
                construction=construction,
                mandate=mandate,
                deployed=deployed,
            )
            streamlit_module.stop()
            return
        _render_link(
            streamlit_module,
            briefing=briefing,
            construction=construction,
            mandate=mandate,
            deployed=deployed,
        )

    portfolio_first._capital_structure = capital_structure
    portfolio_first._render_cio_report = render_cio_report
    setattr(portfolio_first, _INSTALLED_STATE_KEY, True)


__all__ = ["install", "report_requested"]
