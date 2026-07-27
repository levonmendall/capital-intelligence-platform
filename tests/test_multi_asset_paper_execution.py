"""Integration tests for crypto, FX, and global paper execution."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from governance import AssetClassApprovalState, TradingSessionModel
from portfolio import (
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    InstrumentSession,
    InstrumentSessionStatus,
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetInstrumentProfile,
    MultiAssetOrderStatus,
    MultiAssetPaperExecutionOrchestrator,
    MultiAssetQuote,
    SQLiteCanonicalPortfolioStore,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.construction_models import (
    ConstructionStatus,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)


class SessionProvider:
    def __init__(self, statuses=None) -> None:
        self.statuses = statuses or {}
        self.calls: list[tuple[str, TradingSessionModel]] = []

    def session(self, profile, *, session_model, as_of):
        self.calls.append((profile.symbol, session_model))
        return InstrumentSession(
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            session_model=session_model,
            as_of=as_of,
            status=self.statuses.get(profile.symbol, InstrumentSessionStatus.OPEN),
            source_identifier=f"session:{profile.venue}:{as_of.isoformat()}",
        )


class QuoteProvider:
    def __init__(self, quotes) -> None:
        self.values = dict(quotes)
        self.calls: list[tuple[str, ...]] = []

    def quotes(self, profiles, *, as_of):
        symbols = tuple(item.symbol for item in profiles)
        self.calls.append(symbols)
        return {symbol: self.values[symbol] for symbol in symbols}


def _profile(
    symbol: str,
    asset_class: CandidateAssetClass,
    *,
    venue: str,
    country_code: str = "GLOBAL",
    currency: str = "USD",
    approval_state: AssetClassApprovalState = AssetClassApprovalState.PAPER_ELIGIBLE,
    unlevered: bool = True,
    spot_only: bool = True,
) -> MultiAssetInstrumentProfile:
    return MultiAssetInstrumentProfile(
        symbol=symbol,
        instrument_identifier=f"instrument:{asset_class.value}:{venue}:{symbol}",
        asset_class=asset_class,
        venue=venue,
        country_code=country_code,
        price_currency=currency,
        settlement_currency=currency,
        approval_identifier=f"approval:{asset_class.value}:paper-v1",
        approval_state=approval_state,
        unlevered=unlevered,
        spot_only=spot_only,
        custody_settlement_identifier=f"custody:{asset_class.value}:v1",
        execution_model_version=f"execution:{asset_class.value}:v1",
    )


def _quote(
    profile: MultiAssetInstrumentProfile,
    *,
    bid: float,
    ask: float,
    last: float,
    fx: float = 1.0,
    observed_at: datetime = AS_OF,
    available_base_notional: float = 10_000_000,
    halted: bool = False,
) -> MultiAssetQuote:
    return MultiAssetQuote(
        symbol=profile.symbol,
        instrument_identifier=profile.instrument_identifier,
        venue=profile.venue,
        observed_at=observed_at,
        bid=bid,
        ask=ask,
        last=last,
        available_base_notional=available_base_notional,
        price_currency=profile.price_currency,
        fx_rate_to_base=fx,
        fx_observed_at=observed_at,
        quote_source_identifier=f"quote:{profile.venue}:{profile.symbol}",
        fx_source_identifier=(
            f"fx:{profile.price_currency}USD"
            if profile.price_currency != "USD"
            else "fx:USDUSD"
        ),
        quote_certification_identifier=f"cert:quote:{profile.venue}:v1",
        halted=halted,
    )


def _buy(symbol: str, weight: float = 0.10) -> TradeProposal:
    return TradeProposal(
        symbol=symbol,
        side=TradeSide.BUY,
        from_weight=0.0,
        to_weight=weight,
        trade_weight=weight,
        estimated_cost_return=0.001,
        reason="qualified superior use of capital",
    )


def _construction(*trades: TradeProposal) -> PortfolioConstructionResult:
    return PortfolioConstructionResult(
        request_identifier="construction:multi-asset:1",
        as_of=AS_OF - timedelta(minutes=1),
        status=ConstructionStatus.FEASIBLE,
        policy_version="portfolio-construction.v1",
        target_cash_weight=round(1.0 - sum(item.to_weight for item in trades), 8),
        target_weights=tuple((item.symbol, item.to_weight) for item in trades),
        trades=tuple(trades),
        turnover=sum(item.trade_weight for item in trades),
        estimated_cost_return=0.001,
        expected_return_before=0.08,
        expected_return_after_cost=0.079,
        expected_return_improvement=0.02,
        constraints=(),
        blocks=(),
    )


def _portfolio(
    identifier: str = "portfolio:beginning",
    *,
    positions: tuple[CanonicalPortfolioPosition, ...] = (),
    cash: float = 100_000,
) -> CanonicalPortfolioSnapshot:
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF - timedelta(minutes=1),
        starting_capital=250_000,
        cash_amount=cash,
        positions=positions,
        source_identifiers=("portfolio-source:test",),
    )


def _orchestrator(
    tmp_path: Path,
    session_provider: SessionProvider,
    quote_provider: QuoteProvider,
    portfolio: CanonicalPortfolioSnapshot | None = None,
):
    state = portfolio or _portfolio()
    portfolio_store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    portfolio_store.append(state)
    execution_store = SQLiteMultiAssetPaperExecutionStore(
        tmp_path / "multi-asset-execution.db"
    )
    return (
        MultiAssetPaperExecutionOrchestrator(
            session_provider=session_provider,
            quote_provider=quote_provider,
            store=execution_store,
            portfolio_store=portfolio_store,
        ),
        portfolio_store,
        execution_store,
        state,
    )


def test_crypto_spot_buy_is_fractional_unlevered_and_reconciled(
    tmp_path: Path,
) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    quote = _quote(profile, bid=49_900, ask=50_100, last=50_000)
    sessions = SessionProvider()
    orchestrator, portfolio_store, execution_store, portfolio = _orchestrator(
        tmp_path,
        sessions,
        QuoteProvider({profile.symbol: quote}),
    )

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:crypto:1",
        portfolio=portfolio,
        profiles={profile.symbol: profile},
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.COMPLETED
    assert len(batch.fills) == 1
    fill = batch.fills[0]
    assert 0 < fill.quantity < 1
    assert fill.asset_class is CandidateAssetClass.CRYPTO
    assert fill.approval_identifier == profile.approval_identifier
    assert fill.execution_model_version == profile.execution_model_version
    assert batch.ending_snapshot.cash_amount >= 0
    assert batch.reconciliation.reconciled is True
    assert abs(batch.reconciliation.difference) <= 0.01
    position = batch.ending_snapshot.positions[0]
    assert position.instrument_identifier == profile.instrument_identifier
    assert position.asset_class == CandidateAssetClass.CRYPTO.value
    assert sessions.calls == [
        (profile.symbol, TradingSessionModel.CONTINUOUS_24_7)
    ]
    assert portfolio_store.latest("COMPOUNDING") == batch.ending_snapshot
    assert execution_store.latest_batch(batch.identifier) == batch


def test_global_equity_preserves_local_price_and_point_in_time_fx(
    tmp_path: Path,
) -> None:
    profile = _profile(
        "SHEL",
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        venue="LSE",
        country_code="GB",
        currency="GBP",
    )
    quote = _quote(profile, bid=10.0, ask=10.0, last=10.0, fx=1.25)
    sessions = SessionProvider()
    orchestrator, _, _, portfolio = _orchestrator(
        tmp_path,
        sessions,
        QuoteProvider({profile.symbol: quote}),
    )

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol, 0.05)),
        decision_identifier="decision:global:1",
        portfolio=portfolio,
        profiles={profile.symbol: profile},
        as_of=AS_OF,
    )

    fill = batch.fills[0]
    position = batch.ending_snapshot.positions[0]
    assert fill.quantity == 400
    assert fill.gross_amount_local == 4_000
    assert fill.gross_amount_base == 5_000
    assert position.price_currency == "GBP"
    assert position.settlement_currency == "GBP"
    assert position.average_cost_base is not None
    assert position.fx_rate_source_identifier == "fx:GBPUSD"
    assert batch.reconciliation.reconciled is True
    assert sessions.calls == [
        (profile.symbol, TradingSessionModel.EXCHANGE_LOCAL)
    ]


def test_closed_fx_session_holds_without_requesting_quote(tmp_path: Path) -> None:
    profile = _profile("EURUSD", CandidateAssetClass.FX, venue="EBS")
    sessions = SessionProvider(
        {profile.symbol: InstrumentSessionStatus.CLOSED}
    )
    quotes = QuoteProvider({})
    orchestrator, _, _, portfolio = _orchestrator(tmp_path, sessions, quotes)

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:fx:closed",
        portfolio=portfolio,
        profiles={profile.symbol: profile},
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.HELD
    assert batch.fills == ()
    assert batch.order_results[0].status is MultiAssetOrderStatus.HELD
    assert batch.ending_snapshot == portfolio
    assert quotes.calls == []
    assert sessions.calls == [
        (profile.symbol, TradingSessionModel.CONTINUOUS_24_5)
    ]


def test_mixed_market_retry_does_not_duplicate_completed_fill(
    tmp_path: Path,
) -> None:
    crypto = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    global_equity = _profile(
        "SHEL",
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        venue="LSE",
        country_code="GB",
        currency="GBP",
    )
    sessions = SessionProvider(
        {global_equity.symbol: InstrumentSessionStatus.HOLIDAY}
    )
    quotes = QuoteProvider(
        {
            crypto.symbol: _quote(
                crypto,
                bid=50_000,
                ask=50_000,
                last=50_000,
            ),
            global_equity.symbol: _quote(
                global_equity,
                bid=10,
                ask=10,
                last=10,
                fx=1.25,
                observed_at=AS_OF + timedelta(minutes=1),
            ),
        }
    )
    orchestrator, _, store, portfolio = _orchestrator(
        tmp_path,
        sessions,
        quotes,
    )
    construction = _construction(
        _buy(crypto.symbol, 0.05),
        _buy(global_equity.symbol, 0.05),
    )
    profiles = {
        crypto.symbol: crypto,
        global_equity.symbol: global_equity,
    }

    first = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:mixed:1",
        portfolio=portfolio,
        profiles=profiles,
        as_of=AS_OF,
    )
    assert first.status is MultiAssetExecutionStatus.PARTIAL
    assert len(first.fills) == 1
    crypto_fill_id = first.fills[0].identifier

    sessions.statuses[global_equity.symbol] = InstrumentSessionStatus.OPEN
    second = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:mixed:1",
        portfolio=first.ending_snapshot,
        profiles=profiles,
        as_of=AS_OF + timedelta(minutes=1),
    )

    assert second.status is MultiAssetExecutionStatus.COMPLETED
    assert second.attempt == 2
    assert len(second.fills) == 2
    assert [item.identifier for item in second.fills].count(crypto_fill_id) == 1
    assert quotes.calls == [
        (crypto.symbol,),
        (global_equity.symbol,),
    ]
    assert second.reconciliation.reconciled is True

    replay = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:mixed:1",
        portfolio=second.ending_snapshot,
        profiles=profiles,
        as_of=AS_OF + timedelta(minutes=2),
    )
    assert replay == second
    assert store.verify_integrity()


def test_stale_and_future_known_quote_evidence_fail_closed(tmp_path: Path) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    stale = _quote(
        profile,
        bid=49_900,
        ask=50_100,
        last=50_000,
        observed_at=AS_OF - timedelta(minutes=6),
    )
    orchestrator, _, _, portfolio = _orchestrator(
        tmp_path / "stale",
        SessionProvider(),
        QuoteProvider({profile.symbol: stale}),
    )
    with pytest.raises(MultiAssetExecutionError, match="stale"):
        orchestrator.execute(
            construction=_construction(_buy(profile.symbol)),
            decision_identifier="decision:stale",
            portfolio=portfolio,
            profiles={profile.symbol: profile},
            as_of=AS_OF,
        )

    future = _quote(
        profile,
        bid=49_900,
        ask=50_100,
        last=50_000,
        observed_at=AS_OF + timedelta(seconds=1),
    )
    orchestrator2, _, _, portfolio2 = _orchestrator(
        tmp_path / "future",
        SessionProvider(),
        QuoteProvider({profile.symbol: future}),
    )
    with pytest.raises(MultiAssetExecutionError, match="future-known"):
        orchestrator2.execute(
            construction=_construction(_buy(profile.symbol)),
            decision_identifier="decision:future",
            portfolio=portfolio2,
            profiles={profile.symbol: profile},
            as_of=AS_OF,
        )


def test_profile_coverage_approval_and_unlevered_spot_are_enforced(
    tmp_path: Path,
) -> None:
    crypto = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    fx = _profile("EURUSD", CandidateAssetClass.FX, venue="EBS")
    orchestrator, _, _, portfolio = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({}),
    )
    with pytest.raises(MultiAssetExecutionError, match="exactly match"):
        orchestrator.execute(
            construction=_construction(_buy(crypto.symbol)),
            decision_identifier="decision:coverage",
            portfolio=portfolio,
            profiles={crypto.symbol: crypto, fx.symbol: fx},
            as_of=AS_OF,
        )

    research_only = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
        approval_state=AssetClassApprovalState.RESEARCH_APPROVED,
    )
    with pytest.raises(MultiAssetExecutionError, match="paper_eligible"):
        orchestrator.execute(
            construction=_construction(_buy(research_only.symbol)),
            decision_identifier="decision:approval",
            portfolio=portfolio,
            profiles={research_only.symbol: research_only},
            as_of=AS_OF,
        )

    leveraged = _profile(
        "EURUSD",
        CandidateAssetClass.FX,
        venue="EBS",
        unlevered=False,
    )
    with pytest.raises(MultiAssetExecutionError, match="unlevered spot"):
        orchestrator.execute(
            construction=_construction(_buy(leveraged.symbol)),
            decision_identifier="decision:leverage",
            portfolio=portfolio,
            profiles={leveraged.symbol: leveraged},
            as_of=AS_OF,
        )


def test_global_sell_uses_owned_identity_and_reconciles(tmp_path: Path) -> None:
    profile = _profile(
        "SHEL",
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        venue="LSE",
        country_code="GB",
        currency="GBP",
    )
    position = CanonicalPortfolioPosition(
        symbol="SHEL",
        instrument_identifier=profile.instrument_identifier,
        venue="LSE",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY.value,
        quantity=400,
        average_cost=9.0,
        average_cost_base=11.25,
        mark_price=10.0,
        updated_at=AS_OF - timedelta(minutes=1),
        price_currency="GBP",
        settlement_currency="GBP",
        fx_rate_to_base=1.25,
        fx_rate_observed_at=AS_OF - timedelta(minutes=1),
        fx_rate_source_identifier="fx:GBPUSD:prior",
    )
    portfolio = _portfolio(positions=(position,), cash=95_000)
    quote = _quote(profile, bid=10, ask=10, last=10, fx=1.25)
    orchestrator, _, _, _ = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({profile.symbol: quote}),
        portfolio,
    )
    sell = TradeProposal(
        symbol=profile.symbol,
        side=TradeSide.SELL,
        from_weight=0.05,
        to_weight=0.0,
        trade_weight=0.05,
        estimated_cost_return=0.001,
        reason="fund superior opportunity",
    )
    construction = PortfolioConstructionResult(
        request_identifier="construction:global-sell:1",
        as_of=AS_OF - timedelta(minutes=1),
        status=ConstructionStatus.FEASIBLE,
        policy_version="portfolio-construction.v1",
        target_cash_weight=1.0,
        target_weights=(),
        trades=(sell,),
        turnover=0.05,
        estimated_cost_return=0.001,
        expected_return_before=0.06,
        expected_return_after_cost=0.059,
        expected_return_improvement=0.01,
        constraints=(),
        blocks=(),
    )

    batch = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:global-sell",
        portfolio=portfolio,
        profiles={profile.symbol: profile},
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.COMPLETED
    assert batch.ending_snapshot.positions == ()
    assert batch.ending_snapshot.cash_amount < 100_000
    assert batch.ending_snapshot.cash_amount > 99_990
    assert batch.reconciliation.reconciled is True


def test_multi_asset_execution_history_is_append_only(tmp_path: Path) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    orchestrator, _, store, portfolio = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider(
            {
                profile.symbol: _quote(
                    profile,
                    bid=50_000,
                    ask=50_000,
                    last=50_000,
                )
            }
        ),
    )
    orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:append-only",
        portfolio=portfolio,
        profiles={profile.symbol: profile},
        as_of=AS_OF,
    )

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE multi_asset_paper_execution_events "
                "SET payload_json = '{}' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM multi_asset_paper_execution_events")
