from __future__ import annotations

import pytest

from application.cio_cycle import CanonicalCIOCycle
from cio import CIOAction
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from portfolio.decision_reconciliation import ConstructionDisposition
from tests.test_canonical_cio_cycle import (
    _candidate,
    _construction_policy,
    _context,
    _opportunity_context,
    _portfolio,
)


def test_exact_cio_target_is_reconciled_to_final_construction() -> None:
    candidate = _candidate("EXACT")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:construction-reconciliation-exact",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
    )

    assert len(result.construction_reconciliations) == 1
    record = result.construction_reconciliations[0]
    assert record.action is CIOAction.BUY
    assert record.cio_target_weight == pytest.approx(0.08)
    assert record.final_target_weight == pytest.approx(0.08)
    assert record.target_delta == pytest.approx(0.0)
    assert record.disposition is ConstructionDisposition.IMPLEMENTED_EXACTLY


def test_scarce_cash_records_approved_target_reduced_to_zero() -> None:
    first = _candidate("FIRST", base_return=0.15, bull_return=0.30)
    second = _candidate("SECOND", base_return=0.11, bull_return=0.22)
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
    ).run(
        identifier="cycle:construction-reconciliation-scarce-cash",
        candidates=(second, first),
        opportunity_context=_opportunity_context(cash_weight=0.10),
        specialist_contexts=(_context(second), _context(first)),
        portfolio=_portfolio((first, second), cash_weight=0.10),
    )

    by_symbol = {
        item.symbol: item for item in result.construction_reconciliations
    }
    assert by_symbol["FIRST"].final_target_weight == pytest.approx(0.08)
    assert by_symbol["SECOND"].cio_target_weight is not None
    assert by_symbol["SECOND"].final_target_weight == pytest.approx(0.0)
    assert by_symbol["SECOND"].zeroed_after_approval
    assert by_symbol["SECOND"].funding_conflict
    assert "FIRST" in by_symbol["SECOND"].displaced_by


def test_reconciliation_is_append_only_journal_evidence(tmp_path) -> None:
    candidate = _candidate("JOURNAL")
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:construction-reconciliation-journal",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
        code_version="test",
    )

    event = next(
        item
        for item in journal.events()
        if item.event_type is CIOJournalEventType.CONSTRUCTION_RECONCILIATION
    )
    assert event.payload["decision_identifier"] == result.decisions[0].identifier
    assert event.payload["disposition"] == "implemented_exactly"
    assert journal.verify_integrity()
