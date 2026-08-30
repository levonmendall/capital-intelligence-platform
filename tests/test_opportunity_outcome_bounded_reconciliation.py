from datetime import datetime, timedelta, timezone

import evaluation.opportunity_outcomes as opportunity_outcomes
from evaluation.opportunity_outcomes import SQLiteOpportunityOutcomeStore


def _append_decision(
    store: SQLiteOpportunityOutcomeStore,
    *,
    identifier: str,
    symbol: str,
    as_of: datetime,
) -> None:
    store._append(
        event_identifier=f"screening-decision:{identifier}",
        event_type="screening_decision",
        symbol=symbol,
        occurred_at=as_of,
        payload={
            "candidate_identifier": identifier,
            "symbol": symbol,
            "decision_as_of": as_of.isoformat(),
            "decision_horizon_days": 30,
            "starting_price": 100.0,
            "cash_annual_return": 0.04,
            "disposition": "rejected",
            "rank": None,
            "score": None,
            "reasons": ["regression_fixture"],
            "resolved_policy_profile": None,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )


def test_resolve_due_does_not_materialize_full_historical_ledgers(tmp_path, monkeypatch):
    store = SQLiteOpportunityOutcomeStore(tmp_path / "outcomes.sqlite3")
    observed_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
    decision_at = observed_at - timedelta(days=30)
    for index in range(7):
        _append_decision(
            store,
            identifier=f"candidate-{index}",
            symbol=f"T{index}",
            as_of=decision_at,
        )

    monkeypatch.setattr(opportunity_outcomes, "_DECISION_RESOLUTION_BATCH_SIZE", 2)
    monkeypatch.setattr(
        store,
        "_decision_rows",
        lambda: (_ for _ in ()).throw(AssertionError("full decision ledger materialized")),
    )
    monkeypatch.setattr(
        store,
        "_outcome_decision_ids",
        lambda: (_ for _ in ()).throw(AssertionError("full outcome-id ledger materialized")),
    )

    prices = {f"T{index}": (110.0, "test-price") for index in range(7)}
    assert store.resolve_due(observed_at=observed_at, observed_prices=prices) == 7
    assert store.resolve_due(observed_at=observed_at, observed_prices=prices) == 0
    assert store.verify_integrity() is True


def test_bounded_reconciliation_skips_resolved_and_not_due_without_blocking(tmp_path, monkeypatch):
    store = SQLiteOpportunityOutcomeStore(tmp_path / "outcomes.sqlite3")
    observed_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
    old = observed_at - timedelta(days=30)
    recent = observed_at - timedelta(days=2)

    _append_decision(store, identifier="already-resolved", symbol="OLD", as_of=old)
    assert store.resolve_due(
        observed_at=observed_at,
        observed_prices={"OLD": (90.0, "first-observation")},
    ) == 1

    _append_decision(store, identifier="not-due", symbol="NEW", as_of=recent)
    _append_decision(store, identifier="due-later-page", symbol="DUE", as_of=old)
    monkeypatch.setattr(opportunity_outcomes, "_DECISION_RESOLUTION_BATCH_SIZE", 1)

    assert store.resolve_due(
        observed_at=observed_at,
        observed_prices={
            "OLD": (90.0, "second-observation"),
            "NEW": (110.0, "second-observation"),
            "DUE": (120.0, "second-observation"),
        },
    ) == 1
    assert store.verify_integrity() is True
