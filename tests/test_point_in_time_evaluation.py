"""Point-in-time evaluation, calibration, walk-forward, and paper tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from application.cio_cycle import CanonicalCIOCycle
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from evaluation import (
    AlternativeRealizedReturn,
    ConfidenceCalibrator,
    EvaluationOutcome,
    EvaluationProcessVerdict,
    EvidenceReference,
    PaperTradeFill,
    PointInTimeDecisionEvaluator,
    PointInTimeResearchRecord,
    PointInTimeUniverseMembership,
    RealizedDecisionOutcome,
    WalkForwardAuditor,
    WalkForwardFold,
    WalkForwardVerdict,
)
from evaluation.persistence import (
    append_calibration_report,
    append_decision_evaluation,
    append_paper_trade_fill,
    append_walk_forward_audit,
)
from portfolio.construction_api import TradeSide
from tests.test_canonical_cio_cycle import (
    AS_OF,
    _candidate,
    _construction_policy,
    _context,
    _opportunity_context,
    _portfolio,
)


def _cycle(tmp_path):
    candidate = _candidate("QUAL")
    journal = SQLiteCIOJournal(tmp_path / "decision-evaluation.db")
    result = CanonicalCIOCycle(
        construction_policy=_construction_policy(),
        journal=journal,
    ).run(
        identifier="cycle:evaluation",
        candidates=(candidate,),
        opportunity_context=_opportunity_context(),
        specialist_contexts=(_context(candidate),),
        portfolio=_portfolio((candidate,)),
        code_version="commit:evaluation",
    )
    return candidate, journal, result


def _realized(snapshot, *, candidate_return=0.20, implementation_return=0.18):
    returns = []
    for alternative in snapshot.alternatives:
        value = 0.04 if alternative.kind.value == "cash" else 0.08
        returns.append(
            AlternativeRealizedReturn(
                alternative_identifier=alternative.identifier,
                realized_return=value,
                source_identifier=f"prices:{alternative.identifier}",
            )
        )
    return RealizedDecisionOutcome(
        snapshot_identifier=snapshot.identifier,
        horizon_ended_at=AS_OF + timedelta(days=365),
        observed_at=AS_OF + timedelta(days=366),
        decision_to_horizon_return=candidate_return,
        implementation_to_horizon_return=implementation_return,
        actual_implementation_cost_return=0.001,
        cash_return=0.04,
        benchmark_return=0.10,
        passive_portfolio_return=0.09,
        alternative_returns=tuple(returns),
        source_identifiers=("prices:qual", "benchmark:sp500"),
    )


def test_cycle_journals_construction_and_complete_evidence_snapshot(tmp_path) -> None:
    candidate, journal, result = _cycle(tmp_path)

    assert len(result.evaluation_snapshots) == 1
    snapshot = result.evaluation_snapshots[0]
    assert snapshot.candidate_identifier == candidate.identifier
    assert {item.identifier for item in snapshot.alternatives} == {
        item.identifier for item in _opportunity_context().alternatives
    }
    assert snapshot.implemented_position_weight == pytest.approx(0.08)
    assert snapshot.thesis_identifier == result.theses[0].identifier
    assert snapshot.fingerprint == snapshot.to_dict()["fingerprint"]
    assert all(
        item.available_at <= snapshot.decision_as_of
        for item in snapshot.evidence_references
    )
    event_types = tuple(item.event_type for item in journal.events(limit=20))
    assert CIOJournalEventType.PORTFOLIO_CONSTRUCTION in event_types
    assert CIOJournalEventType.DECISION_EVIDENCE_SNAPSHOT in event_types
    assert journal.verify_integrity()


def test_snapshot_rejects_evidence_unavailable_at_decision_time(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    future = EvidenceReference(
        identifier="future:evidence",
        available_at=snapshot.decision_as_of + timedelta(seconds=1),
        source_type="forbidden_hindsight",
    )

    with pytest.raises(ValueError, match="unavailable at decision time"):
        replace(snapshot, evidence_references=(future,))


def test_evaluator_requires_exact_original_capital_alternative_set(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    realized = _realized(snapshot)

    with pytest.raises(ValueError, match="exactly match"):
        PointInTimeDecisionEvaluator().evaluate(
            snapshot,
            replace(
                realized,
                alternative_returns=realized.alternative_returns[:-1],
            ),
        )


def test_evaluation_reconciles_selection_sizing_timing_and_cost(tmp_path) -> None:
    _, journal, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(snapshot),
    )

    assert evaluation.process_verdict is EvaluationProcessVerdict.DISCIPLINED
    assert evaluation.outcome is EvaluationOutcome.VALUE_ADDED
    assert evaluation.best_original_alternative_return == pytest.approx(0.08)
    assert evaluation.attribution.net_active_contribution == pytest.approx(
        evaluation.attribution.selection
        + evaluation.attribution.sizing
        + evaluation.attribution.timing
        + evaluation.attribution.implementation_cost
    )
    assert evaluation.excess_return_vs_cash == pytest.approx(0.14)
    append_decision_evaluation(journal, evaluation)
    assert journal.events(
        event_type=CIOJournalEventType.DECISION_EVALUATION,
    )[0].payload["snapshot_fingerprint"] == snapshot.fingerprint
    assert journal.verify_integrity()


def test_disciplined_process_can_have_negative_outcome(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(
            snapshot,
            candidate_return=-0.15,
            implementation_return=-0.16,
        ),
    )

    assert evaluation.process_verdict is EvaluationProcessVerdict.DISCIPLINED
    assert evaluation.outcome is EvaluationOutcome.VALUE_DESTROYED
    assert not evaluation.process_failures


def test_confidence_calibration_uses_frozen_decision_confidence(tmp_path) -> None:
    _, journal, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    positive = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(snapshot),
    )
    negative_snapshot = replace(
        snapshot,
        identifier="evaluation-snapshot:negative",
        decision_identifier="decision:negative",
        final_confidence=0.75,
    )
    negative = PointInTimeDecisionEvaluator().evaluate(
        negative_snapshot,
        replace(
            _realized(
                negative_snapshot,
                candidate_return=-0.10,
                implementation_return=-0.12,
            ),
            snapshot_identifier=negative_snapshot.identifier,
        ),
    )
    report = ConfidenceCalibrator().build(
        ((snapshot, positive), (negative_snapshot, negative)),
        as_of=AS_OF + timedelta(days=367),
        bucket_width=0.25,
    )

    assert report.count == 2
    assert sum(item.count for item in report.buckets) == 2
    assert 0.0 <= report.calibration_error <= 1.0
    append_calibration_report(journal, report)
    assert journal.events(
        event_type=CIOJournalEventType.CONFIDENCE_CALIBRATION,
    )


def test_walk_forward_audit_blocks_lookahead_and_survivorship_bias() -> None:
    decision_at = datetime(2026, 1, 31, tzinfo=timezone.utc)
    valid_record = PointInTimeResearchRecord(
        identifier="filing:old",
        symbol="OLD",
        observed_at=decision_at - timedelta(days=30),
        available_at=decision_at - timedelta(days=20),
        model_input=True,
    )
    future_record = PointInTimeResearchRecord(
        identifier="filing:future",
        symbol="NEW",
        observed_at=decision_at - timedelta(days=5),
        available_at=decision_at + timedelta(days=1),
        model_input=True,
    )
    membership = PointInTimeUniverseMembership(
        symbol="OLD",
        eligible_from=decision_at - timedelta(days=365),
        eligible_until=None,
        source_identifier="universe:2026-01-31",
    )
    fold = WalkForwardFold(
        identifier="fold:1",
        training_started_at=decision_at - timedelta(days=365),
        training_ended_at=decision_at - timedelta(days=1),
        decision_at=decision_at,
        evaluation_ended_at=decision_at + timedelta(days=90),
        research_records=(valid_record, future_record),
        universe_memberships=(membership,),
        evaluated_symbols=("OLD", "NEW"),
    )

    audit = WalkForwardAuditor().audit(fold)
    assert audit.verdict is WalkForwardVerdict.LOOKAHEAD_VIOLATION
    assert any("look-ahead" in item for item in audit.violations)
    assert any("point-in-time universe" in item for item in audit.violations)


def test_valid_walk_forward_and_paper_fill_are_append_only(tmp_path) -> None:
    _, journal, result = _cycle(tmp_path)
    decision_at = AS_OF
    fold = WalkForwardFold(
        identifier="fold:valid",
        training_started_at=decision_at - timedelta(days=365),
        training_ended_at=decision_at - timedelta(days=1),
        decision_at=decision_at,
        evaluation_ended_at=decision_at + timedelta(days=90),
        research_records=(
            PointInTimeResearchRecord(
                identifier="filing:valid",
                symbol="QUAL",
                observed_at=decision_at - timedelta(days=30),
                available_at=decision_at - timedelta(days=20),
                model_input=True,
            ),
        ),
        universe_memberships=(
            PointInTimeUniverseMembership(
                symbol="QUAL",
                eligible_from=decision_at - timedelta(days=365),
                eligible_until=None,
                source_identifier="universe:valid",
            ),
        ),
        evaluated_symbols=("QUAL",),
    )
    audit = WalkForwardAuditor().audit(fold)
    assert audit.verdict is WalkForwardVerdict.VALID
    append_walk_forward_audit(
        journal,
        audit,
        occurred_at=fold.evaluation_ended_at,
    )

    fill = PaperTradeFill(
        identifier="paper-fill:qual:1",
        decision_identifier=result.decisions[0].identifier,
        construction_request_identifier=result.construction.request_identifier,
        symbol="QUAL",
        side=TradeSide.BUY,
        proposed_at=AS_OF,
        filled_at=AS_OF + timedelta(minutes=5),
        proposed_weight=0.08,
        filled_weight=0.075,
        reference_price=100.0,
        fill_price=100.20,
        estimated_cost_return=0.00008,
        realized_cost_return=0.00015,
        source_identifier="paper-market:qual",
    )
    assert fill.completion_ratio == pytest.approx(0.9375)
    assert fill.slippage_return < 0.0
    append_paper_trade_fill(journal, fill)
    assert journal.events(event_type=CIOJournalEventType.PAPER_TRADE_FILL)
    assert journal.verify_integrity()
