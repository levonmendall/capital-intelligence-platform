from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from portfolio.integrity_specialist import (
    PortfolioIntegrityDisposition,
    PortfolioValuationExecutionIntegritySpecialist,
    SQLitePortfolioIntegrityCertificationStore,
)
from portfolio.state import (
    CanonicalImplementationEvent,
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
)


def _snapshot(
    *,
    identifier: str,
    cash: float,
    quantity: float,
    event: CanonicalImplementationEvent | None = None,
) -> CanonicalPortfolioSnapshot:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    positions = ()
    if quantity > 0.0:
        positions = (
            CanonicalPortfolioPosition(
                symbol="VTI",
                instrument_identifier="instrument:us-etf:vti",
                venue="ARCX",
                asset_class="us_etf",
                quantity=quantity,
                average_cost=100.1,
                mark_price=100.0,
                updated_at=as_of,
            ),
        )
    return CanonicalPortfolioSnapshot(
        identifier=identifier,
        portfolio_code="COMPOUNDING",
        display_name="Capital Intelligence Compounding Portfolio",
        constraint_profile="governed-compounding.v1",
        as_of=as_of,
        starting_capital=250000.0,
        cash_amount=cash,
        positions=positions,
        implementation_events=() if event is None else (event,),
    )


def _buy_fill():
    return SimpleNamespace(
        identifier="fill:test",
        symbol="VTI",
        side=SimpleNamespace(value="buy"),
        quantity=10.0,
        gross_amount_base=1000.0,
        commission_base=1.0,
    )


def _buy_event() -> CanonicalImplementationEvent:
    return CanonicalImplementationEvent(
        identifier="fill:test",
        occurred_at=datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc),
        action="buy",
        symbol="VTI",
        quantity=10.0,
        price=100.0,
        gross_amount=1000.0,
        cost_amount=1.0,
    )


def test_specialist_certifies_reconciled_buy(tmp_path) -> None:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    review = PortfolioValuationExecutionIntegritySpecialist().review_execution(
        execution_identifier="multi-asset-execution:test",
        beginning=_snapshot(identifier="before", cash=250000.0, quantity=0.0),
        ending=_snapshot(
            identifier="after",
            cash=248999.0,
            quantity=10.0,
            event=_buy_event(),
        ),
        fills=(_buy_fill(),),
        reconciliation=SimpleNamespace(reconciled=True, difference=0.0),
        completed_at=as_of,
        attempt=1,
    )

    assert review.disposition is PortfolioIntegrityDisposition.CERTIFIED
    assert review.certified is True
    assert review.blocks == ()
    assert review.to_dict()["investment_decision_authorized"] is False
    assert review.to_dict()["real_money_authorized"] is False

    store = SQLitePortfolioIntegrityCertificationStore(tmp_path / "integrity.db")
    assert store.append(review) == 1
    assert store.append(review) == 1
    assert store.verify_integrity() is True
    assert store.latest("multi-asset-execution:test") == review


def test_specialist_holds_cash_mismatch() -> None:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    review = PortfolioValuationExecutionIntegritySpecialist().review_execution(
        execution_identifier="multi-asset-execution:test",
        beginning=_snapshot(identifier="before", cash=250000.0, quantity=0.0),
        ending=_snapshot(
            identifier="after",
            cash=249500.0,
            quantity=10.0,
            event=_buy_event(),
        ),
        fills=(_buy_fill(),),
        reconciliation=SimpleNamespace(reconciled=True, difference=0.0),
        completed_at=as_of,
        attempt=1,
    )

    assert review.disposition is PortfolioIntegrityDisposition.HELD
    assert any("cash does not reconcile" in item for item in review.blocks)


def test_specialist_holds_share_mismatch() -> None:
    as_of = datetime(2026, 7, 28, 19, 0, tzinfo=timezone.utc)
    review = PortfolioValuationExecutionIntegritySpecialist().review_execution(
        execution_identifier="multi-asset-execution:test",
        beginning=_snapshot(identifier="before", cash=250000.0, quantity=0.0),
        ending=_snapshot(
            identifier="after",
            cash=248999.0,
            quantity=9.0,
            event=_buy_event(),
        ),
        fills=(_buy_fill(),),
        reconciliation=SimpleNamespace(reconciled=True, difference=0.0),
        completed_at=as_of,
        attempt=1,
    )

    assert review.disposition is PortfolioIntegrityDisposition.HELD
    assert any("quantity does not reconcile" in item for item in review.blocks)


def test_specialist_is_not_a_sixth_investment_vote() -> None:
    from cio.models import SpecialistRole

    assert len(tuple(SpecialistRole)) == 5
    assert all("integrity" not in role.value for role in SpecialistRole)
