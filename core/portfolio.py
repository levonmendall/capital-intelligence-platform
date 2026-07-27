"""Compatibility facade backed exclusively by canonical portfolio snapshots."""

from __future__ import annotations

import os
from pathlib import Path

from portfolio.state import SQLiteCanonicalPortfolioStore, snapshot_details, snapshot_summary


def _store() -> SQLiteCanonicalPortfolioStore:
    path = Path(os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE", "database/canonical_portfolio.db"))
    return SQLiteCanonicalPortfolioStore(path)


def initialize_portfolios() -> None:
    """Initialize only the canonical portfolio-state schema; never seed mandates."""

    _store().verify_integrity()


def get_mandates() -> list[dict]:
    """Compatibility name for authorized canonical portfolio summaries."""

    store = _store()
    store.verify_integrity()
    return [snapshot_summary(item) for item in store.list_latest()]


def get_all_mandates() -> list[dict]:
    return get_mandates()


def get_holdings(mandate_code: str | None = None) -> list[dict]:
    store = _store()
    store.verify_integrity()
    snapshots = store.list_latest() if mandate_code is None else tuple(filter(None, (store.latest(mandate_code),)))
    items: list[dict] = []
    for snapshot in snapshots:
        items.extend(snapshot_details(snapshot)["holdings"])
    return items


def get_trade_history(mandate_code: str | None = None, limit: int = 100) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be positive")
    store = _store()
    store.verify_integrity()
    snapshots = store.list_latest() if mandate_code is None else tuple(filter(None, (store.latest(mandate_code),)))
    items: list[dict] = []
    for snapshot in snapshots:
        items.extend(snapshot_details(snapshot)["trades"])
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return items[:limit]


def get_portfolio_snapshots(mandate_code: str | None = None, limit: int = 250) -> list[dict]:
    store = _store()
    store.verify_integrity()
    codes = [item.portfolio_code for item in store.list_latest()] if mandate_code is None else [mandate_code]
    items: list[dict] = []
    for code in codes:
        latest = store.latest(code)
        if latest is not None:
            items.extend(snapshot_details(latest, history=store.history(code, limit=limit))["snapshots"])
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return items[:limit]


def get_mandate_details(mandate_code: str) -> dict | None:
    store = _store()
    store.verify_integrity()
    snapshot = store.latest(mandate_code)
    if snapshot is None:
        return None
    return snapshot_details(snapshot, history=store.history(snapshot.portfolio_code))


def get_mandate(mandate_code: str) -> dict | None:
    return get_mandate_details(mandate_code)


def get_portfolio_totals() -> dict:
    snapshots = _store().list_latest()
    starting = sum(item.starting_capital for item in snapshots)
    cash = sum(item.cash_amount for item in snapshots)
    nav = sum(item.nav for item in snapshots)
    return {
        "mandate_count": len(snapshots),
        "portfolio_count": len(snapshots),
        "starting_capital": starting,
        "starting": starting,
        "cash": cash,
        "nav": nav,
        "total_return": ((nav / starting) - 1.0 if starting else 0.0),
    }


def portfolio_totals() -> dict:
    return get_portfolio_totals()
