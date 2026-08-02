"""Present the governed opportunity funnel without a misleading quote denominator.

This adapter changes investor-facing labels and layout only. It reads the existing
current-cycle opportunity snapshot and live implementation-data status; it does not
create observations, qualify candidates, alter CIO authority, size positions, or
execute trades.
"""

from __future__ import annotations

from functools import wraps
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

import streamlit as st

import cio_report_backdrop_refinement
import concise_operating_intelligence_ui as concise
import live_operating_console
import portfolio_first_ui_refinement


_INSTALLED_STATE_KEY = "_capital_intelligence_opportunity_funnel_ui_installed"
_LOADER_MARKER = "_capital_intelligence_quote_denominator_removed"


def _count_label(value: int | None) -> str:
    return "Unavailable" if value is None else f"{value:,}"


def _implementation_market_state(snapshot: Mapping[str, object]) -> str:
    status = str(snapshot.get("status") or "").strip().lower()
    if status == "connected":
        return "Complete"
    if status == "partial":
        return "Partial"
    return "Unavailable"


def _missing_implementation_count(snapshot: Mapping[str, object]) -> int | None:
    try:
        expected = int(snapshot.get("expected_quote_count", 0) or 0)
        usable = int(snapshot.get("quote_count", 0) or 0)
    except (TypeError, ValueError):
        return None
    if expected <= 0:
        return None
    return max(expected - usable, 0)


def _partial_market_detail(snapshot: Mapping[str, object]) -> str:
    missing = _missing_implementation_count(snapshot)
    if missing is None:
        return (
            "Some approved implementation instruments currently lack usable "
            "top-of-book evidence."
        )
    noun = "instrument" if missing == 1 else "instruments"
    return (
        f"{missing:,} approved implementation {noun} currently lack usable "
        "top-of-book evidence."
    )


def _sanitize_market_snapshot(snapshot: object) -> object:
    if not isinstance(snapshot, Mapping):
        return snapshot
    sanitized = dict(snapshot)
    if str(sanitized.get("status") or "").strip().lower() == "partial":
        sanitized["detail"] = _partial_market_detail(sanitized)
    return sanitized


def _sanitized_loader(loader: Callable[..., object]) -> Callable[..., object]:
    if getattr(loader, _LOADER_MARKER, False):
        return loader

    @wraps(loader)
    def wrapped(*args: object, **kwargs: object) -> object:
        return _sanitize_market_snapshot(loader(*args, **kwargs))

    setattr(wrapped, _LOADER_MARKER, True)
    return wrapped


def _refined_status_rows(rows: Sequence[object]) -> tuple[object, ...]:
    refined: list[object] = []
    for row in rows:
        if not isinstance(row, tuple) or len(row) != 3 or row[0] != "Market status":
            refined.append(row)
            continue
        current_value = str(row[1] or "")
        session = current_value.split("·", 1)[0].strip() or "Unavailable"
        lowered = current_value.lower()
        state = (
            "complete"
            if "complete" in lowered
            else "partial"
            if "partial" in lowered
            else "unavailable"
        )
        refined.append(
            (
                "Market status",
                f"{session} · implementation market data {state}",
                (
                    "Provider-backed session state. Broader assets observed and "
                    "considered are reported in the current-cycle opportunity funnel."
                ),
            )
        )
    return tuple(refined)


def render_today_opportunity_scan(
    *,
    briefing: Mapping[str, Any] | None = None,
) -> None:
    """Show the three current-cycle counts requested by the investor-facing UI."""

    snapshot = concise.base.load_opportunity_scan()
    action = concise._briefing_value(
        briefing,
        "portfolio_decision",
        "Maintain the current portfolio until an opportunity clears the full process.",
        limit=130,
    )
    concise.ui.page_header(
        "Opportunity scan",
        (
            "How broadly the system searched, how many investable candidates were "
            "formed, and how many became eligible for governed decision review."
        ),
        "SCAN",
    )
    concise.ui.metric_grid(
        (
            (
                "Assets observed",
                _count_label(snapshot.broad_assets_screened),
                "Current governed scan",
            ),
            (
                "Investment candidates considered",
                _count_label(snapshot.governed_candidates),
                "Complete candidate evidence",
            ),
            (
                "Decision eligible",
                _count_label(snapshot.opportunities_reaching_cio),
                "Qualified for specialist and CIO review",
            ),
        ),
        variant="today",
    )
    concise.ui.callout_card(
        "Opportunity synopsis",
        (
            f"Strongest alternative: {snapshot.strongest_alternative}. "
            f"{concise._truncate(snapshot.strongest_stage, 110)}."
        ),
        (
            f"Portfolio impact: {concise._truncate(snapshot.main_reason, 170)} · "
            f"CIO action: {action}"
        ),
    )
    with st.expander("View opportunity scan detail", expanded=False):
        concise.ui.metric_grid(
            (
                (
                    "Market snapshots",
                    _count_label(snapshot.snapshot_covered),
                    "Usable initial evidence",
                ),
                (
                    "Assets deepened",
                    _count_label(snapshot.companies_deepened),
                    "Received deeper analysis",
                ),
            ),
            variant="today",
        )
        st.write(f"**Main reason capital did not advance:** {snapshot.main_reason}")
        st.caption(
            f"Scan as of {concise.ui.format_datetime(snapshot.as_of)} · production "
            f"context {snapshot.decision_reference} · CIO decision "
            f"{concise._decision_reference(briefing)}. {snapshot.detail}"
        )


def render_live_market_status() -> None:
    """Report implementation-data health without implying total observation scope."""

    snapshot = live_operating_console.load_live_market_console()
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    if not live_operating_console.os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip():
        st.info(
            "Presentation preview: the persistent CIO scheduler, canonical journal, "
            "paper operator, historical replay, and encrypted backups run on the "
            "Render operating deployment."
        )
    st.caption(
        "Live operating data · refreshes every 30 seconds · evaluated "
        f"{live_operating_console._format_timestamp(snapshot.get('evaluated_at'))}"
    )
    columns = st.columns(4)
    columns[0].metric(
        "Paper account",
        str(snapshot.get("account_status", "Unavailable")),
    )
    market_open = snapshot.get("market_open")
    columns[1].metric(
        "U.S. session",
        "Open"
        if market_open is True
        else "Closed"
        if market_open is False
        else "Unavailable",
    )
    columns[2].metric(
        "Implementation market data",
        _implementation_market_state(snapshot),
    )
    columns[3].metric(
        "Latest quote",
        live_operating_console._format_timestamp(snapshot.get("latest_quote_at")),
    )
    status = str(snapshot.get("status") or "").strip().lower()
    if status == "partial":
        st.warning(_partial_market_detail(snapshot))
    elif status != "connected":
        st.error(
            "Live implementation evidence is unavailable. "
            f"{snapshot.get('detail', '')}"
        )


def install(app_impl: ModuleType) -> None:
    """Install one idempotent, presentation-only opportunity-funnel refinement."""

    if getattr(app_impl, _INSTALLED_STATE_KEY, False):
        return

    for module in (app_impl, concise.base, live_operating_console):
        current_loader = getattr(module, "load_live_market_console", None)
        if callable(current_loader):
            setattr(module, "load_live_market_console", _sanitized_loader(current_loader))

    original_status_list = app_impl.status_list

    @wraps(original_status_list)
    def status_list(rows: Sequence[object], *args: object, **kwargs: object) -> object:
        return original_status_list(_refined_status_rows(rows), *args, **kwargs)

    app_impl._coverage_label = lambda snapshot: _implementation_market_state(snapshot).lower()
    app_impl.status_list = status_list
    app_impl.render_today_opportunity_scan = render_today_opportunity_scan
    app_impl.render_live_market_status = render_live_market_status
    live_operating_console.render_live_market_status = render_live_market_status
    portfolio_first_ui_refinement.install(app_impl)
    cio_report_backdrop_refinement.install(portfolio_first_ui_refinement)
    setattr(app_impl, _INSTALLED_STATE_KEY, True)


__all__ = [
    "install",
    "render_live_market_status",
    "render_today_opportunity_scan",
]
