from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from portfolio.state import (
    CanonicalImplementationEvent,
    CanonicalPortfolioIntegrityError,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
    snapshot_details,
)
from run_portfolio_migration import migrate


NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)


def snapshot(identifier: str = "portfolio:compounding:1", *, cash: float = 25_000) -> CanonicalPortfolioSnapshot:
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code="COMPOUNDING",
        display_name="Capital Intelligence Portfolio",
        constraint_profile="standard",
        as_of=NOW,
        starting_capital=250_000,
        cash_amount=cash,
        positions=(CanonicalPortfolioPosition("SPY", 100, 500, 750, NOW),),
        implementation_events=(
            CanonicalImplementationEvent("fill:1", NOW, "BUY", "SPY", 100, 500, 50_000, 10, "approved CIO implementation", "paper-fill:1"),
        ),
        source_identifiers=("construction:1", "paper-execution:1"),
    )


def test_store_is_append_only_and_returns_latest_complete_state(tmp_path) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    assert store.append(snapshot()) == 1
    assert store.append(snapshot()) == 1
    later = replace(snapshot("portfolio:compounding:2", cash=20_000), as_of=NOW + timedelta(days=1))
    store.append(later)
    store.verify_integrity()
    assert store.latest("compounding") == later
    assert store.list_latest() == (later,)
    assert len(store.history("COMPOUNDING")) == 2
    details = snapshot_details(later, history=store.history("COMPOUNDING"))
    assert details["cash"] == 20_000
    assert details["holdings"][0]["symbol"] == "SPY"
    assert details["trades"][0]["source_identifier"] == "paper-fill:1"


def test_conflicting_identifier_and_mutation_are_rejected(tmp_path) -> None:
    path = tmp_path / "portfolio.db"
    store = SQLiteCanonicalPortfolioStore(path)
    store.append(snapshot())
    with pytest.raises(ValueError):
        store.append(snapshot(cash=10_000))
    with sqlite3.connect(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE canonical_portfolio_events SET portfolio_code = 'OTHER'")


def test_tampering_is_detected(tmp_path) -> None:
    path = tmp_path / "portfolio.db"
    store = SQLiteCanonicalPortfolioStore(path)
    store.append(snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER canonical_portfolio_no_update")
        connection.execute("UPDATE canonical_portfolio_events SET payload_json = '{}' WHERE sequence = 1")
    with pytest.raises(CanonicalPortfolioIntegrityError):
        store.verify_integrity()


def test_legacy_database_migrates_read_only_into_canonical_store(tmp_path) -> None:
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.executescript("""
            CREATE TABLE mandates (id INTEGER PRIMARY KEY, code TEXT, name TEXT, risk TEXT, starting_capital REAL, cash REAL, nav REAL);
            CREATE TABLE holdings (mandate_code TEXT, symbol TEXT, quantity REAL, average_cost REAL, current_price REAL, updated_at TEXT);
            CREATE TABLE trades (id INTEGER PRIMARY KEY, created_at TEXT, mandate_code TEXT, side TEXT, symbol TEXT, quantity REAL, price REAL, gross_amount REAL, rationale TEXT);
            INSERT INTO mandates VALUES (1, 'CORE', 'Retired Core', 'standard', 100000, 50000, 101000);
            INSERT INTO mandates VALUES (2, 'COMPOUNDING', 'Capital Intelligence Portfolio', 'standard', 250000, 200000, 251000);
            INSERT INTO holdings VALUES ('CORE', 'SPY', 100, 500, 510, '2026-07-26T12:00:00+00:00');
            INSERT INTO holdings VALUES ('COMPOUNDING', 'SPY', 100, 500, 510, '2026-07-26T12:00:00+00:00');
            INSERT INTO trades VALUES (1, '2026-07-26T12:00:00+00:00', 'CORE', 'BUY', 'SPY', 100, 500, 50000, 'retired');
            INSERT INTO trades VALUES (2, '2026-07-26T12:00:00+00:00', 'COMPOUNDING', 'BUY', 'SPY', 100, 500, 50000, 'migration');
        """)
    canonical = tmp_path / "canonical.db"
    assert migrate(legacy_path=legacy, canonical_path=canonical, as_of=NOW) == 1
    state = SQLiteCanonicalPortfolioStore(canonical).latest("COMPOUNDING")
    assert state is not None
    assert state.nav == 251_000
    assert state.implementation_events[0].source_identifier == "legacy-portfolio-migration"
