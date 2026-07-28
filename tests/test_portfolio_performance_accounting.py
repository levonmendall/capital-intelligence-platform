"""Tests for canonical realized, unrealized, FX, and cash-flow accounting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from governance import AssetClassApprovalState
from portfolio import (
    CanonicalCurrencyBalance,
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    CurrencyRateMark,
    MultiAssetInstrumentProfile,
    MultiAssetQuote,
    PortfolioAccountingMigrationService,
    PortfolioCashFlowKind,
    PortfolioCashFlowService,
    PortfolioMarkToMarketService,
    PortfolioPerformanceError,
    PortfolioPositionAdjustmentService,
    SQLiteCanonicalPortfolioStore,
)
from portfolio.state import snapshot_details, snapshot_from_dict, snapshot_to_dict

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 16, 0, tzinfo=UTC)


class QuoteProvider:
    def __init__(self, values: dict[str, MultiAssetQuote]) -> None:
        self.values = values

    def quotes(self, profiles, *, as_of):
        return {item.symbol: self.values[item.symbol] for item in profiles}


class RateProvider:
    def __init__(self, values: dict[str, CurrencyRateMark]) -> None:
        self.values = values

    def rates(self, currencies, *, base_currency, as_of):
        return {currency: self.values[currency] for currency in currencies}


def _profile() -> MultiAssetInstrumentProfile:
    return MultiAssetInstrumentProfile(
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        asset_class=CandidateAssetClass.US_ETF,
        venue="NYSEARCA",
        country_code="US",
        price_currency="USD",
        settlement_currency="USD",
        approval_identifier="core-policy:us-etf:v1",
        approval_state=AssetClassApprovalState.PAPER_ELIGIBLE,
        unlevered=True,
        spot_only=True,
        custody_settlement_identifier="alpaca-paper-custody:v1",
        execution_model_version="alpaca-paper-iex:v1",
        instrument_type="fund",
    )


def _position() -> CanonicalPortfolioPosition:
    return CanonicalPortfolioPosition(
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        venue="NYSEARCA",
        asset_class="us_etf",
        quantity=50,
        average_cost=10,
        mark_price=10,
        updated_at=AS_OF - timedelta(minutes=5),
    )


def _snapshot(*, positions=(_position(),), cash=249_500.0, starting=250_000.0, balances=()):
    return CanonicalPortfolioSnapshot(
        identifier="portfolio:performance:beginning",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF - timedelta(minutes=5),
        starting_capital=starting,
        cash_amount=cash,
        positions=positions,
        currency_balances=balances,
    )


def _quote(*, observed_at=AS_OF, last=12.0) -> MultiAssetQuote:
    profile = _profile()
    return MultiAssetQuote(
        symbol=profile.symbol,
        instrument_identifier=profile.instrument_identifier,
        venue=profile.venue,
        observed_at=observed_at,
        bid=last - 0.01,
        ask=last + 0.01,
        last=last,
        available_base_notional=10_000_000,
        price_currency="USD",
        fx_rate_to_base=1.0,
        fx_observed_at=observed_at,
        quote_source_identifier="alpaca-iex:vti",
        fx_source_identifier="fx:USDUSD",
        quote_certification_identifier="quote-certification:alpaca-iex:v1",
    )


def test_mark_to_market_updates_nav_and_unrealized_pnl_without_a_trade(tmp_path: Path) -> None:
    beginning = _snapshot()
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(beginning)

    report = PortfolioMarkToMarketService(
        quote_provider=QuoteProvider({"VTI": _quote()}),
        portfolio_store=store,
    ).mark(
        portfolio=beginning,
        profiles={"VTI": _profile()},
        as_of=AS_OF,
    )

    ending = store.latest()
    assert ending is not None
    assert ending.nav == pytest.approx(250_100.0)
    assert ending.total_pnl == pytest.approx(100.0)
    assert ending.unrealized_pnl == pytest.approx(100.0)
    assert ending.realized_pnl == 0.0
    assert ending.accounting_residual == 0.0
    assert report.mark_change_base == pytest.approx(100.0)
    assert report.complete is True


def test_mark_to_market_fails_closed_for_stale_quote(tmp_path: Path) -> None:
    beginning = _snapshot()
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(beginning)

    with pytest.raises(PortfolioPerformanceError, match="stale"):
        PortfolioMarkToMarketService(
            quote_provider=QuoteProvider(
                {"VTI": _quote(observed_at=AS_OF - timedelta(hours=1))}
            ),
            portfolio_store=store,
        ).mark(
            portfolio=beginning,
            profiles={"VTI": _profile()},
            as_of=AS_OF,
        )

    assert store.latest() == beginning


def test_non_base_cash_preserves_cost_and_tracks_fx_gain(tmp_path: Path) -> None:
    balance = CanonicalCurrencyBalance(
        currency="EUR",
        amount=1_000,
        fx_rate_to_base=1.10,
        updated_at=AS_OF - timedelta(minutes=5),
        fx_rate_source_identifier="fx:EURUSD:entry",
        cost_basis_base=1_100,
    )
    beginning = _snapshot(positions=(), cash=248_900.0, starting=250_000.0, balances=(balance,))
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(beginning)
    mark = CurrencyRateMark(
        currency="EUR",
        base_currency="USD",
        rate_to_base=1.20,
        observed_at=AS_OF,
        source_identifier="fx:EURUSD:mark",
    )

    PortfolioMarkToMarketService(
        quote_provider=QuoteProvider({}),
        currency_rate_provider=RateProvider({"EUR": mark}),
        portfolio_store=store,
    ).mark(portfolio=beginning, profiles={}, as_of=AS_OF)

    ending = store.latest()
    assert ending is not None
    assert ending.nav == pytest.approx(250_100.0)
    assert ending.cash_fx_pnl == pytest.approx(100.0)
    assert ending.total_pnl == pytest.approx(100.0)
    assert ending.accounting_residual == 0.0


def test_income_and_expenses_affect_performance_but_external_flows_do_not(tmp_path: Path) -> None:
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    beginning = _snapshot(positions=(), cash=250_000.0, starting=250_000.0)
    store.append(beginning)
    service = PortfolioCashFlowService(store)

    service.book(
        portfolio=beginning,
        event_identifier="cash-flow:dividend:1",
        kind=PortfolioCashFlowKind.DIVIDEND,
        amount_base=25.0,
        as_of=AS_OF,
        source_identifier="corporate-action:dividend:1",
        rationale="Qualified cash distribution",
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
    )
    dividend = store.latest()
    assert dividend is not None
    assert dividend.total_pnl == pytest.approx(25.0)
    assert dividend.non_trade_pnl == pytest.approx(25.0)

    service.book(
        portfolio=dividend,
        event_identifier="cash-flow:fee:1",
        kind=PortfolioCashFlowKind.FEE,
        amount_base=-5.0,
        as_of=AS_OF + timedelta(seconds=1),
        source_identifier="custody-fee:1",
        rationale="Paper custody charge",
    )
    after_fee = store.latest()
    assert after_fee is not None
    assert after_fee.total_pnl == pytest.approx(20.0)
    assert after_fee.non_trade_pnl == pytest.approx(20.0)

    service.book(
        portfolio=after_fee,
        event_identifier="cash-flow:contribution:1",
        kind=PortfolioCashFlowKind.CONTRIBUTION,
        amount_base=100.0,
        as_of=AS_OF + timedelta(seconds=2),
        source_identifier="external-flow:test",
        rationale="Controlled paper-capital contribution",
    )
    ending = store.latest()
    assert ending is not None
    assert ending.nav == pytest.approx(250_120.0)
    assert ending.net_external_flows == pytest.approx(100.0)
    assert ending.total_pnl == pytest.approx(20.0)
    assert ending.total_return == pytest.approx(20.0 / 250_000.0)
    assert ending.accounting_residual == 0.0





def test_accounting_migration_reconstructs_legacy_realized_pnl(tmp_path: Path) -> None:
    buy = CanonicalImplementationEvent(
        identifier="fill:buy:1",
        occurred_at=AS_OF - timedelta(days=2),
        action="buy",
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        venue="NYSEARCA",
        asset_class="us_etf",
        quantity=100,
        price=10,
        gross_amount=1_000,
        cost_amount=1,
        source_identifier="paper-fill:buy:1",
    )
    sell = CanonicalImplementationEvent(
        identifier="fill:sell:1",
        occurred_at=AS_OF - timedelta(days=1),
        action="sell",
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        venue="NYSEARCA",
        asset_class="us_etf",
        quantity=40,
        price=12,
        gross_amount=480,
        cost_amount=1,
        source_identifier="paper-fill:sell:1",
    )
    position = CanonicalPortfolioPosition(
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        venue="NYSEARCA",
        asset_class="us_etf",
        quantity=60,
        average_cost=10.01,
        mark_price=12,
        updated_at=AS_OF - timedelta(minutes=5),
    )
    legacy = CanonicalPortfolioSnapshot(
        identifier="portfolio:legacy-accounting",
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF - timedelta(minutes=5),
        starting_capital=250_000,
        cash_amount=249_478,
        positions=(position,),
        implementation_events=(buy, sell),
    )
    assert legacy.accounting_residual == pytest.approx(78.6)
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(legacy)

    report = PortfolioAccountingMigrationService(store).enrich(
        portfolio=legacy,
        as_of=AS_OF,
        source_identifier="average-cost-migration:v1",
    )

    ending = store.latest()
    assert ending is not None
    assert ending.realized_pnl == pytest.approx(78.6)
    assert ending.unrealized_pnl == pytest.approx(119.4)
    assert ending.total_pnl == pytest.approx(198.0)
    assert ending.accounting_residual == 0.0
    assert ending.implementation_events[-1].cost_basis_relieved_base == pytest.approx(400.4)
    assert report.enriched_sell_events == 1

def test_snapshot_history_reports_period_and_same_day_pnl(tmp_path: Path) -> None:
    beginning = _snapshot()
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(beginning)
    service = PortfolioMarkToMarketService(
        quote_provider=QuoteProvider({"VTI": _quote(last=12.0)}),
        portfolio_store=store,
    )
    service.mark(
        portfolio=beginning,
        profiles={"VTI": _profile()},
        as_of=AS_OF,
    )
    first_mark = store.latest()
    assert first_mark is not None
    second_time = AS_OF + timedelta(minutes=5)
    service = PortfolioMarkToMarketService(
        quote_provider=QuoteProvider(
            {"VTI": _quote(observed_at=second_time, last=13.0)}
        ),
        portfolio_store=store,
    )
    service.mark(
        portfolio=first_mark,
        profiles={"VTI": _profile()},
        as_of=second_time,
    )
    ending = store.latest()
    assert ending is not None

    details = snapshot_details(
        ending,
        history=store.history("COMPOUNDING"),
    )

    assert details["period_pnl"] == pytest.approx(50.0)
    assert details["day_pnl"] == pytest.approx(150.0)
    assert details["day_return"] == pytest.approx(150.0 / 250_000.0)

def test_share_split_preserves_market_value_cost_basis_and_pnl(tmp_path: Path) -> None:
    beginning = _snapshot()
    store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    store.append(beginning)

    adjustment = PortfolioPositionAdjustmentService(store).apply_split(
        portfolio=beginning,
        event_identifier="corporate-action:split:vti:1",
        symbol="VTI",
        instrument_identifier="instrument:us-etf:vti",
        split_ratio=2.0,
        as_of=AS_OF,
        source_identifier="issuer-action:vti:split",
        rationale="Two-for-one share split",
    )

    ending = store.latest()
    assert ending is not None
    position = ending.positions[0]
    assert position.quantity == pytest.approx(100.0)
    assert position.average_cost == pytest.approx(5.0)
    assert position.mark_price == pytest.approx(5.0)
    assert position.cost_basis == pytest.approx(500.0)
    assert position.market_value == pytest.approx(500.0)
    assert ending.total_pnl == beginning.total_pnl
    assert ending.accounting_residual == beginning.accounting_residual
    assert adjustment.current_quantity == pytest.approx(100.0)

def test_new_accounting_fields_are_backward_compatible() -> None:
    payload = snapshot_to_dict(_snapshot())
    for balance in payload["currency_balances"]:
        balance.pop("cost_basis_base", None)
        balance.pop("unrealized_fx_gain", None)
    for event in payload["implementation_events"]:
        for key in (
            "contract_multiplier",
            "cost_basis_relieved",
            "cost_basis_relieved_base",
            "realized_pnl",
            "realized_pnl_base",
            "non_trade_pnl_base",
            "external_flow_amount_base",
        ):
            event.pop(key, None)

    restored = snapshot_from_dict(payload)

    assert restored.total_pnl == 0.0
    assert restored.realized_pnl == 0.0
    assert restored.unrealized_pnl == 0.0
    assert restored.accounting_residual == 0.0
