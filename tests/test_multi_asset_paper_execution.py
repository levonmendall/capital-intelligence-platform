"""Integration tests for crypto, FX, and global paper execution."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
from governance import TradingSessionModel
from portfolio import (
    CanonicalPortfolioSnapshot,
    InstrumentExecutionProfile,
    InstrumentSession,
    InstrumentSessionStatus,
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetOrderStatus,
    MultiAssetPaperExecutionOrchestrator,
    MultiAssetQuote,
    SQLiteCanonicalPortfolioStore,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.construction_api import (
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
        self.calls: list[str] = []

    def session(self, profile, *, as_of):
        self.calls.append(profile.symbol)
        return InstrumentSession(
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            session_model=profile.session_model,
            as_of=as_of,
            status=self.statuses.get(
                profile.symbol,
                InstrumentSessionStatus.OPEN,
            ),
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
    currency: str = "USD",
    session_model: TradingSessionModel | None = None,
    commission_bps: float = 0.0,
    maximum_position_weight: float = 0.20,
) -> InstrumentExecutionProfile:
    if session_model is None:
        session_model = {
            CandidateAssetClass.CRYPTO: TradingSessionModel.CONTINUOUS_24_7,
            CandidateAssetClass.FX: TradingSessionModel.CONTINUOUS_24_5,
            CandidateAssetClass.INTERNATIONAL_EQUITY: (
                TradingSessionModel.EXCHANGE_LOCAL
            ),
        }[asset_class]
    return InstrumentExecutionProfile(
        symbol=symbol,
        instrument_identifier=f"instrument:{asset_class.value}:{venue}:{symbol}",
        asset_class=asset_class,
        venue=venue,
        session_model=session_model,
        price_currency=currency,
        settlement_currency=currency,
        asset_class_approval_identifier=f"approval:{asset_class.value}:paper-v1",
        execution_certification_identifier=f"cert:execution:{asset_class.value}:v1",
        commission_bps=commission_bps,
        maximum_position_weight=maximum_position_weight,
    )


def _quote(
    profile: InstrumentExecutionProfile,
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
            f"fx:{profile.price_currency}USD" if profile.price_currency != "USD" else "fx:USDUSD"
        ),
        quote_certification_identifier=f"cert:quote:{profile.venue}:v1",
        halted=halted,
    )


def _construction(*trades: TradeProposal) -> PortfolioConstructionResult:
    return PortfolioConstructionResult(
        request_identifier="construction:multi-asset:1",
        as_of=AS_OF - timedelta(minutes=1),
        status=ConstructionStatus.APPROVED,
        policy_version="portfolio-construction.v1",
        target_cash_weight=0.8,
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


def _portfolio(identifier: str = "portfolio:beginning") -> CanonicalPortfolioSnapshot:
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="institutional",
        as_of=AS_OF - timedelta(minutes=1),
        starting_capital=100_000,
        cash_amount=100_000,
        positions=(),
        source_identifiers=("portfolio-source:test",),
    )


def _orchestrator(
    tmp_path: Path,
    session_provider: SessionProvider,
    quote_provider: QuoteProvider,
):
    portfolio_store = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    portfolio_store.append(_portfolio())
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
    )


def test_crypto_spot_buy_is_fractional_unlevered_and_reconciled(
    tmp_path: Path,
) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
        commission_bps=10,
    )
    quote = _quote(profile, bid=49_900, ask=50_100, last=50_000)
    orchestrator, portfolio_store, execution_store = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({profile.symbol: quote}),
    )

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:crypto:1",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.COMPLETED
    assert len(batch.fills) == 1
    fill = batch.fills[0]
    assert 0 < fill.quantity < 1
    assert fill.asset_class is CandidateAssetClass.CRYPTO
    assert fill.price_currency == "USD"
    assert batch.ending_snapshot.cash_amount >= 0
    assert batch.reconciliation.reconciled is True
    assert abs(batch.reconciliation.difference) <= 0.01
    position = batch.ending_snapshot.positions[0]
    assert position.instrument_identifier == profile.instrument_identifier
    assert position.asset_class == CandidateAssetClass.CRYPTO.value
    assert portfolio_store.latest("COMPOUNDING") == batch.ending_snapshot
    assert execution_store.latest_batch(batch.identifier) == batch


def test_global_equity_uses_local_price_and_point_in_time_fx(
    tmp_path: Path,
) -> None:
    profile = _profile(
        "SHEL",
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        venue="LSE",
        currency="GBP",
        commission_bps=5,
    )
    quote = _quote(profile, bid=25.90, ask=26.10, last=26.00, fx=1.30)
    orchestrator, _, _ = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({profile.symbol: quote}),
    )

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:global:1",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF,
    )

    fill = batch.fills[0]
    position = batch.ending_snapshot.positions[0]
    assert fill.fill_price_local == 26.10
    assert fill.fx_rate_to_base == 1.30
    assert fill.gross_amount_base == pytest.approx(
        fill.gross_amount_local * 1.30,
        abs=0.01,
    )
    assert position.price_currency == "GBP"
    assert position.settlement_currency == "GBP"
    assert position.average_cost_base is not None
    assert position.fx_rate_source_identifier == "fx:GBPUSD"
    assert batch.reconciliation.reconciled is True


def test_closed_fx_session_holds_without_requesting_a_quote(tmp_path: Path) -> None:
    profile = _profile(
        "EURUSD",
        CandidateAssetClass.FX,
        venue="EBS",
    )
    sessions = SessionProvider(
        {profile.symbol: InstrumentSessionStatus.CLOSED}
    )
    quotes = QuoteProvider({})
    orchestrator, _, _ = _orchestrator(tmp_path, sessions, quotes)

    batch = orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:fx:closed",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.HELD
    assert batch.fills == ()
    assert batch.order_results[0].status is MultiAssetOrderStatus.HELD
    assert quotes.calls == []
    assert batch.ending_snapshot.identifier.endswith("attempt:1")
    assert batch.ending_snapshot.nav == _portfolio().nav


def test_mixed_global_sessions_create_a_reconciled_partial_batch(
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
        currency="GBP",
    )
    sessions = SessionProvider(
        {global_equity.symbol: InstrumentSessionStatus.HOLIDAY}
    )
    quote_provider = QuoteProvider(
        {crypto.symbol: _quote(crypto, bid=49_900, ask=50_100, last=50_000)}
    )
    orchestrator, _, _ = _orchestrator(tmp_path, sessions, quote_provider)

    batch = orchestrator.execute(
        construction=_construction(
            _buy(crypto.symbol, 0.05),
            _buy(global_equity.symbol, 0.05),
        ),
        decision_identifier="decision:mixed:1",
        portfolio=_portfolio(),
        profiles=(crypto, global_equity),
        as_of=AS_OF,
    )

    assert batch.status is MultiAssetExecutionStatus.PARTIAL
    assert len(batch.fills) == 1
    assert {item.status for item in batch.order_results} == {
        MultiAssetOrderStatus.FILLED,
        MultiAssetOrderStatus.HELD,
    }
    assert quote_provider.calls == ((crypto.symbol,),)
    assert batch.reconciliation.reconciled is True


def test_stale_or_future_known_quote_and_fx_fail_closed(tmp_path: Path) -> None:
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
    orchestrator, _, _ = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({profile.symbol: stale}),
    )
    with pytest.raises(MultiAssetExecutionError, match="stale"):
        orchestrator.execute(
            construction=_construction(_buy(profile.symbol)),
            decision_identifier="decision:stale",
            portfolio=_portfolio(),
            profiles=(profile,),
            as_of=AS_OF,
        )

    future = _quote(
        profile,
        bid=49_900,
        ask=50_100,
        last=50_000,
        observed_at=AS_OF + timedelta(seconds=1),
    )
    orchestrator2, _, _ = _orchestrator(
        tmp_path / "future",
        SessionProvider(),
        QuoteProvider({profile.symbol: future}),
    )
    with pytest.raises(MultiAssetExecutionError, match="future-known"):
        orchestrator2.execute(
            construction=_construction(_buy(profile.symbol)),
            decision_identifier="decision:future",
            portfolio=_portfolio(),
            profiles=(profile,),
            as_of=AS_OF,
        )


def test_exact_profile_and_quote_identity_prevent_substitution(
    tmp_path: Path,
) -> None:
    crypto = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    fx = _profile("EURUSD", CandidateAssetClass.FX, venue="EBS")
    orchestrator, _, _ = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider({crypto.symbol: _quote(crypto, bid=1, ask=1, last=1)}),
    )

    with pytest.raises(MultiAssetExecutionError, match="exactly match"):
        orchestrator.execute(
            construction=_construction(_buy(crypto.symbol)),
            decision_identifier="decision:coverage",
            portfolio=_portfolio(),
            profiles=(crypto, fx),
            as_of=AS_OF,
        )


def test_expanded_execution_profile_prohibits_missing_approval_and_leverage() -> None:
    with pytest.raises(ValueError, match="approval identifier"):
        InstrumentExecutionProfile(
            symbol="BTC-USD",
            instrument_identifier="instrument:btc",
            asset_class=CandidateAssetClass.CRYPTO,
            venue="COINBASE",
            session_model=TradingSessionModel.CONTINUOUS_24_7,
            price_currency="USD",
            settlement_currency="USD",
            execution_certification_identifier="cert:execution:crypto",
        )

    with pytest.raises(ValueError, match="prohibits leveraged"):
        InstrumentExecutionProfile(
            symbol="EURUSD",
            instrument_identifier="instrument:eurusd",
            asset_class=CandidateAssetClass.FX,
            venue="EBS",
            session_model=TradingSessionModel.CONTINUOUS_24_5,
            price_currency="USD",
            settlement_currency="USD",
            asset_class_approval_identifier="approval:fx",
            execution_certification_identifier="cert:execution:fx",
            notional_multiplier=10.0,
        )


def test_held_batch_retries_from_same_state_and_completed_replay_is_idempotent(
    tmp_path: Path,
) -> None:
    profile = _profile(
        "EURUSD",
        CandidateAssetClass.FX,
        venue="EBS",
    )
    sessions = SessionProvider(
        {profile.symbol: InstrumentSessionStatus.CLOSED}
    )
    quotes = QuoteProvider(
        {profile.symbol: _quote(profile, bid=1.08, ask=1.081, last=1.0805)}
    )
    orchestrator, _, store = _orchestrator(tmp_path, sessions, quotes)
    construction = _construction(_buy(profile.symbol))

    held = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:fx:retry",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF,
    )
    assert held.status is MultiAssetExecutionStatus.HELD

    sessions.statuses[profile.symbol] = InstrumentSessionStatus.OPEN
    completed = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:fx:retry",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF + timedelta(minutes=1),
    )
    assert completed.attempt == 2
    assert completed.status is MultiAssetExecutionStatus.COMPLETED
    assert completed.reconciliation.reconciled is True

    replay = orchestrator.execute(
        construction=construction,
        decision_identifier="decision:fx:retry",
        portfolio=completed.ending_snapshot,
        profiles=(profile,),
        as_of=AS_OF + timedelta(minutes=2),
    )
    assert replay == completed
    assert store.verify_integrity()


def test_multi_asset_execution_history_is_append_only(tmp_path: Path) -> None:
    profile = _profile(
        "BTC-USD",
        CandidateAssetClass.CRYPTO,
        venue="COINBASE",
    )
    orchestrator, _, store = _orchestrator(
        tmp_path,
        SessionProvider(),
        QuoteProvider(
            {profile.symbol: _quote(profile, bid=49_900, ask=50_100, last=50_000)}
        ),
    )
    orchestrator.execute(
        construction=_construction(_buy(profile.symbol)),
        decision_identifier="decision:append-only",
        portfolio=_portfolio(),
        profiles=(profile,),
        as_of=AS_OF,
    )

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE multi_asset_paper_execution_events SET payload_json = '{}' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM multi_asset_paper_execution_events")
