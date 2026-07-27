from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from governance.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    SQLiteCertifiedEligibleUniverseStore,
)
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from portfolio.construction_api import (
    ConstructionStatus,
    ConstraintCheck,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.state import (
    SQLiteCanonicalPortfolioStore,
    ensure_canonical_portfolio_store,
)
from portfolio.execution import (
    MarketSession,
    MarketSessionStatus,
    PaperExecutionError,
    PaperExecutionIntegrityError,
    PaperExecutionOrchestrator,
    PaperExecutionPolicy,
    PaperExecutionStatus,
    PaperOrderStatus,
    PaperPortfolioState,
    PaperPosition,
    PaperQuote,
    SQLitePaperExecutionStore,
)


AS_OF = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)


class SessionProvider:
    def __init__(self, status: MarketSessionStatus = MarketSessionStatus.OPEN) -> None:
        self.status = status
        self.calls = 0

    def session(self, *, as_of: datetime, calendar_name: str) -> MarketSession:
        self.calls += 1
        return MarketSession(
            as_of=as_of,
            status=self.status,
            calendar_name=calendar_name,
            opened_at=as_of - timedelta(hours=1) if self.status is MarketSessionStatus.OPEN else None,
            closes_at=as_of + timedelta(hours=5) if self.status is MarketSessionStatus.OPEN else None,
        )


class QuoteProvider:
    def __init__(self, quotes: dict[str, PaperQuote]) -> None:
        self.values = quotes
        self.calls = 0

    def quotes(self, *, symbols: tuple[str, ...], as_of: datetime):
        self.calls += 1
        return {symbol: self.values[symbol] for symbol in symbols if symbol in self.values}


def quote(
    symbol: str,
    *,
    bid: float,
    ask: float,
    last: float,
    volume: float = 10_000_000.0,
    as_of: datetime = AS_OF,
    halted: bool = False,
) -> PaperQuote:
    return PaperQuote(
        symbol=symbol,
        as_of=as_of,
        bid=bid,
        ask=ask,
        last=last,
        available_dollar_volume=volume,
        halted=halted,
        source_identifier=f"quote:{symbol}:{as_of.isoformat()}",
    )


def portfolio() -> PaperPortfolioState:
    return PaperPortfolioState(
        identifier="portfolio:before",
        as_of=AS_OF - timedelta(minutes=1),
        cash_amount=20_000.0,
        positions=(
            PaperPosition(
                symbol="AAA",
                instrument_identifier="instrument:AAA",
                quantity=800.0,
                mark_price=100.0,
            ),
        ),
    )


def construction(*, status: ConstructionStatus = ConstructionStatus.FEASIBLE) -> PortfolioConstructionResult:
    trades = () if status is ConstructionStatus.NO_ACTION else (
        TradeProposal(
            symbol="AAA",
            side=TradeSide.SELL,
            from_weight=0.80,
            to_weight=0.60,
            trade_weight=0.20,
            estimated_cost_return=0.0002,
            reason="fund superior opportunity",
            funding_for=("BBB",),
        ),
        TradeProposal(
            symbol="BBB",
            side=TradeSide.BUY,
            from_weight=0.0,
            to_weight=0.20,
            trade_weight=0.20,
            estimated_cost_return=0.0003,
            reason="approved CIO allocation",
        ),
    )
    return PortfolioConstructionResult(
        request_identifier="construction:1",
        as_of=AS_OF - timedelta(minutes=2),
        status=status,
        policy_version="construction.v1",
        target_cash_weight=0.20 if status is not ConstructionStatus.NO_ACTION else 0.20,
        target_weights=(("AAA", 0.60), ("BBB", 0.20)) if status is not ConstructionStatus.NO_ACTION else (("AAA", 0.80),),
        trades=trades,
        turnover=0.40 if trades else 0.0,
        estimated_cost_return=0.0005 if trades else 0.0,
        expected_return_before=0.05,
        expected_return_after_cost=0.06,
        expected_return_improvement=0.01,
        constraints=(ConstraintCheck("cash", True, 0.20, 0.02, "cash is sufficient"),),
        blocks=(),
        eligible_universe_publication_identifier="eligible-universe:test",
        instrument_identifiers=(
            ()
            if not trades
            else (("AAA", "instrument:AAA"), ("BBB", "instrument:BBB"))
        ),
    )


def _universe_store(tmp_path) -> SQLiteCertifiedEligibleUniverseStore:
    store = SQLiteCertifiedEligibleUniverseStore(tmp_path / "eligible-universe.db")
    store.append(
        CertifiedEligibleUniversePublication(
            identifier="eligible-universe:test",
            published_at=AS_OF - timedelta(minutes=3),
            as_of=AS_OF - timedelta(minutes=2),
            knowledge_cutoff=AS_OF - timedelta(minutes=4),
            security_master_catalog_identifier="catalog:test",
            security_master_snapshot_identifier="snapshot:test",
            policy_version="recommendation-universe.v1",
            certification_identifier="certification:test",
            certification_state=EligibleUniverseCertificationState.APPROVED,
            certification_expires_at=AS_OF + timedelta(days=1),
            eligible_instrument_identifiers=(
                "instrument:AAA",
                "instrument:BBB",
            ),
            source_versions=(("security-master", "v1"),),
            model_versions=(("universe-policy", "v1"),),
        )
    )
    return store


def orchestrator(tmp_path, *, quotes=None, session=MarketSessionStatus.OPEN, policy=None, journal=True):
    session_provider = SessionProvider(session)
    quote_provider = QuoteProvider(
        quotes
        or {
            "AAA": quote("AAA", bid=99.0, ask=101.0, last=100.0),
            "BBB": quote("BBB", bid=49.0, ask=51.0, last=50.0),
        }
    )
    cio_journal = SQLiteCIOJournal(tmp_path / "cio.db") if journal else None
    ensure_canonical_portfolio_store(
        tmp_path / "canonical_portfolio.db",
        as_of=AS_OF - timedelta(days=1),
    )
    service = PaperExecutionOrchestrator(
        session_provider=session_provider,
        quote_provider=quote_provider,
        store=SQLitePaperExecutionStore(tmp_path / "paper.db"),
        universe_store=_universe_store(tmp_path),
        journal=cio_journal,
        portfolio_store=SQLiteCanonicalPortfolioStore(tmp_path / "canonical_portfolio.db"),
        portfolio_code="COMPOUNDING",
        policy=policy,
    )
    return service, session_provider, quote_provider, cio_journal


def test_sell_fills_before_dependent_buy_and_reconciles(tmp_path) -> None:
    service, _, _, journal = orchestrator(tmp_path)
    batch = service.execute(
        construction=construction(),
        decision_identifier="decision:1",
        portfolio=portfolio(),
        as_of=AS_OF,
    )

    assert batch.status is PaperExecutionStatus.COMPLETED
    assert [item.side for item in batch.fills] == [TradeSide.SELL, TradeSide.BUY]
    assert all(item.status is PaperOrderStatus.FILLED for item in batch.orders)
    assert batch.reconciliation is not None and batch.reconciliation.reconciled
    assert batch.ending_portfolio.quantity("AAA") == pytest.approx(600.0)
    assert batch.ending_portfolio.quantity("BBB") == pytest.approx(400.0)
    assert batch.ending_portfolio.cash_amount == pytest.approx(19_400.0)
    assert batch.ending_portfolio.nav == pytest.approx(99_400.0)
    assert len(journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)) == 2
    canonical = service.portfolio_store.latest("COMPOUNDING")
    assert canonical is not None
    assert canonical.cash_amount == pytest.approx(19_400.0)
    assert {item.symbol for item in canonical.positions} == {"AAA", "BBB"}
    assert {item.identifier for item in canonical.implementation_events} == {item.identifier for item in batch.fills}


def test_closed_market_holds_orders_without_quotes_or_fills(tmp_path) -> None:
    service, _, quote_provider, journal = orchestrator(tmp_path, session=MarketSessionStatus.CLOSED)
    batch = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    assert batch.status is PaperExecutionStatus.HELD
    assert quote_provider.calls == 0
    assert not batch.fills
    assert all(item.status is PaperOrderStatus.HELD for item in batch.orders)
    assert not journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)


def test_holiday_holds_orders(tmp_path) -> None:
    service, _, _, _ = orchestrator(tmp_path, session=MarketSessionStatus.HOLIDAY)
    batch = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    assert batch.status is PaperExecutionStatus.HELD


def test_partial_funding_sale_holds_dependent_buy_then_retry_completes(tmp_path) -> None:
    low_quotes = {
        "AAA": quote("AAA", bid=99.0, ask=101.0, last=100.0, volume=1_000.0),
        "BBB": quote("BBB", bid=49.0, ask=51.0, last=50.0),
    }
    service, _, provider, journal = orchestrator(tmp_path, quotes=low_quotes)
    first = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    assert first.status is PaperExecutionStatus.PARTIAL
    sell = next(item for item in first.orders if item.side is TradeSide.SELL)
    buy = next(item for item in first.orders if item.side is TradeSide.BUY)
    assert sell.status is PaperOrderStatus.PARTIALLY_FILLED
    assert buy.status is PaperOrderStatus.HELD
    assert len(first.fills) == 1

    provider.values["AAA"] = quote("AAA", bid=99.0, ask=101.0, last=100.0, as_of=AS_OF + timedelta(minutes=1))
    provider.values["BBB"] = quote("BBB", bid=49.0, ask=51.0, last=50.0, as_of=AS_OF + timedelta(minutes=1))
    second = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=first.ending_portfolio,
        as_of=AS_OF + timedelta(minutes=1),
    )
    assert second.status is PaperExecutionStatus.COMPLETED
    assert second.attempt_count == 2
    assert len(second.fills) == 3
    assert len(journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)) == 3


def test_stale_quote_rejects_sell_and_holds_funding_buy(tmp_path) -> None:
    quotes = {
        "AAA": quote("AAA", bid=99.0, ask=101.0, last=100.0, as_of=AS_OF - timedelta(minutes=10)),
        "BBB": quote("BBB", bid=49.0, ask=51.0, last=50.0),
    }
    service, _, _, _ = orchestrator(tmp_path, quotes=quotes)
    batch = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    assert batch.status is PaperExecutionStatus.PARTIAL
    assert next(item for item in batch.orders if item.symbol == "AAA").status is PaperOrderStatus.REJECTED
    assert next(item for item in batch.orders if item.symbol == "BBB").status is PaperOrderStatus.HELD
    assert not batch.fills


def test_halted_security_is_rejected(tmp_path) -> None:
    quotes = {
        "AAA": quote("AAA", bid=99.0, ask=101.0, last=100.0, halted=True),
        "BBB": quote("BBB", bid=49.0, ask=51.0, last=50.0),
    }
    service, _, _, _ = orchestrator(tmp_path, quotes=quotes)
    batch = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    assert next(item for item in batch.orders if item.symbol == "AAA").reason == "security is halted"


def test_no_action_completes_without_market_access(tmp_path) -> None:
    service, session_provider, quote_provider, journal = orchestrator(tmp_path)
    batch = service.execute(
        construction=construction(status=ConstructionStatus.NO_ACTION),
        decision_identifier="decision:1",
        portfolio=portfolio(),
        as_of=AS_OF,
    )
    assert batch.status is PaperExecutionStatus.NO_ACTION
    assert session_provider.calls == 0 and quote_provider.calls == 0
    assert batch.reconciliation is not None and batch.reconciliation.reconciled
    assert not journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)


def test_blocked_construction_is_rejected(tmp_path) -> None:
    service, _, _, _ = orchestrator(tmp_path)
    blocked = PortfolioConstructionResult(
        request_identifier="construction:blocked", as_of=AS_OF, status=ConstructionStatus.BLOCKED,
        policy_version="v1", target_cash_weight=0.20, target_weights=(("AAA", 0.80),), trades=(),
        turnover=0.0, estimated_cost_return=0.0, expected_return_before=0.0,
        expected_return_after_cost=0.0, expected_return_improvement=0.0, constraints=(), blocks=("blocked",),
    )
    with pytest.raises(PaperExecutionError, match="blocked construction"):
        service.execute(construction=blocked, decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF)


def test_exact_completed_replay_is_idempotent(tmp_path) -> None:
    service, _, provider, journal = orchestrator(tmp_path)
    first = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    calls = provider.calls
    second = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=first.ending_portfolio,
        as_of=AS_OF + timedelta(minutes=1),
    )
    assert second == first
    assert provider.calls == calls
    assert len(journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)) == 2


def test_open_orders_can_be_cancelled_immutably(tmp_path) -> None:
    service, _, _, _ = orchestrator(tmp_path, session=MarketSessionStatus.CLOSED)
    held = service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    cancelled = service.cancel_open_orders(
        batch_identifier=held.identifier, cancelled_at=AS_OF + timedelta(minutes=5), reason="end of day"
    )
    assert cancelled.status is PaperExecutionStatus.CANCELLED
    assert all(item.status is PaperOrderStatus.CANCELLED for item in cancelled.orders)
    assert service.cancel_open_orders(
        batch_identifier=held.identifier, cancelled_at=AS_OF + timedelta(minutes=6), reason="repeat"
    ) == cancelled


def test_store_is_append_only_and_detects_tampering(tmp_path) -> None:
    service, _, _, _ = orchestrator(tmp_path)
    service.execute(
        construction=construction(), decision_identifier="decision:1", portfolio=portfolio(), as_of=AS_OF
    )
    store = service.store
    assert store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE paper_execution_events SET payload_json = '{}' WHERE sequence = 1")
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER paper_execution_no_update")
        connection.execute("UPDATE paper_execution_events SET payload_json = '{}' WHERE sequence = 1")
        connection.commit()
    with pytest.raises(PaperExecutionIntegrityError):
        store.verify_integrity()


def test_unsupported_new_buy_is_rejected_at_execution_boundary(tmp_path) -> None:
    service, session_provider, quote_provider, _ = orchestrator(tmp_path)
    unsupported = PortfolioConstructionResult(
        request_identifier="construction:unsupported-buy",
        as_of=AS_OF - timedelta(minutes=2),
        status=ConstructionStatus.FEASIBLE,
        policy_version="construction.v1",
        target_cash_weight=0.90,
        target_weights=(("UNSUPPORTED", 0.10),),
        trades=(
            TradeProposal(
                symbol="UNSUPPORTED",
                side=TradeSide.BUY,
                from_weight=0.0,
                to_weight=0.10,
                trade_weight=0.10,
                estimated_cost_return=0.001,
                reason="manual unsupported allocation",
            ),
        ),
        turnover=0.10,
        estimated_cost_return=0.001,
        expected_return_before=0.05,
        expected_return_after_cost=0.06,
        expected_return_improvement=0.01,
        constraints=(),
        blocks=(),
        eligible_universe_publication_identifier="eligible-universe:test",
        instrument_identifiers=(("UNSUPPORTED", "instrument:UNSUPPORTED"),),
    )

    with pytest.raises(PaperExecutionError, match="not eligible for new"):
        service.execute(
            construction=unsupported,
            decision_identifier="decision:unsupported",
            portfolio=portfolio(),
            as_of=AS_OF,
        )

    assert session_provider.calls == 0
    assert quote_provider.calls == 0


def test_unsupported_owned_position_may_only_be_reduced(tmp_path) -> None:
    service, _, provider, _ = orchestrator(
        tmp_path,
        quotes={
            "LEGACY": quote(
                "LEGACY",
                bid=9.9,
                ask=10.1,
                last=10.0,
            )
        },
    )
    legacy_portfolio = PaperPortfolioState(
        identifier="portfolio:legacy",
        as_of=AS_OF - timedelta(minutes=1),
        cash_amount=90_000.0,
        positions=(
            PaperPosition(
                symbol="LEGACY",
                instrument_identifier="instrument:LEGACY",
                quantity=1_000.0,
                mark_price=10.0,
            ),
        ),
    )
    exit_construction = PortfolioConstructionResult(
        request_identifier="construction:legacy-exit",
        as_of=AS_OF - timedelta(minutes=2),
        status=ConstructionStatus.FEASIBLE,
        policy_version="construction.v1",
        target_cash_weight=1.0,
        target_weights=(),
        trades=(
            TradeProposal(
                symbol="LEGACY",
                side=TradeSide.SELL,
                from_weight=0.10,
                to_weight=0.0,
                trade_weight=0.10,
                estimated_cost_return=0.001,
                reason="exit no-longer-eligible holding",
            ),
        ),
        turnover=0.10,
        estimated_cost_return=0.001,
        expected_return_before=0.04,
        expected_return_after_cost=0.04,
        expected_return_improvement=0.0,
        constraints=(),
        blocks=(),
        eligible_universe_publication_identifier="eligible-universe:test",
        instrument_identifiers=(("LEGACY", "instrument:LEGACY"),),
    )

    batch = service.execute(
        construction=exit_construction,
        decision_identifier="decision:legacy-exit",
        portfolio=legacy_portfolio,
        as_of=AS_OF,
    )

    assert batch.status is PaperExecutionStatus.COMPLETED
    assert batch.ending_portfolio.positions == ()
    assert provider.calls == 1
    started = service.store.events(batch_identifier=batch.identifier)[0].payload
    eligibility = started["execution_eligibility"]
    assert eligibility["publication_identifier"] == "eligible-universe:test"
    assert eligibility["instrument_results"][0]["eligibility_result"] == "legacy_exit_only"


def test_execution_module_has_no_broker_or_network_authority() -> None:
    source = open("portfolio/execution.py", encoding="utf-8").read()
    for prohibited in ("requests.", "httpx.", "alpaca", "interactive_brokers", "submit_order", "broker_api"):
        assert prohibited not in source
