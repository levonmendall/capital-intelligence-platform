"""Lead the Portfolio CIO report with current market context and monitoring.

Presentation only. Existing governed records are rearranged and summarized; no
evidence, decision, construction, execution, or authority is changed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence


_INSTALLED_STATE_KEY = "_capital_intelligence_cio_report_backdrop_installed"


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


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


def _sentence(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    return text if text[-1:] in {".", "!", "?"} else text + "."


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _format_timestamp(value: object) -> str:
    text = _clean(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    return parsed.astimezone(timezone.utc).strftime("%b %d, %Y %H:%M UTC")


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
        record = loader()
    except (OSError, RuntimeError, TypeError, ValueError):
        return {}
    return record if isinstance(record, Mapping) else {}


def _economic_dashboard(app: ModuleType) -> object | None:
    loader = getattr(app, "load_dashboard_data", None)
    if not callable(loader):
        return None
    try:
        return loader()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _economic_readings(dashboard: object | None) -> object | None:
    if isinstance(dashboard, Mapping):
        return dashboard.get("readings")
    return getattr(dashboard, "readings", None)


def _reading(readings: object | None, field_name: str) -> float | None:
    if readings is None:
        return None
    if isinstance(readings, Mapping):
        return _number(readings.get(field_name))
    return _number(getattr(readings, field_name, None))


def _economic_summary(app: ModuleType) -> str:
    dashboard = _economic_dashboard(app)
    readings = _economic_readings(dashboard)
    inflation = _reading(readings, "inflation_rate")
    unemployment = _reading(readings, "unemployment_rate")
    policy_rate = _reading(readings, "federal_funds_rate")
    curve = _reading(readings, "yield_curve_spread")
    values: list[str] = []
    if inflation is not None:
        values.append(f"inflation {inflation:.2f}%")
    if unemployment is not None:
        values.append(f"unemployment {unemployment:.1f}%")
    if policy_rate is not None:
        values.append(f"the federal funds rate {policy_rate:.2f}%")
    if curve is not None:
        curve_shape = "upward sloping" if curve > 0 else "inverted" if curve < 0 else "flat"
        values.append(f"the 10-year minus 2-year curve {curve:+.2f} percentage points ({curve_shape})")
    if not values:
        return ""
    return "Economic backdrop: " + ", ".join(values) + "."


def _market_status_summary(market: Mapping[str, Any]) -> str:
    if not market:
        return ""
    state = market.get("market_open")
    session = (
        "The U.S. session is open"
        if state is True
        else "The U.S. session is closed"
        if state is False
        else "The U.S. session state is unavailable"
    )
    try:
        usable = int(market.get("quote_count", 0) or 0)
        expected = int(market.get("expected_quote_count", 0) or 0)
    except (TypeError, ValueError):
        usable = expected = 0
    coverage = (
        f"{usable} of {expected} governed implementation instruments have usable live quotes"
        if expected > 0
        else "live implementation-quote coverage is unavailable"
    )
    observed_at = _format_timestamp(
        market.get("latest_quote_at") or market.get("evaluated_at")
    )
    timing = f" as of {observed_at}" if observed_at else ""
    summary = f"{session}, and {coverage}{timing}."
    status = _clean(market.get("status")).lower()
    detail = _clean(market.get("detail"))
    if status not in {"connected", ""} and detail:
        summary += " Data-status note: " + _sentence(detail)
    return summary


def _briefing_developments(
    briefing: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if not isinstance(briefing, Mapping):
        return ()
    values: list[str] = []
    values.extend(_values(briefing.get("material_developments")))
    values.extend(_values(briefing.get("what_changed")))
    values.extend(_values(briefing.get("opportunity_or_risk")))
    filtered = tuple(
        item
        for item in _unique(values)
        if not item.casefold().startswith("cio action is ")
    )
    return filtered[:4]


def _portfolio_implication(
    environment: Mapping[str, Any],
    briefing: Mapping[str, Any] | None,
) -> str:
    values: list[object] = [environment.get("portfolio_impact")]
    if isinstance(briefing, Mapping):
        values.extend(
            (
                briefing.get("why_it_matters"),
                briefing.get("portfolio_effect"),
            )
        )
    return next((_clean(value) for value in values if _clean(value)), "")


def _watch_items(
    environment: Mapping[str, Any],
    briefing: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    values: list[str] = list(_values(environment.get("review_conditions")))
    if isinstance(briefing, Mapping):
        for field_name in (
            "what_is_being_monitored",
            "what_to_watch",
            "evidence_that_changes_conclusion",
        ):
            values.extend(_values(briefing.get(field_name)))
    return _unique(values)[:4]


def _current_market_backdrop(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> str:
    """Return an investor-readable discussion of the latest governed market state."""

    environment = _environment_record(app)
    market = _live_market_record(app)
    sections: list[str] = ["What's happening in markets now (latest governed snapshot):"]

    market_status = _market_status_summary(market)
    if market_status:
        sections.append(market_status)

    headline = _clean(environment.get("headline"))
    summary = _clean(environment.get("summary"))
    regime = _clean(environment.get("regime"))
    if headline:
        sections.append("Market setting: " + _sentence(headline))
    if summary and summary.casefold() != headline.casefold():
        sections.append(_sentence(summary))
    if regime and regime.casefold() not in {"unavailable", "not separately classified"}:
        sections.append(f"Governed regime: {regime}.")

    economic = _economic_summary(app)
    if economic:
        sections.append(economic)

    developments = _briefing_developments(briefing)
    if developments:
        sections.append(
            "Developments reflected in the CIO briefing: "
            + " • ".join(developments)
            + "."
        )

    implication = _portfolio_implication(environment, briefing)
    if implication:
        sections.append("Portfolio relevance: " + _sentence(implication))

    watch = _watch_items(environment, briefing)
    if watch:
        sections.append("What to watch next: " + " • ".join(watch) + ".")

    meaningful = len(sections) > 1
    if meaningful:
        return " ".join(sections)

    if isinstance(briefing, Mapping):
        for field in (
            "market_backdrop",
            "current_backdrop",
            "environment_summary",
            "market_environment",
            "opportunity_or_risk",
        ):
            value = _clean(briefing.get(field))
            if value:
                return sections[0] + " " + _sentence(value)

    return (
        "The current governed market backdrop is unavailable. The CIO remains "
        "fail-closed until market and environment records are current."
    )


def _monitoring_summary(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
    existing_change_conditions: object = None,
) -> str:
    monitored: list[str] = []
    if isinstance(briefing, Mapping):
        for field in (
            "what_is_being_monitored",
            "what_to_watch",
            "monitoring",
            "watchlist",
            "evidence_that_changes_conclusion",
        ):
            monitored.extend(_values(briefing.get(field)))
    monitored.extend(_values(_environment_record(app).get("review_conditions")))
    monitored.extend(_values(existing_change_conditions))
    unique = _unique(monitored)
    if unique:
        return " • ".join(unique)
    return (
        "The CIO is monitoring growth, inflation, policy, liquidity, earnings, "
        "cross-asset confirmation, downside risk, and whether a superior liquid "
        "opportunity clears every decision threshold."
    )


def _row_map(rows: Sequence[object]) -> dict[str, tuple[object, object, object]]:
    result: dict[str, tuple[object, object, object]] = {}
    for row in rows:
        if isinstance(row, tuple) and len(row) == 3:
            result[str(row[0])] = row
    return result


def install(portfolio_first: ModuleType) -> None:
    """Install the market-first CIO-report ordering once."""

    if getattr(portfolio_first, _INSTALLED_STATE_KEY, False):
        return

    original: Callable[..., Any] = portfolio_first._render_cio_report

    @wraps(original)
    def render_cio_report(
        app: ModuleType,
        *,
        briefing: Mapping[str, Any] | None,
        construction: Mapping[str, Any] | None,
        mandate: Mapping[str, Any],
        deployed: float,
    ) -> None:
        original_status_list = app.status_list

        def status_list(
            rows: Sequence[object],
            *args: object,
            **kwargs: object,
        ) -> object:
            mapped = _row_map(rows)
            if "Current posture" not in mapped or "CIO decision" not in mapped:
                return original_status_list(rows, *args, **kwargs)

            changed = mapped.get(
                "What changed",
                (
                    "What changed",
                    "No material change was recorded in the latest governed briefing.",
                    "Latest governed evidence update.",
                ),
            )
            change_conditions = mapped.get("What could change the decision", (None, None, None))[1]
            posture = mapped["Current posture"]
            reordered = (
                (
                    "Current market backdrop",
                    _current_market_backdrop(app, briefing),
                    "The latest governed market, economic, development, and implementation-data setting.",
                ),
                changed,
                (
                    "What the CIO is monitoring",
                    _monitoring_summary(app, briefing, change_conditions),
                    "Conditions that could change the assessment or portfolio decision.",
                ),
                ("Current portfolio posture", posture[1], posture[2]),
                mapped["CIO decision"],
                mapped.get("Why capital is positioned this way"),
                mapped.get("Implementation state"),
            )
            filtered = tuple(row for row in reordered if isinstance(row, tuple))
            return original_status_list(filtered, *args, **kwargs)

        app.status_list = status_list
        try:
            original(
                app,
                briefing=briefing,
                construction=construction,
                mandate=mandate,
                deployed=deployed,
            )
        finally:
            app.status_list = original_status_list

    portfolio_first._render_cio_report = render_cio_report
    setattr(portfolio_first, _INSTALLED_STATE_KEY, True)


__all__ = ["install", "_current_market_backdrop", "_monitoring_summary"]
