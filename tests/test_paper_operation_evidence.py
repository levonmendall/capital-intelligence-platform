"""Extended paper-operation evidence and governance-readiness tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from evaluation import (
    PaperOperationEvidenceEvaluator,
    PaperOperationEvidenceIntegrityError,
    PaperOperationObservation,
    PaperOperationPolicy,
    PaperOperationReadiness,
    SQLitePaperOperationEvidenceStore,
)

UTC = timezone.utc


def _observation(
    identifier: str,
    day: int,
    *,
    regime: str = "expansion",
    portfolio_return: float = 0.001,
    benchmark_return: float = 0.002,
    completed_cycles: int = 1,
    data_failures: int = 0,
    alert_false_positive: int = 0,
) -> PaperOperationObservation:
    start = datetime(2026, 7, day, tzinfo=UTC)
    return PaperOperationObservation(
        identifier=identifier,
        period_start=start,
        period_end=start + timedelta(hours=23),
        observed_at=start + timedelta(days=1),
        regime=regime,
        expected_full_universe_cycles=1,
        completed_full_universe_cycles=completed_cycles,
        decision_count=2,
        action_decision_count=1,
        abstention_decision_count=1,
        evaluations_due=2,
        evaluations_completed=2,
        confidence_sample_count=2,
        brier_score_sum=0.20,
        calibration_absolute_error_sum=0.08,
        paper_execution_batches=1,
        paper_execution_completed=1,
        paper_execution_reconciled=1,
        paper_execution_failed=0,
        turnover=0.05,
        transaction_cost_return=0.0002,
        thesis_reviews_due=2,
        thesis_reviews_completed=2,
        theses_strengthening=1,
        theses_stable=1,
        theses_weakening=0,
        theses_invalidated=0,
        alerts_generated=2,
        alerts_sent=1,
        alerts_suppressed=1,
        alerts_acknowledged=1,
        alerts_useful=1 - alert_false_positive,
        alerts_false_positive=alert_false_positive,
        portfolio_return=portfolio_return,
        benchmark_return=benchmark_return,
        cash_return=0.0001,
        passive_return=0.0015,
        data_integrity_failures=data_failures,
        evidence_identifiers=(f"journal:{day}", f"slo:{day}", f"execution:{day}"),
    )


def _policy(**overrides) -> PaperOperationPolicy:
    values = dict(
        minimum_observation_days=2,
        minimum_distinct_regimes=2,
        minimum_completed_cycles=2,
        minimum_decisions=4,
        minimum_confidence_samples=4,
        minimum_paper_execution_batches=2,
        minimum_alert_feedback_samples=2,
    )
    values.update(overrides)
    return PaperOperationPolicy(**values)


def test_complete_control_sample_is_ready_only_for_governance_review() -> None:
    report = PaperOperationEvidenceEvaluator(_policy()).evaluate(
        (
            _observation("obs:1", 1, regime="expansion"),
            _observation("obs:2", 2, regime="contraction"),
        ),
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert report.status is PaperOperationReadiness.READY_FOR_GOVERNANCE_REVIEW
    assert report.ready_for_governance_review
    assert report.real_money_authorized is False
    assert report.performance_claims_permitted is False
    assert report.cycle_completion_rate == 1.0
    assert report.evaluation_coverage == 1.0
    assert report.reconciliation_rate == 1.0
    assert report.abstention_decision_count == 2


def test_small_clean_sample_is_insufficient_not_blocked() -> None:
    observation = _observation("obs:small", 1)
    observation = PaperOperationObservation.from_dict(
        {
            **observation.to_dict(),
            "expected_full_universe_cycles": 0,
            "completed_full_universe_cycles": 0,
            "evaluations_due": 0,
            "evaluations_completed": 0,
            "paper_execution_batches": 0,
            "paper_execution_completed": 0,
            "paper_execution_reconciled": 0,
            "thesis_reviews_due": 0,
            "thesis_reviews_completed": 0,
        }
    )
    report = PaperOperationEvidenceEvaluator().evaluate(
        (observation,),
        evaluated_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    assert report.status is PaperOperationReadiness.INSUFFICIENT_EVIDENCE
    assert report.blockers == ()
    assert report.insufficiencies


def test_operational_and_integrity_failures_block_review() -> None:
    report = PaperOperationEvidenceEvaluator(_policy()).evaluate(
        (
            _observation("obs:1", 1, regime="expansion"),
            _observation(
                "obs:2",
                2,
                regime="contraction",
                completed_cycles=0,
                data_failures=1,
            ),
        ),
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert report.status is PaperOperationReadiness.BLOCKED
    assert any("cycle completion" in item for item in report.blockers)
    assert any("data-integrity" in item for item in report.blockers)


def test_underperforming_portfolio_is_diagnostic_not_automatic_blocker() -> None:
    report = PaperOperationEvidenceEvaluator(_policy()).evaluate(
        (
            _observation("obs:1", 1, regime="expansion", portfolio_return=-0.01, benchmark_return=0.02),
            _observation("obs:2", 2, regime="contraction", portfolio_return=-0.01, benchmark_return=0.01),
        ),
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert report.status is PaperOperationReadiness.READY_FOR_GOVERNANCE_REVIEW
    assert report.portfolio_return_vs_benchmark < 0
    assert "diagnostic" in report.diagnostics[0].lower()


def test_alert_false_positive_rate_blocks_only_after_minimum_feedback_sample() -> None:
    one = _observation("obs:1", 1, alert_false_positive=1)
    insufficient_policy = _policy(minimum_alert_feedback_samples=3)
    report = PaperOperationEvidenceEvaluator(insufficient_policy).evaluate(
        (one, _observation("obs:2", 2, regime="contraction")),
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert report.status is PaperOperationReadiness.INSUFFICIENT_EVIDENCE
    assert not any("false-positive" in item for item in report.blockers)

    blocking_policy = _policy(maximum_alert_false_positive_rate=0.25)
    blocked = PaperOperationEvidenceEvaluator(blocking_policy).evaluate(
        (one, _observation("obs:2", 2, regime="contraction")),
        evaluated_at=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert blocked.status is PaperOperationReadiness.BLOCKED
    assert any("false-positive" in item for item in blocked.blockers)


def test_observation_periods_cannot_overlap_or_use_future_knowledge() -> None:
    first = _observation("obs:1", 1)
    overlapping = PaperOperationObservation.from_dict(
        {
            **_observation("obs:2", 2).to_dict(),
            "period_start": "2026-07-01T12:00:00+00:00",
        }
    )
    with pytest.raises(ValueError, match="cannot overlap"):
        PaperOperationEvidenceEvaluator().evaluate(
            (first, overlapping),
            evaluated_at=datetime(2026, 7, 5, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="cannot be known"):
        PaperOperationEvidenceEvaluator().evaluate(
            (first,),
            evaluated_at=datetime(2026, 7, 1, 12, tzinfo=UTC),
        )


def test_store_is_idempotent_append_only_and_tamper_evident(tmp_path) -> None:
    path = tmp_path / "paper_operation.db"
    store = SQLitePaperOperationEvidenceStore(path)
    observation = _observation("obs:1", 1)
    store.append_observation(observation)
    store.append_observation(observation)
    assert len(store.observations()) == 1
    report = PaperOperationEvidenceEvaluator().evaluate(
        (observation,),
        evaluated_at=datetime(2026, 7, 3, tzinfo=UTC),
    )
    store.append_report(report)
    assert store.latest_report() == report
    assert store.verify_integrity()

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM paper_operation_observations")

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER paper_operation_observations_no_update")
        connection.execute(
            "UPDATE paper_operation_observations SET payload_json = '{}' WHERE sequence = 1"
        )
    with pytest.raises(PaperOperationEvidenceIntegrityError, match="content hash"):
        store.verify_integrity()
