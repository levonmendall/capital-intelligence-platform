from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from portfolio.constants import INITIAL_PAPER_CAPITAL
from portfolio.initialization import (
    CanonicalPortfolioInitializationError,
    ensure_canonical_portfolio_store,
)
from portfolio.state import (
    CanonicalPortfolioPosition,
    SQLiteCanonicalPortfolioStore,
    canonical_initial_snapshot,
    snapshot_to_dict,
)


def test_clean_first_boot_creates_exactly_one_genesis(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    as_of = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)

    result = ensure_canonical_portfolio_store(path, as_of=as_of)
    store = SQLiteCanonicalPortfolioStore(path)
    latest = store.latest()

    assert result.created is True
    assert result.state == "bootstrapped"
    assert result.reset is False
    assert result.archive_path is None
    assert result.paper_only is True
    assert result.real_money_authorized is False
    assert latest is not None
    assert latest.starting_capital == INITIAL_PAPER_CAPITAL
    assert latest.cash_amount == INITIAL_PAPER_CAPITAL
    assert latest.positions == ()
    assert len(store.history(latest.portfolio_code)) == 1


def test_repeated_initialization_recovers_without_reset(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    first = ensure_canonical_portfolio_store(path)
    second = ensure_canonical_portfolio_store(path)

    assert first.created is True
    assert second.created is False
    assert second.state == "recovered"
    assert second.reset is False
    assert second.archive_path is None
    assert second.state_generation_id == first.state_generation_id
    assert second.state_hash == first.state_hash
    assert len(SQLiteCanonicalPortfolioStore(path).history("COMPOUNDING")) == 1


def test_concurrent_initialization_commits_only_one_genesis(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: ensure_canonical_portfolio_store(path), range(8)))

    assert sum(1 for result in results if result.created) == 1
    assert sum(1 for result in results if result.state == "recovered") == 7
    store = SQLiteCanonicalPortfolioStore(path)
    assert len(store.history("COMPOUNDING")) == 1
    store.verify_integrity()


def test_existing_invested_portfolio_is_recovered_unchanged(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    ensure_canonical_portfolio_store(path)
    store = SQLiteCanonicalPortfolioStore(path)
    prior = store.latest()
    assert prior is not None

    position = CanonicalPortfolioPosition(
        symbol="SPY",
        quantity=10.0,
        average_cost=100.0,
        mark_price=100.0,
        updated_at=prior.as_of + timedelta(minutes=1),
        instrument_identifier="US:SPY",
        venue="ARCX",
        asset_class="equity_etf",
    )
    invested = replace(
        prior,
        identifier="portfolio-state:invested-regression",
        as_of=prior.as_of + timedelta(minutes=1),
        cash_amount=INITIAL_PAPER_CAPITAL - 1000.0,
        positions=(position,),
        source_identifiers=("invested-regression",),
    )
    store.append(invested)

    result = ensure_canonical_portfolio_store(path)
    recovered = SQLiteCanonicalPortfolioStore(path).latest()

    assert result.state == "recovered"
    assert result.created is False
    assert recovered == invested
    assert len(SQLiteCanonicalPortfolioStore(path).history("COMPOUNDING")) == 2


def test_existing_empty_database_is_invalid_not_absent(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    sqlite3.connect(path).close()

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.initialization_state == "invalid"
    assert caught.value.failure_type == "missing_snapshot"
    assert path.exists()


def test_tampered_history_fails_closed_without_replacement(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    ensure_canonical_portfolio_store(path)
    original_bytes = path.read_bytes()

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER canonical_portfolio_no_update")
        row = connection.execute(
            "SELECT sequence, payload_json FROM canonical_portfolio_events LIMIT 1"
        ).fetchone()
        payload = json.loads(row[1])
        payload["cash_amount"] = 1.0
        connection.execute(
            "UPDATE canonical_portfolio_events SET payload_json = ? WHERE sequence = ?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), row[0]),
        )

    tampered_bytes = path.read_bytes()
    assert tampered_bytes != original_bytes

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.failure_type == "digest_mismatch"
    assert path.read_bytes() == tampered_bytes


def test_missing_database_after_prior_genesis_is_not_first_boot(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    ensure_canonical_portfolio_store(path)
    path.unlink()

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.failure_type == "missing_snapshot"
    assert not path.exists()


def test_unsupported_schema_fails_explicitly(tmp_path) -> None:
    path = tmp_path / "canonical_portfolio.db"
    store = SQLiteCanonicalPortfolioStore(path)
    unsupported = replace(
        canonical_initial_snapshot(),
        schema_version="canonical-portfolio-state.v999",
    )
    store.append(unsupported)

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.failure_type == "schema_mismatch"
    assert len(SQLiteCanonicalPortfolioStore(path).history("COMPOUNDING")) == 1


def test_live_money_governance_flags_are_rejected(tmp_path, monkeypatch) -> None:
    path = tmp_path / "canonical_portfolio.db"
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_REAL_MONEY_AUTHORIZED", "true")

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.failure_type == "invalid_governance_state"
    assert not path.exists()


def test_paper_only_cannot_be_disabled(tmp_path, monkeypatch) -> None:
    path = tmp_path / "canonical_portfolio.db"
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_PAPER_ONLY", "false")

    with pytest.raises(CanonicalPortfolioInitializationError) as caught:
        ensure_canonical_portfolio_store(path)

    assert caught.value.failure_type == "invalid_governance_state"
    assert not path.exists()
