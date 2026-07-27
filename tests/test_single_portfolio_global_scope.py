from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from market_scope import MarketFamily, load_global_market_scope
from portfolio.constants import (
    CANONICAL_PORTFOLIO_CODE,
    INITIAL_PAPER_CAPITAL,
)
from portfolio.state import (
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
    ensure_canonical_portfolio_store,
)


NOW = datetime(2026, 7, 27, 20, tzinfo=timezone.utc)


def test_empty_database_bootstraps_one_250000_portfolio(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    result = ensure_canonical_portfolio_store(path, as_of=NOW)

    assert result.created is True
    assert result.reset is False
    store = SQLiteCanonicalPortfolioStore(path)
    portfolios = store.list_latest()
    assert len(portfolios) == 1
    assert portfolios[0].portfolio_code == CANONICAL_PORTFOLIO_CODE
    assert portfolios[0].starting_capital == INITIAL_PAPER_CAPITAL
    assert portfolios[0].cash_amount == INITIAL_PAPER_CAPITAL
    assert portfolios[0].nav == INITIAL_PAPER_CAPITAL


def test_noncanonical_snapshot_is_rejected_before_storage(tmp_path) -> None:
    with pytest.raises(ValueError, match="sole canonical portfolio"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:GROWTH:1",
            portfolio_code="GROWTH",
            display_name="Growth",
            constraint_profile="legacy",
            as_of=NOW,
            starting_capital=INITIAL_PAPER_CAPITAL,
            cash_amount=INITIAL_PAPER_CAPITAL,
            positions=(),
        )


def test_valid_incompatible_history_is_archived_then_reset(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    # Build a valid pre-change hash chain using the current hash algorithm and a
    # legacy portfolio code. This proves the reset path does not confuse
    # incompatibility with corruption.
    payload = {
        "identifier": "legacy:CORE:1",
        "portfolio_code": "CORE",
        "display_name": "Legacy Core",
        "constraint_profile": "legacy",
        "as_of": NOW.isoformat(),
        "starting_capital": 400000.0,
        "cash_amount": 400000.0,
        "positions": [],
        "implementation_events": [],
        "source_identifiers": ["legacy-test"],
        "schema_version": "canonical-portfolio-state.v2",
        "base_currency": "USD",
        "currency_balances": [],
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    previous_hash = "0" * 64
    content_hash = SQLiteCanonicalPortfolioStore._hash(
        sequence=1,
        event_identifier="legacy:CORE:1",
        portfolio_code="CORE",
        occurred_at=NOW.isoformat(),
        payload_json=payload_json,
        previous_hash=previous_hash,
    )
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE canonical_portfolio_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_identifier TEXT NOT NULL UNIQUE,
                portfolio_code TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_portfolio_events (
                sequence, event_identifier, portfolio_code, occurred_at,
                payload_json, previous_hash, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "legacy:CORE:1",
                "CORE",
                NOW.isoformat(),
                payload_json,
                previous_hash,
                content_hash,
            ),
        )

    result = ensure_canonical_portfolio_store(path, as_of=NOW)
    assert result.reset is True
    assert result.archive_path is not None and result.archive_path.exists()
    assert result.archive_path.with_suffix(result.archive_path.suffix + ".json").exists()
    latest = SQLiteCanonicalPortfolioStore(path).latest()
    assert latest is not None
    assert latest.portfolio_code == CANONICAL_PORTFOLIO_CODE
    assert latest.starting_capital == INITIAL_PAPER_CAPITAL
    assert latest.cash_amount == INITIAL_PAPER_CAPITAL


def test_hash_chain_corruption_is_not_auto_reset(tmp_path) -> None:
    path = tmp_path / "canonical.db"
    ensure_canonical_portfolio_store(path, as_of=NOW)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER canonical_portfolio_no_update")
        connection.execute(
            "UPDATE canonical_portfolio_events SET payload_json = '{}' WHERE sequence = 1"
        )
    with pytest.raises(RuntimeError, match="content hash"):
        ensure_canonical_portfolio_store(path, as_of=NOW)


def test_global_market_scope_requires_every_market_and_no_static_symbols() -> None:
    scope = load_global_market_scope()
    assert {entry.market_family for entry in scope.markets} == set(MarketFamily)
    assert all(entry.analysis_required for entry in scope.markets)
    assert scope.static_symbols == ()
    assert scope.portfolio_code == CANONICAL_PORTFOLIO_CODE
