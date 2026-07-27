"""Compatibility facade backed exclusively by the sole canonical portfolio."""

from __future__ import annotations

import os
from pathlib import Path

from portfolio.constants import CANONICAL_PORTFOLIO_CODE
from portfolio.state import (
    SQLiteCanonicalPortfolioStore,
    ensure_canonical_portfolio_store,
    snapshot_details,
    snapshot_summary,
)


def _portfolio_path() -> Path:
    return Path(
        os.getenv(
            "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE",
            "database/canonical_portfolio.db",
        )
    )


def _store() -> SQLiteCanonicalPortfolioStore:
    path = _portfolio_path()
    ensure_canonical_portfolio_store(path)
    return SQLiteCanonicalPortfolioStore(path)


def initialize_portfolios() -> None:
    """Create or safely reset the sole $250,000 canonical paper portfolio."""

    ensure_canonical_portfolio_store(_portfolio_path())


def get_mandates() -> list[dict]:
    """Compatibility name for the single canonical portfolio summary."""

    store = _store()
    store.verify_integrity()
    latest = store.latest(CANONICAL_PORTFOLIO_CODE)
    return [] if latest is None else [snapshot_summary(latest)]


def get_all_mandates() -> list[dict]:
    return get_mandates()


def get_holdings(mandate_code: str | None = None) -> list[dict]:
    if mandate_code is not None and mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
        return []
    store = _store()
    store.verify_integrity()
    snapshot = store.latest(CANONICAL_PORTFOLIO_CODE)
    return [] if snapshot is None else snapshot_details(snapshot)["holdings"]


def get_trade_history(mandate_code: str | None = None, limit: int = 100) -> list[dict]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be positive")
    if mandate_code is not None and mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
        return []
    store = _store()
    store.verify_integrity()
    snapshot = store.latest(CANONICAL_PORTFOLIO_CODE)
    if snapshot is None:
        return []
    items = snapshot_details(snapshot)["trades"]
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return items[:limit]


def get_portfolio_snapshots(mandate_code: str | None = None, limit: int = 250) -> list[dict]:
    if mandate_code is not None and mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
        return []
    store = _store()
    store.verify_integrity()
    latest = store.latest(CANONICAL_PORTFOLIO_CODE)
    if latest is None:
        return []
    items = snapshot_details(
        latest,
        history=store.history(CANONICAL_PORTFOLIO_CODE, limit=limit),
    )["snapshots"]
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return items[:limit]


def get_mandate_details(mandate_code: str = CANONICAL_PORTFOLIO_CODE) -> dict | None:
    if mandate_code.strip().upper() != CANONICAL_PORTFOLIO_CODE:
        return None
    store = _store()
    store.verify_integrity()
    snapshot = store.latest(CANONICAL_PORTFOLIO_CODE)
    if snapshot is None:
        return None
    return snapshot_details(
        snapshot,
        history=store.history(CANONICAL_PORTFOLIO_CODE),
    )


def get_mandate(mandate_code: str = CANONICAL_PORTFOLIO_CODE) -> dict | None:
    return get_mandate_details(mandate_code)


def get_portfolio_totals() -> dict:
    store = _store()
    store.verify_integrity()
    snapshot = store.latest(CANONICAL_PORTFOLIO_CODE)
    if snapshot is None:
        return {
            "mandate_count": 0,
            "portfolio_count": 0,
            "starting_capital": 0.0,
            "starting": 0.0,
            "cash": 0.0,
            "nav": 0.0,
            "total_return": 0.0,
        }
    return {
        "mandate_count": 1,
        "portfolio_count": 1,
        "starting_capital": snapshot.starting_capital,
        "starting": snapshot.starting_capital,
        "cash": snapshot.total_cash_value,
        "nav": snapshot.nav,
        "total_return": snapshot.total_return,
    }


def portfolio_totals() -> dict:
    return get_portfolio_totals()
