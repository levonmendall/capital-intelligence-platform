"""Tests for local-currency lineage and base-currency portfolio valuation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio import (
    CanonicalCurrencyBalance,
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)
from portfolio.state import snapshot_details, snapshot_from_dict, snapshot_to_dict

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)


def test_legacy_usd_snapshot_round_trips_without_fx_configuration() -> None:
    snapshot = CanonicalPortfolioSnapshot(
        identifier="portfolio:legacy-usd",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF,
        starting_capital=100_000,
        cash_amount=20_000,
        positions=(
            CanonicalPortfolioPosition(
                symbol="AAPL",
                quantity=100,
                average_cost=180,
                mark_price=200,
                updated_at=AS_OF,
            ),
        ),
    )

    restored = snapshot_from_dict(snapshot_to_dict(snapshot))

    assert restored == snapshot
    assert restored.base_currency == "USD"
    assert restored.currency_balances == ()
    assert restored.positions[0].fx_rate_to_base == 1.0
    assert restored.holdings_value == 20_000
    assert restored.total_cash_value == 20_000
    assert restored.nav == 40_000


def test_global_equity_preserves_local_and_base_currency_values() -> None:
    position = CanonicalPortfolioPosition(
        symbol="SHEL",
        instrument_identifier="GLOBAL:EQUITY:LSE:SHEL",
        venue="LSE",
        asset_class="international_equity",
        quantity=1_000,
        average_cost=24.0,
        average_cost_base=30.0,
        mark_price=26.0,
        price_currency="GBP",
        settlement_currency="GBP",
        fx_rate_to_base=1.30,
        fx_rate_observed_at=AS_OF - timedelta(minutes=1),
        fx_rate_source_identifier="fx:GBPUSD:2026-07-27T15:59Z",
        updated_at=AS_OF,
    )
    snapshot = CanonicalPortfolioSnapshot(
        identifier="portfolio:global-equity",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF,
        starting_capital=100_000,
        cash_amount=10_000,
        base_currency="USD",
        positions=(position,),
        source_identifiers=("security-master:global", "fx:GBPUSD:2026-07-27T15:59Z"),
    )

    assert position.local_cost_basis == 24_000
    assert position.local_market_value == 26_000
    assert position.cost_basis == 30_000
    assert position.market_value == 33_800
    assert position.unrealized_gain == 3_800
    assert snapshot.nav == 43_800

    detail = snapshot_details(snapshot)
    holding = detail["holdings"][0]
    assert holding["price_currency"] == "GBP"
    assert holding["market_value"] == 33_800
    assert holding["fx_rate_source_identifier"].startswith("fx:GBPUSD")


def test_non_base_currency_cash_is_translated_once() -> None:
    snapshot = CanonicalPortfolioSnapshot(
        identifier="portfolio:currency-cash",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF,
        starting_capital=100_000,
        cash_amount=5_000,
        base_currency="USD",
        currency_balances=(
            CanonicalCurrencyBalance(
                currency="EUR",
                amount=10_000,
                fx_rate_to_base=1.10,
                updated_at=AS_OF,
                fx_rate_source_identifier="fx:EURUSD:close",
            ),
            CanonicalCurrencyBalance(
                currency="JPY",
                amount=1_000_000,
                fx_rate_to_base=0.0068,
                updated_at=AS_OF,
                fx_rate_source_identifier="fx:JPYUSD:close",
            ),
        ),
        positions=(),
    )

    assert snapshot.non_base_cash_value == 17_800
    assert snapshot.total_cash_value == 22_800
    assert snapshot.nav == 22_800


def test_non_base_position_requires_fx_lineage_and_base_acquisition_cost() -> None:
    with pytest.raises(ValueError, match="point-in-time FX evidence"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:missing-fx",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=AS_OF,
            starting_capital=100_000,
            cash_amount=100_000,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="SHEL",
                    quantity=1,
                    average_cost=24,
                    mark_price=26,
                    updated_at=AS_OF,
                    price_currency="GBP",
                    settlement_currency="GBP",
                    average_cost_base=30,
                ),
            ),
        )

    with pytest.raises(ValueError, match="base-currency acquisition cost"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:missing-cost",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=AS_OF,
            starting_capital=100_000,
            cash_amount=100_000,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="SHEL",
                    quantity=1,
                    average_cost=24,
                    mark_price=26,
                    updated_at=AS_OF,
                    price_currency="GBP",
                    settlement_currency="GBP",
                    fx_rate_to_base=1.3,
                    fx_rate_observed_at=AS_OF,
                    fx_rate_source_identifier="fx:GBPUSD",
                ),
            ),
        )


def test_future_known_fx_and_base_cash_duplication_are_rejected() -> None:
    with pytest.raises(ValueError, match="cannot follow portfolio as_of"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:future-fx",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=AS_OF,
            starting_capital=100_000,
            cash_amount=100_000,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="SHEL",
                    quantity=1,
                    average_cost=24,
                    average_cost_base=30,
                    mark_price=26,
                    updated_at=AS_OF,
                    price_currency="GBP",
                    settlement_currency="GBP",
                    fx_rate_to_base=1.3,
                    fx_rate_observed_at=AS_OF + timedelta(seconds=1),
                    fx_rate_source_identifier="fx:future",
                ),
            ),
        )

    with pytest.raises(ValueError, match="base-currency cash belongs"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:duplicate-usd",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=AS_OF,
            starting_capital=100_000,
            cash_amount=50_000,
            base_currency="USD",
            currency_balances=(
                CanonicalCurrencyBalance(
                    currency="USD",
                    amount=50_000,
                    fx_rate_to_base=1.0,
                    updated_at=AS_OF,
                    fx_rate_source_identifier="fx:USDUSD",
                ),
            ),
            positions=(),
        )


def test_position_identity_prevents_symbol_collision_across_venues() -> None:
    with pytest.raises(ValueError, match="instrument identifiers must be unique"):
        CanonicalPortfolioSnapshot(
            identifier="portfolio:duplicate-instrument",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=AS_OF,
            starting_capital=100_000,
            cash_amount=50_000,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="ABC",
                    instrument_identifier="instrument:one",
                    venue="LSE",
                    quantity=1,
                    average_cost=10,
                    mark_price=10,
                    updated_at=AS_OF,
                ),
                CanonicalPortfolioPosition(
                    symbol="XYZ",
                    instrument_identifier="instrument:one",
                    venue="NYSE",
                    quantity=1,
                    average_cost=10,
                    mark_price=10,
                    updated_at=AS_OF,
                ),
            ),
        )


def test_cross_currency_implementation_event_preserves_base_amounts() -> None:
    event = CanonicalImplementationEvent(
        identifier="implementation:global-buy",
        occurred_at=AS_OF,
        action="buy",
        symbol="SHEL",
        instrument_identifier="GLOBAL:EQUITY:LSE:SHEL",
        venue="LSE",
        asset_class="international_equity",
        quantity=100,
        price=26,
        gross_amount=2_600,
        cost_amount=5,
        price_currency="GBP",
        settlement_currency="GBP",
        fx_rate_to_base=1.3,
        fx_rate_source_identifier="fx:GBPUSD",
    )

    assert event.gross_amount_base == 3_380
    assert event.cost_amount_base == 6.5


def test_cross_currency_snapshot_remains_append_only(tmp_path: Path) -> None:
    snapshot = CanonicalPortfolioSnapshot(
        identifier="portfolio:stored-cross-currency",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF,
        starting_capital=100_000,
        cash_amount=50_000,
        currency_balances=(
            CanonicalCurrencyBalance(
                currency="EUR",
                amount=10_000,
                fx_rate_to_base=1.1,
                updated_at=AS_OF,
                fx_rate_source_identifier="fx:EURUSD",
            ),
        ),
        positions=(),
    )
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")

    assert store.append(snapshot) == 1
    assert store.append(snapshot) == 1
    assert store.latest("COMPOUNDING") == snapshot
    store.verify_integrity()
