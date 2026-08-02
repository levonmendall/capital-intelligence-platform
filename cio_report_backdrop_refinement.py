"""Lead the Portfolio CIO report with market context and active monitoring.

Presentation only. Existing governed records are rearranged and summarized; no
evidence, decision, construction, execution, or authority is changed.
"""

from __future__ import annotations

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


def _current_market_backdrop(
    app: ModuleType,
    briefing: Mapping[str, Any] | None,
) -> str:
    environment = _environment_record(app)
    market = _live_market_record(app)
    parts: list[str] = []

    if market:
        state = market.get("market_open")
        session = (
            "U.S. session open"
            if state is True
            else "U.S. session closed"
            if state is False
            else "U.S. session unavailable"
        )
        try:
            usable = int(market.get("quote_count", 0) or 0)
            expected = int(market.get("expected_quote_count", 0) or 0)
        except (TypeError, ValueError):
            usable = expected = 0
        coverage = (
            f"implementation coverage {usable}/{expected}"
            if expected > 0
            else "implementation coverage unavailable"
        )
        parts.append(f"{session}; {coverage}.")

    headline = _clean(environment.get("headline"))
    summary = _clean(environment.get("summary"))
    regime = _clean(environment.get("regime"))
    if headline:
        parts.append(headline.rstrip(".") + ".")
    if summary and summary.casefold() != headline.casefold():
        parts.append(summary.rstrip(".") + ".")
    if regime and regime.casefold() not in {"unavailable", "not separately classified"}:
        parts.append(f"Current governed regime: {regime}.")

    if not parts and isinstance(briefing, Mapping):
        for field in (
            "market_backdrop",
            "current_backdrop",
            "environment_summary",
            "market_environment",
            "opportunity_or_risk",
        ):
            value = _clean(briefing.get(field))
            if value:
                parts.append(value)
                break

    return " ".join(parts) or (
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
                    "Today’s governed market, economic, and implementation-data setting.",
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
