"""Real-time, provider-backed Streamlit operating views.

No sample market values are emitted. When a live source is unavailable, the UI reports
that state explicitly and continues displaying the last governed canonical records.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

import premium_ui as ui

from cio_pending_transactions import pending_report_paths
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    load_free_paper_pilot_universe,
)
from paper_execution_runtime import artifact_directory
from provider_configuration import (
    alpaca_credential_readiness,
    safe_provider_error,
)
from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    AlpacaPaperSettings,
)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: object) -> str:
    parsed = value if isinstance(value, datetime) else _timestamp(value)
    if not isinstance(parsed, datetime):
        return "—"
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_money(value: object) -> str:
    number = _number(value)
    return "—" if number is None else f"${number:,.2f}"


def _format_percent(value: object) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2%}"


def _sequence(value: object) -> list[Any]:
    return (
        list(value)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        else []
    )


def _unavailable_snapshot(
    *,
    evaluated_at: datetime,
    detail: str,
    expected_quote_count: int,
    configuration_state: str,
) -> dict[str, object]:
    return {
        "status": "unavailable",
        "detail": detail,
        "configuration_state": configuration_state,
        "evaluated_at": evaluated_at.isoformat(),
        "account_status": "Unavailable",
        "market_open": None,
        "clock_at": None,
        "quote_count": 0,
        "expected_quote_count": expected_quote_count,
        "latest_quote_at": None,
        "rows": [],
        "source": "Alpaca paper account + IEX",
        "paper_only": True,
        "real_money_authorized": False,
    }


@st.cache_data(ttl=20, show_spinner=False)
def load_live_market_console() -> dict[str, object]:
    evaluated_at = datetime.now(timezone.utc)
    try:
        universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    except (OSError, TypeError, ValueError) as error:
        return _unavailable_snapshot(
            evaluated_at=evaluated_at,
            detail=(
                "The governed paper universe could not be loaded. Review the deployed "
                "universe artifact and service logs."
            ),
            expected_quote_count=15,
            configuration_state="universe_unavailable",
        )

    instruments = tuple(universe.instruments)
    readiness = alpaca_credential_readiness()
    if not readiness.configured:
        return _unavailable_snapshot(
            evaluated_at=evaluated_at,
            detail=readiness.detail,
            expected_quote_count=len(instruments),
            configuration_state=readiness.state,
        )

    try:
        settings = AlpacaPaperSettings.from_env()
        client = AlpacaPaperClient(settings)
        account = client.account()
        clock = client.clock()
        quotes = client.latest_quotes([item.symbol for item in instruments])
    except (OSError, TypeError, ValueError, AlpacaPaperProviderError) as error:
        return _unavailable_snapshot(
            evaluated_at=evaluated_at,
            detail=safe_provider_error("alpaca", error),
            expected_quote_count=len(instruments),
            configuration_state="invalid",
        )

    rows: list[dict[str, object]] = []
    latest_quote_at: datetime | None = None
    for instrument in instruments:
        quote = quotes.get(instrument.symbol, {})
        bid = _number(quote.get("bp"))
        ask = _number(quote.get("ap"))
        bid_size = _number(quote.get("bs"))
        ask_size = _number(quote.get("as"))
        observed_at = _timestamp(quote.get("t"))
        if observed_at is not None and (
            latest_quote_at is None or observed_at > latest_quote_at
        ):
            latest_quote_at = observed_at
        valid_top = (
            bid is not None
            and ask is not None
            and bid > 0.0
            and ask > 0.0
            and ask >= bid
        )
        mid = (bid + ask) / 2.0 if valid_top else None
        spread_bps = (
            ((ask - bid) / mid) * 10_000.0
            if valid_top and mid is not None and mid > 0.0
            else None
        )
        quote_age_seconds = (
            max((evaluated_at - observed_at).total_seconds(), 0.0)
            if observed_at is not None
            else None
        )
        rows.append(
            {
                "symbol": instrument.symbol,
                "name": instrument.name,
                "economic_exposure": instrument.economic_exposure,
                "asset_class": instrument.execution_asset_class.value,
                "bid": bid if bid is not None and bid > 0.0 else None,
                "ask": ask if ask is not None and ask > 0.0 else None,
                "mid": mid,
                "spread_bps": spread_bps,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "quote_at": None if observed_at is None else observed_at.isoformat(),
                "quote_age_seconds": quote_age_seconds,
                "current": bool(
                    quote_age_seconds is not None
                    and quote_age_seconds
                    <= universe.maximum_quote_age_minutes * 60
                ),
            }
        )

    usable_quote_count = sum(1 for row in rows if row.get("mid") is not None)
    status = "connected" if usable_quote_count == len(instruments) else "partial"
    detail = (
        "Current provider-backed paper-market evidence is available."
        if status == "connected"
        else (
            f"Only {usable_quote_count} of {len(instruments)} governed instruments "
            "have usable top-of-book evidence."
        )
    )
    clock_at = _timestamp(clock.get("timestamp"))
    return {
        "status": status,
        "detail": detail,
        "configuration_state": "configured",
        "evaluated_at": evaluated_at.isoformat(),
        "account_status": str(account.get("status", "Unavailable")),
        "market_open": clock.get("is_open") is True,
        "clock_at": None if clock_at is None else clock_at.isoformat(),
        "quote_count": usable_quote_count,
        "expected_quote_count": len(instruments),
        "latest_quote_at": (
            None if latest_quote_at is None else latest_quote_at.isoformat()
        ),
        "rows": rows,
        "source": "Alpaca paper account + IEX",
        "paper_only": True,
        "real_money_authorized": False,
    }


def render_live_market_status() -> None:
    snapshot = load_live_market_console()
    if not os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip():
        st.info(
            "Presentation preview: the persistent CIO scheduler, canonical journal, "
            "paper operator, historical replay, and encrypted backups run on the "
            "Render operating deployment."
        )
    st.caption(
        "Live operating data · refreshes every 30 seconds · "
        f"evaluated {_format_timestamp(snapshot.get('evaluated_at'))}"
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
        "Live quote coverage",
        f"{snapshot.get('quote_count', 0)}/{snapshot.get('expected_quote_count', 0)}",
    )
    columns[3].metric(
        "Latest quote",
        _format_timestamp(snapshot.get("latest_quote_at")),
    )
    status = snapshot.get("status")
    if status == "partial":
        st.warning(str(snapshot.get("detail", "Partial live provider coverage.")))
    elif status != "connected":
        st.error(
            "Live Alpaca/IEX evidence is unavailable. "
            f"{snapshot.get('detail', '')}"
        )


def render_live_environment_market_table() -> None:
    snapshot = load_live_market_console()
    st.markdown("#### Live cross-asset wrapper monitor")
    st.caption(
        "Provider-backed top-of-book evidence for the 15 instruments currently eligible "
        "for the controlled all-exposure paper pilot."
    )
    rows = snapshot.get("rows")
    if not isinstance(rows, list) or not rows:
        st.error(
            "No live market table is available. "
            f"{snapshot.get('detail', '')}"
        )
        return
    frame = pd.DataFrame(rows)
    frame = frame.rename(
        columns={
            "economic_exposure": "Exposure",
            "symbol": "Symbol",
            "name": "Instrument",
            "bid": "Bid",
            "ask": "Ask",
            "mid": "Mid",
            "spread_bps": "Spread (bps)",
            "quote_at": "Quote time",
            "quote_age_seconds": "Age (sec)",
            "current": "Current",
        }
    )
    columns = [
        "Exposure",
        "Symbol",
        "Instrument",
        "Bid",
        "Ask",
        "Mid",
        "Spread (bps)",
        "Age (sec)",
        "Current",
        "Quote time",
    ]
    frame = frame[[column for column in columns if column in frame.columns]]
    for column in ("Bid", "Ask", "Mid"):
        if column in frame.columns:
            frame[column] = frame[column].map(_format_money)
    if "Spread (bps)" in frame.columns:
        frame["Spread (bps)"] = frame["Spread (bps)"].map(
            lambda value: "—"
            if _number(value) is None
            else f"{float(value):.2f}"
        )
    if "Age (sec)" in frame.columns:
        frame["Age (sec)"] = frame["Age (sec)"].map(
            lambda value: "—"
            if _number(value) is None
            else f"{float(value):.0f}"
        )
    if "Quote time" in frame.columns:
        frame["Quote time"] = frame["Quote time"].map(_format_timestamp)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    st.caption(
        f"Source: {snapshot.get('source')} · Session clock: "
        f"{_format_timestamp(snapshot.get('clock_at'))}"
    )
    if snapshot.get("status") == "partial":
        st.warning(str(snapshot.get("detail", "Partial live provider coverage.")))


def render_live_portfolio_marks(mandate: Mapping[str, Any]) -> None:
    st.markdown("#### Live indicative portfolio mark")
    snapshot = load_live_market_console()
    holdings = [
        item
        for item in _sequence(mandate.get("holdings"))
        if isinstance(item, Mapping)
    ]
    cash = _number(mandate.get("cash")) or 0.0
    canonical_nav = _number(mandate.get("nav")) or cash
    if not holdings:
        st.info(
            "The portfolio currently holds cash only. Live indicative NAV equals the "
            f"canonical cash balance of {_format_money(cash)}."
        )
        return
    quote_map = {
        str(item.get("symbol", "")).upper(): item
        for item in _sequence(snapshot.get("rows"))
        if isinstance(item, Mapping)
    }
    rows: list[dict[str, object]] = []
    live_holdings_value = 0.0
    complete = True
    for holding in holdings:
        symbol = str(holding.get("symbol", "")).strip().upper()
        quantity = _number(holding.get("quantity"))
        canonical_price = _number(holding.get("current_price"))
        quote = quote_map.get(symbol, {})
        live_mid = (
            _number(quote.get("mid")) if isinstance(quote, Mapping) else None
        )
        if quantity is None or live_mid is None:
            complete = False
            live_value = None
        else:
            live_value = quantity * live_mid
            live_holdings_value += live_value
        canonical_value = _number(holding.get("market_value"))
        rows.append(
            {
                "Symbol": symbol,
                "Quantity": quantity,
                "Canonical price": canonical_price,
                "Live mid": live_mid,
                "Canonical value": canonical_value,
                "Live value": live_value,
                "Mark change": (
                    None
                    if live_value is None or canonical_value is None
                    else live_value - canonical_value
                ),
                "Quote time": (
                    quote.get("quote_at") if isinstance(quote, Mapping) else None
                ),
            }
        )
    indicative_nav = cash + live_holdings_value if complete else None
    metrics = st.columns(4)
    metrics[0].metric("Canonical NAV", _format_money(canonical_nav))
    metrics[1].metric("Indicative live NAV", _format_money(indicative_nav))
    metrics[2].metric(
        "Live mark difference",
        _format_money(
            None if indicative_nav is None else indicative_nav - canonical_nav
        ),
    )
    market_open = snapshot.get("market_open")
    metrics[3].metric(
        "Market session",
        "Open"
        if market_open is True
        else "Closed"
        if market_open is False
        else "Unavailable",
    )
    frame = pd.DataFrame(rows)
    for column in (
        "Canonical price",
        "Live mid",
        "Canonical value",
        "Live value",
        "Mark change",
    ):
        if column in frame.columns:
            frame[column] = frame[column].map(_format_money)
    if "Quote time" in frame.columns:
        frame["Quote time"] = frame["Quote time"].map(_format_timestamp)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if not complete:
        st.warning(
            "One or more holdings lack a current live quote. The canonical portfolio "
            "remains authoritative and no partial indicative NAV is presented."
        )
    st.caption(
        "Indicative marks are display-only. The canonical reconciled portfolio ledger "
        "remains the accounting and paper-execution authority."
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def render_operating_report_history() -> None:
    ui.page_header(
        "Operating reports",
        "The current portfolio-level report, launch state, and paper-execution status.",
        "OPS",
    )
    json_path, markdown_path = pending_report_paths()
    report = _load_json(json_path)
    if report is None:
        st.info("The first CIO pending-transactions report has not been generated yet.")
    else:
        report_state = (
            str(report.get("report_state", "Unavailable"))
            .replace("_", " ")
            .title()
        )
        launch_state = str(report.get("launch_state", "Unavailable")).title()
        execution_state = (
            str(report.get("execution_state", "Unavailable"))
            .replace("_", " ")
            .title()
        )
        ui.metric_grid(
            (
                ("Report state", report_state, "Portfolio recommendation"),
                ("Transactions", int(report.get("transaction_count", 0)), "Paper actions"),
                ("Launch state", launch_state, "Operating availability"),
                ("Execution", execution_state, "Current worker state"),
            ),
            variant="history",
        )
        ui.callout_card(
            "Current report",
            str(report.get("summary") or report_state),
            (
                f"Generated {_format_timestamp(report.get('generated_at'))} · "
                f"Decision reference {report.get('decision_identifier') or 'not applicable'}"
            ),
        )
        transactions = report.get("transactions")
        if isinstance(transactions, list) and transactions:
            frame = pd.DataFrame(transactions)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        if markdown_path.exists():
            with st.expander("Full CIO report", expanded=False):
                st.markdown(markdown_path.read_text(encoding="utf-8"))

    statuses: list[dict[str, object]] = []
    try:
        status_paths = sorted(
            artifact_directory().glob("*.status.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:25]
    except OSError:
        status_paths = []
    for path in status_paths:
        payload = _load_json(path)
        if payload is None:
            continue
        statuses.append(
            {
                "Attempted": _format_timestamp(payload.get("attempted_at")),
                "State": str(payload.get("state", "unavailable")).title(),
                "Detail": str(payload.get("detail", "")),
                "Execution ID": str(payload.get("execution_identifier") or ""),
                "Paper only": payload.get("real_money_authorized") is False,
            }
        )
    if statuses:
        with st.expander("Paper execution attempts", expanded=False):
            st.dataframe(statuses, use_container_width=True, hide_index=True)


__all__ = [
    "load_live_market_console",
    "render_live_environment_market_table",
    "render_live_market_status",
    "render_live_portfolio_marks",
    "render_operating_report_history",
]
