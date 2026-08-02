"""Lead the Portfolio CIO report with market context and active monitoring.

Presentation only. This module reads existing governed environment, market, and
briefing records. It does not create evidence, alter a CIO decision, change
portfolio construction, authorize execution, or create real-money authority.
"""

from __future__ import annotations

from html import escape
from types import ModuleType
from typing import Any, Mapping, Sequence

import streamlit as st


_INSTALLED_STATE_KEY = "_capital_intelligence_cio_report_backdrop_installed"


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _plain(value: object, fallback: str) -> str:
    return _clean(value) or fallback


def _values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        cleaned = _clean(value)
        return (cleaned,) if cleaned else ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_clean(item) for item in value if _clean(item))
    return ()


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold().strip(" .,;:–—-")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


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


def _environment_record(app: ModuleType) -> Mapping[str, Any]:
    loader = getattr(app, "_diagnostic_environment", None)
    if not callable(loader):
        return {}
    try:
        payload = loader()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    environment = payload.get("environment")
    return environment if isinstance(environment, Mapping) else {}


def _live_market_record(app: ModuleType) -> Mapping[str, Any]:
    loader = getattr(app, "load_live_market_console", None)
    if not callable(loader):
        return {}
    try:
        value = loader()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _market_session(record: Mapping[str, Any]) -> str:
    state = record.get("market_open")
    return "U.S. session open" if state is True else "U.S. session closed" if state is False else "U.S. session unavailable"


def _market_coverage(record: Mapping[str, Any]) -> str:
    try:
        usable = int(record.get("quote_count", 0) or 0)
        expected = int(record.get("expected_quote_count", 0) or 0)
    except (TypeError, ValueError):
        return "implementation coverage unavailable"
    if expected <= 0:
        return "implementation coverage unavailable"
    return f"implementation coverage {usable}/{expected}"


def _current_market_backdrop(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> str:
    environment = _environment_record(app)
    live_market = _live_market_record(app)

    context: list[str] = []
    if live_market:
        context.append(f"{_market_session(live_market)}; {_market_coverage(live_market)}.")

    headline = _clean(environment.get("headline"))
    summary = _clean(environment.get("summary"))
    regime = _clean(environment.get("regime"))
    if headline:
        context.append(headline.rstrip(".") + ".")
    if summary and summary.casefold() != headline.casefold():
        context.append(summary.rstrip(".") + ".")
    if regime and regime.casefold() not in {"unavailable", "not separately classified"}:
        context.append(f"Current governed regime: {regime}.")

    if not context and isinstance(briefing, Mapping):
        for field_name in (
            "market_backdrop",
            "current_backdrop",
            "environment_summary",
            "market_environment",
            "opportunity_or_risk",
        ):
            value = _clean(briefing.get(field_name))
            if value:
                context.append(value)
                break

    if not context and live_market:
        detail = _clean(live_market.get("detail"))
        if detail:
            context.append(detail)

    return " ".join(context) or (
        "The current governed market backdrop is unavailable. The CIO remains "
        "fail-closed until market and environment records are current."
    )


def _monitoring_summary(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> str:
    environment = _environment_record(app)
    monitored: list[str] = []

    if isinstance(briefing, Mapping):
        for field_name in (
            "what_is_being_monitored",
            "what_to_watch",
            "monitoring",
            "watchlist",
            "evidence_that_changes_conclusion",
        ):
            monitored.extend(_values(briefing.get(field_name)))

    monitored.extend(_values(environment.get("review_conditions")))
    monitored = list(_unique(monitored))
    if monitored:
        return " • ".join(monitored)
    return (
        "The CIO is monitoring growth, inflation, policy, liquidity, earnings, "
        "cross-asset confirmation, downside risk, and whether a superior liquid "
        "opportunity clears every decision threshold."
    )


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
    backdrop = _current_market_backdrop(app, briefing)
    monitoring = _monitoring_summary(app, briefing)
    opportunity_or_risk = _plain(
        briefing.get("opportunity_or_risk") if isinstance(briefing, Mapping) else None,
        "No separate opportunity or risk vector was recorded.",
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
                (
                    "Current market backdrop",
                    backdrop,
                    "Today’s governed market, economic, and implementation-data setting.",
                ),
                ("What changed", what_changed, "Latest governed evidence update."),
                (
                    "What the CIO is monitoring",
                    monitoring,
                    "Conditions that could change the market assessment or portfolio decision.",
                ),
                ("Current portfolio posture", posture, holdings_summary),
                ("CIO decision", decision, "Only the CIO can authorize the portfolio action."),
                ("Why capital is positioned this way", positioning_reason, opportunity_or_risk),
                ("Implementation state", implementation_state, implementation_note),
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


def install(portfolio_first: ModuleType) -> None:
    """Install the market-first CIO report ordering once."""

    if getattr(portfolio_first, _INSTALLED_STATE_KEY, False):
        return
    portfolio_first._render_cio_report = _render_cio_report
    setattr(portfolio_first, _INSTALLED_STATE_KEY, True)


__all__ = [
    "install",
    "_current_market_backdrop",
    "_monitoring_summary",
]
