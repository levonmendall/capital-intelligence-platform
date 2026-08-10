from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from opportunity.relative_value import (
    RelativeValueCandidateExpression,
    RelativeValueExpressionType,
    RelativeValueLeg,
    RelativeValueLegSide,
)
from portfolio.construction_models import TradeSide
from portfolio.multi_asset_execution import (
    MultiAssetExecutionStatus,
    MultiAssetOrderStatus,
)
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore
from portfolio import atomic_relative_value_execution as module
from portfolio.atomic_relative_value_execution import (
    AtomicRelativeValueExecutionAttempt,
    AtomicRelativeValueExecutionError,
    AtomicRelativeValueExecutionStatus,
    AtomicRelativeValuePaperExecutionOrchestrator,
    RelativeValuePaperLegImplementation,
    SQLiteAtomicRelativeValueExecutionStore,
)


NOW = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)


def _snapshot(identifier: str = "portfolio:before") -> CanonicalPortfolioSnapshot:
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code="COMPOUNDING",
        display_name="Compounding",
        constraint_profile="COMPOUNDING",
        as_of=NOW,
        starting_capital=250_000.0,
        cash_amount=250_000.0,
        positions=(),
        source_identifiers=("test",),
    )


def _expression(*, certified: bool = True) -> RelativeValueCandidateExpression:
    return RelativeValueCandidateExpression(
        identifier="rv:pair:1",
        as_of=NOW,
        expression_type=RelativeValueExpressionType.PAIR,
        legs=(
            RelativeValueLeg(
                instrument_identifier="inst:long",
                symbol="LONG",
                side=RelativeValueLegSide.LONG,
                gross_weight=0.10,
                expected_return=0.12,
                implementation_cost_return=0.001,
                financing_return=0.0,
                liquidity_score=0.9,
                decision_ready=True,
                paper_execution_certified=True,
                evidence_identifiers=("long:evidence",),
            ),
            RelativeValueLeg(
                instrument_identifier="inst:short",
                symbol="SHORT",
                side=RelativeValueLegSide.SHORT,
                gross_weight=0.10,
                expected_return=-0.08,
                implementation_cost_return=0.001,
                financing_return=-0.002,
                liquidity_score=0.9,
                decision_ready=True,
                paper_execution_certified=True,
                evidence_identifiers=("short:evidence",),
            ),
        ),
        thesis="Long relative winner and hedge with defined-risk inverse implementation.",
        base_case_return=0.08,
        bull_case_return=0.15,
        bear_case_return=-0.05,
        base_probability=0.6,
        bull_probability=0.2,
        bear_probability=0.2,
        maximum_loss_return=-0.15,
        evidence_identifiers=("rv:evidence",),
        model_versions=("rv-test-v1",),
        atomic_paper_execution_certified=certified,
    )


def _construction():
    return SimpleNamespace(
        request_identifier="construction:1",
        as_of=NOW,
        trades=(
            SimpleNamespace(symbol="LONGETF", side=TradeSide.BUY, trade_weight=0.10),
            SimpleNamespace(symbol="INVETF", side=TradeSide.BUY, trade_weight=0.10),
        ),
    )


def _implementations():
    return (
        RelativeValuePaperLegImplementation(
            leg_instrument_identifier="inst:long",
            leg_symbol="LONG",
            economic_side=RelativeValueLegSide.LONG,
            execution_instrument_identifier="exec:long",
            execution_symbol="LONGETF",
            execution_side=TradeSide.BUY,
            implementation_certification_identifier="cert:long",
            evidence_identifiers=("impl:long",),
        ),
        RelativeValuePaperLegImplementation(
            leg_instrument_identifier="inst:short",
            leg_symbol="SHORT",
            economic_side=RelativeValueLegSide.SHORT,
            execution_instrument_identifier="exec:inverse",
            execution_symbol="INVETF",
            execution_side=TradeSide.BUY,
            implementation_certification_identifier="cert:inverse",
            evidence_identifiers=("impl:inverse",),
            defined_risk_short_implementation=True,
        ),
    )


def _profiles():
    return {
        "LONGETF": SimpleNamespace(
            instrument_identifier="exec:long", defined_risk=False
        ),
        "INVETF": SimpleNamespace(
            instrument_identifier="exec:inverse", defined_risk=True
        ),
    }


class _DummyExecutor:
    next_batch = None

    def __init__(
        self,
        *,
        session_provider=None,
        quote_provider=None,
        store=None,
        portfolio_store=None,
        universe_store=None,
        policy=None,
    ):
        self.session_provider = session_provider
        self.quote_provider = quote_provider
        self.store = store
        self.portfolio_store = portfolio_store
        self.universe_store = universe_store
        self.policy = policy or SimpleNamespace(reconciliation_tolerance=1e-6)

    def execute(self, **kwargs):
        del kwargs
        if self.next_batch is None:
            raise AssertionError("test batch was not configured")
        return self.next_batch


def _batch(snapshot: CanonicalPortfolioSnapshot, *, partial: bool = False):
    orders = (
        SimpleNamespace(
            symbol="LONGETF",
            status=(
                MultiAssetOrderStatus.PARTIALLY_FILLED
                if partial
                else MultiAssetOrderStatus.FILLED
            ),
            requested_base_amount=25_000.0,
            filled_base_amount=12_500.0 if partial else 25_000.0,
            reason="partial" if partial else "filled",
        ),
        SimpleNamespace(
            symbol="INVETF",
            status=MultiAssetOrderStatus.FILLED,
            requested_base_amount=25_000.0,
            filled_base_amount=25_000.0,
            reason="filled",
        ),
    )
    return SimpleNamespace(
        identifier="batch:1",
        status=(MultiAssetExecutionStatus.PARTIAL if partial else MultiAssetExecutionStatus.COMPLETED),
        order_results=orders,
        reconciliation=SimpleNamespace(
            reconciled=not partial, accounting_reconciled=not partial
        ),
        ending_snapshot=snapshot,
    )


def _orchestrator(tmp_path, monkeypatch, *, batch):
    monkeypatch.setattr(module, "MultiAssetPaperExecutionOrchestrator", _DummyExecutor)
    real_portfolio = SQLiteCanonicalPortfolioStore(tmp_path / "portfolio.db")
    beginning = _snapshot()
    real_portfolio.append(beginning)
    base = _DummyExecutor(
        portfolio_store=real_portfolio,
        universe_store=object(),
        policy=SimpleNamespace(reconciliation_tolerance=1e-6),
    )
    _DummyExecutor.next_batch = batch
    store = SQLiteAtomicRelativeValueExecutionStore(tmp_path / "atomic.db")
    return (
        AtomicRelativeValuePaperExecutionOrchestrator(
            base_executor=base,
            store=store,
        ),
        beginning,
        real_portfolio,
        store,
    )


def test_atomic_expression_commits_one_canonical_snapshot(tmp_path, monkeypatch):
    simulated_end = _snapshot("temp:end")
    orchestrator, beginning, real_portfolio, store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(simulated_end)
    )
    result = orchestrator.execute(
        expression=_expression(),
        construction=_construction(),
        decision_identifier="decision:1",
        portfolio=beginning,
        profiles=_profiles(),
        implementations=_implementations(),
        as_of=NOW,
    )
    assert result.status is AtomicRelativeValueExecutionStatus.COMPLETED
    assert result.canonical_state_changed is True
    assert real_portfolio.latest("COMPOUNDING").identifier == result.ending_snapshot_identifier
    assert result.ending_snapshot_identifier != beginning.identifier
    assert store.verify_integrity() is True


def test_partial_leg_discards_all_provisional_fills(tmp_path, monkeypatch):
    orchestrator, beginning, real_portfolio, _store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(_snapshot("temp:partial"), partial=True)
    )
    result = orchestrator.execute(
        expression=_expression(),
        construction=_construction(),
        decision_identifier="decision:1",
        portfolio=beginning,
        profiles=_profiles(),
        implementations=_implementations(),
        as_of=NOW,
    )
    assert result.status is AtomicRelativeValueExecutionStatus.FAILED
    assert result.canonical_state_changed is False
    assert real_portfolio.latest("COMPOUNDING").identifier == beginning.identifier


def test_naked_short_sell_is_rejected_before_simulation(tmp_path, monkeypatch):
    orchestrator, beginning, _real_portfolio, _store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(_snapshot("temp:end"))
    )
    construction = SimpleNamespace(
        request_identifier="construction:short",
        as_of=NOW,
        trades=(
            SimpleNamespace(symbol="LONGETF", side=TradeSide.BUY, trade_weight=0.10),
            SimpleNamespace(symbol="SHORTETF", side=TradeSide.SELL, trade_weight=0.10),
        ),
    )
    implementations = (
        _implementations()[0],
        RelativeValuePaperLegImplementation(
            leg_instrument_identifier="inst:short",
            leg_symbol="SHORT",
            economic_side=RelativeValueLegSide.SHORT,
            execution_instrument_identifier="exec:short",
            execution_symbol="SHORTETF",
            execution_side=TradeSide.SELL,
            implementation_certification_identifier="cert:short",
            evidence_identifiers=("impl:short",),
        ),
    )
    profiles = {
        "LONGETF": _profiles()["LONGETF"],
        "SHORTETF": SimpleNamespace(
            instrument_identifier="exec:short", defined_risk=False
        ),
    }
    with pytest.raises(AtomicRelativeValueExecutionError, match="naked paper shorts"):
        orchestrator.execute(
            expression=_expression(),
            construction=construction,
            decision_identifier="decision:1",
            portfolio=beginning,
            profiles=profiles,
            implementations=implementations,
            as_of=NOW,
        )


def test_relative_leg_proportions_cannot_be_distorted(tmp_path, monkeypatch):
    orchestrator, beginning, _real_portfolio, _store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(_snapshot("temp:end"))
    )
    distorted = SimpleNamespace(
        request_identifier="construction:distorted",
        as_of=NOW,
        trades=(
            SimpleNamespace(symbol="LONGETF", side=TradeSide.BUY, trade_weight=0.15),
            SimpleNamespace(symbol="INVETF", side=TradeSide.BUY, trade_weight=0.05),
        ),
    )
    with pytest.raises(AtomicRelativeValueExecutionError, match="distorts relative-value proportions"):
        orchestrator.execute(
            expression=_expression(),
            construction=distorted,
            decision_identifier="decision:1",
            portfolio=beginning,
            profiles=_profiles(),
            implementations=_implementations(),
            as_of=NOW,
        )


def test_uncertified_atomic_expression_cannot_execute(tmp_path, monkeypatch):
    orchestrator, beginning, _real_portfolio, _store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(_snapshot("temp:end"))
    )
    with pytest.raises(AtomicRelativeValueExecutionError, match="not paper-execution eligible"):
        orchestrator.execute(
            expression=_expression(certified=False),
            construction=_construction(),
            decision_identifier="decision:1",
            portfolio=beginning,
            profiles=_profiles(),
            implementations=_implementations(),
            as_of=NOW,
        )


def test_prepared_commit_recovers_without_duplicate_portfolio_append(tmp_path, monkeypatch):
    orchestrator, beginning, real_portfolio, store = _orchestrator(
        tmp_path, monkeypatch, batch=_batch(_snapshot("temp:end"))
    )
    expression = _expression()
    construction = _construction()
    execution_id = orchestrator._execution_identifier(expression, construction)
    committed_id = orchestrator._committed_identifier(beginning.identifier, execution_id)
    prepared = AtomicRelativeValueExecutionAttempt(
        identifier=execution_id,
        expression_identifier=expression.identifier,
        decision_identifier="decision:1",
        construction_identifier=construction.request_identifier,
        attempted_at=NOW,
        status=AtomicRelativeValueExecutionStatus.PREPARED,
        beginning_snapshot_identifier=beginning.identifier,
        ending_snapshot_identifier=committed_id,
        underlying_batch_identifier="batch:recovery",
        implementation_identifiers=("cert:long", "cert:inverse"),
        reasons=("prepared before simulated crash",),
        attempt=1,
        canonical_state_changed=False,
    )
    store.append(prepared)
    real_portfolio.append(
        CanonicalPortfolioSnapshot(
            identifier=committed_id,
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="COMPOUNDING",
            as_of=NOW,
            starting_capital=250_000.0,
            cash_amount=250_000.0,
            positions=(),
            source_identifiers=("recovered",),
        )
    )
    result = orchestrator.execute(
        expression=expression,
        construction=construction,
        decision_identifier="decision:1",
        portfolio=beginning,
        profiles=_profiles(),
        implementations=_implementations(),
        as_of=NOW,
    )
    assert result.status is AtomicRelativeValueExecutionStatus.COMPLETED
    assert result.attempt == 1
    assert real_portfolio.latest("COMPOUNDING").identifier == committed_id
    assert store.verify_integrity() is True
