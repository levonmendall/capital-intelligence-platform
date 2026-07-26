"""Production operational SLO evaluation and persistence tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from operations import (
    DecisionEvaluationSLOObservation,
    FullUniverseCycleRecord,
    FullUniverseCycleStatus,
    MetricRegistry,
    OperationalSLOEvaluator,
    OperationalSLOInputs,
    OperationalSLOIntegrityError,
    OperationalSLOName,
    OperationalSLOPolicy,
    OperationalSLOStatus,
    SQLiteOperationalSLOSource,
    SQLiteOperationalSLOStore,
    SecurityMasterSLOObservation,
    ThesisSLOObservation,
)

UTC = timezone.utc


def _provider(*, ready: bool = True, age: float = 2.0) -> SecurityMasterSLOObservation:
    return SecurityMasterSLOObservation(
        configured=True,
        screening_ready=ready,
        catalog_integrity_verified=True,
        operation_integrity_verified=True,
        active_catalog_identifier="catalog:authoritative" if ready else None,
        source_age_hours=age if ready else None,
        reasons=() if ready else ("authoritative catalog unavailable",),
    )


def _cycle(scheduled: datetime, *, completed_minutes: int = 60) -> FullUniverseCycleRecord:
    return FullUniverseCycleRecord(
        identifier=f"cycle:{scheduled.date().isoformat()}",
        scheduled_for=scheduled,
        started_at=scheduled - timedelta(minutes=5),
        completed_at=scheduled + timedelta(minutes=completed_minutes),
        status=FullUniverseCycleStatus.COMPLETED,
        security_master_catalog_identifier="catalog:authoritative",
        universe_snapshot_identifier="universe:v1",
        eligible_instrument_count=100,
        screened_instrument_count=100,
        qualified_candidate_count=8,
    )


def _by_name(snapshot, name: OperationalSLOName):
    return next(item for item in snapshot.components if item.name is name)


def test_policy_uses_latest_weekday_schedule_in_configured_timezone() -> None:
    policy = OperationalSLOPolicy()
    sunday = datetime(2026, 7, 26, 18, tzinfo=UTC)
    expected = policy.expected_screening_time(sunday)
    assert expected == datetime(2026, 7, 24, 11, tzinfo=UTC)


def test_cycle_is_pending_before_deadline_and_breached_after_deadline() -> None:
    policy = OperationalSLOPolicy()
    evaluator = OperationalSLOEvaluator(policy)
    before = datetime(2026, 7, 27, 12, tzinfo=UTC)
    pending = evaluator.evaluate(
        OperationalSLOInputs(security_master=_provider()),
        evaluated_at=before,
    )
    assert _by_name(pending, OperationalSLOName.FULL_UNIVERSE_CYCLE).status is OperationalSLOStatus.PENDING

    after = datetime(2026, 7, 27, 14, tzinfo=UTC)
    breached = evaluator.evaluate(
        OperationalSLOInputs(security_master=_provider()),
        evaluated_at=after,
    )
    assert _by_name(breached, OperationalSLOName.FULL_UNIVERSE_CYCLE).status is OperationalSLOStatus.BREACHED


def test_complete_cycle_requires_active_catalog_full_coverage_and_deadline() -> None:
    policy = OperationalSLOPolicy()
    evaluated = datetime(2026, 7, 27, 12, 30, tzinfo=UTC)
    scheduled = policy.expected_screening_time(evaluated)
    snapshot = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(_cycle(scheduled),),
        ),
        evaluated_at=evaluated,
    )
    component = _by_name(snapshot, OperationalSLOName.FULL_UNIVERSE_CYCLE)
    assert component.status is OperationalSLOStatus.MET
    assert component.actual_value == 60.0

    partial = FullUniverseCycleRecord(
        identifier="cycle:partial",
        scheduled_for=scheduled,
        started_at=scheduled,
        completed_at=scheduled + timedelta(minutes=30),
        status=FullUniverseCycleStatus.COMPLETED,
        security_master_catalog_identifier="catalog:other",
        universe_snapshot_identifier="universe:v1",
        eligible_instrument_count=100,
        screened_instrument_count=99,
        qualified_candidate_count=8,
    )
    failed = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(partial,),
        ),
        evaluated_at=evaluated,
    )
    component = _by_name(failed, OperationalSLOName.FULL_UNIVERSE_CYCLE)
    assert component.status is OperationalSLOStatus.BREACHED
    assert "currently active" in component.detail
    assert "99/100" in component.detail


def test_provider_staleness_and_integrity_fail_closed() -> None:
    policy = OperationalSLOPolicy(provider_maximum_age_hours=24)
    evaluator = OperationalSLOEvaluator(policy)
    stale = evaluator.evaluate(
        OperationalSLOInputs(security_master=_provider(age=25)),
        evaluated_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )
    assert _by_name(stale, OperationalSLOName.PROVIDER_FRESHNESS).status is OperationalSLOStatus.BREACHED

    invalid = SecurityMasterSLOObservation(
        configured=True,
        screening_ready=True,
        catalog_integrity_verified=False,
        operation_integrity_verified=True,
        active_catalog_identifier="catalog:authoritative",
        source_age_hours=1,
    )
    snapshot = evaluator.evaluate(
        OperationalSLOInputs(security_master=invalid),
        evaluated_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )
    assert _by_name(snapshot, OperationalSLOName.PROVIDER_FRESHNESS).status is OperationalSLOStatus.BREACHED


def test_thesis_and_evaluation_deadlines_use_frozen_journal_records() -> None:
    evaluated = datetime(2026, 7, 27, 12, tzinfo=UTC)
    policy = OperationalSLOPolicy(
        thesis_review_grace_hours=24,
        decision_evaluation_grace_hours=48,
    )
    scheduled = policy.expected_screening_time(evaluated)
    inputs = OperationalSLOInputs(
        security_master=_provider(),
        cycles=(_cycle(scheduled),),
        theses=(
            ThesisSLOObservation(
                identifier="thesis:overdue",
                state="active",
                next_review_at=evaluated - timedelta(hours=25),
            ),
            ThesisSLOObservation(
                identifier="thesis:closed",
                state="invalidated",
                next_review_at=evaluated - timedelta(days=30),
            ),
        ),
        evaluations=(
            DecisionEvaluationSLOObservation(
                snapshot_identifier="evidence:overdue",
                decision_at=evaluated - timedelta(days=12, hours=1),
                horizon_days=10,
            ),
            DecisionEvaluationSLOObservation(
                snapshot_identifier="evidence:done",
                decision_at=evaluated - timedelta(days=12),
                horizon_days=10,
                evaluated_at=evaluated - timedelta(hours=1),
            ),
        ),
    )
    snapshot = OperationalSLOEvaluator(policy).evaluate(inputs, evaluated_at=evaluated)
    thesis = _by_name(snapshot, OperationalSLOName.THESIS_REVIEW)
    evaluation = _by_name(snapshot, OperationalSLOName.DECISION_EVALUATION)
    assert thesis.status is OperationalSLOStatus.BREACHED
    assert thesis.affected_identifiers == ("thesis:overdue",)
    assert evaluation.status is OperationalSLOStatus.BREACHED
    assert evaluation.affected_identifiers == ("evidence:overdue",)


def test_decision_evaluation_deadline_is_inclusive_and_breaches_afterward() -> None:
    evaluated = datetime(2026, 7, 27, 12, tzinfo=UTC)
    policy = OperationalSLOPolicy(decision_evaluation_grace_hours=48)
    scheduled = policy.expected_screening_time(evaluated)

    at_deadline = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(_cycle(scheduled),),
            evaluations=(
                DecisionEvaluationSLOObservation(
                    snapshot_identifier="evidence:deadline",
                    decision_at=evaluated - timedelta(days=12),
                    horizon_days=10,
                ),
            ),
        ),
        evaluated_at=evaluated,
    )
    component = _by_name(
        at_deadline,
        OperationalSLOName.DECISION_EVALUATION,
    )
    assert component.status is OperationalSLOStatus.MET
    assert component.affected_identifiers == ()

    after_deadline = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(_cycle(scheduled),),
            evaluations=(
                DecisionEvaluationSLOObservation(
                    snapshot_identifier="evidence:late",
                    decision_at=evaluated - timedelta(days=12, seconds=1),
                    horizon_days=10,
                ),
            ),
        ),
        evaluated_at=evaluated,
    )
    component = _by_name(
        after_deadline,
        OperationalSLOName.DECISION_EVALUATION,
    )
    assert component.status is OperationalSLOStatus.BREACHED
    assert component.affected_identifiers == ("evidence:late",)


def test_missing_or_invalid_journal_blocks_journal_slos() -> None:
    evaluated = datetime(2026, 7, 27, 12, tzinfo=UTC)
    policy = OperationalSLOPolicy()
    scheduled = policy.expected_screening_time(evaluated)
    snapshot = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(_cycle(scheduled),),
            journal_integrity_verified=False,
            journal_reasons=("canonical CIO journal database does not exist",),
        ),
        evaluated_at=evaluated,
    )
    assert _by_name(snapshot, OperationalSLOName.THESIS_REVIEW).status is OperationalSLOStatus.BLOCKED
    assert _by_name(snapshot, OperationalSLOName.DECISION_EVALUATION).status is OperationalSLOStatus.BLOCKED
    assert not snapshot.ready


def test_slo_store_is_append_only_idempotent_and_tamper_evident(tmp_path) -> None:
    path = tmp_path / "slos.db"
    store = SQLiteOperationalSLOStore(path)
    scheduled = datetime(2026, 7, 27, 11, tzinfo=UTC)
    record = _cycle(scheduled)
    store.append_cycle(record)
    store.append_cycle(record)
    assert store.cycles() == (record,)

    snapshot = OperationalSLOEvaluator().evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(record,),
            journal_integrity_verified=False,
            journal_reasons=("missing",),
        ),
        evaluated_at=scheduled + timedelta(hours=1),
    )
    store.append_snapshot(snapshot)
    store.append_snapshot(snapshot)
    assert store.latest_snapshot() == snapshot
    assert store.verify_integrity()

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE full_universe_cycle_records SET identifier = 'changed'"
            )

    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER full_universe_cycle_records_no_update")
        connection.execute(
            "UPDATE full_universe_cycle_records SET payload_json = '{}' WHERE sequence = 1"
        )
    with pytest.raises(OperationalSLOIntegrityError, match="content hash"):
        store.verify_integrity()


def test_source_marks_missing_authoritative_stores_as_blocking(tmp_path) -> None:
    store = SQLiteOperationalSLOStore(tmp_path / "missing-slo.db", initialize=False)
    source = SQLiteOperationalSLOSource(
        security_master_database=tmp_path / "missing-security.db",
        journal_database=tmp_path / "missing-journal.db",
        slo_store=store,
    )
    inputs = source.load(
        policy=OperationalSLOPolicy(),
        evaluated_at=datetime(2026, 7, 27, 12, tzinfo=UTC),
    )
    assert not inputs.security_master.configured
    assert not inputs.journal_integrity_verified
    assert "does not exist" in inputs.journal_reasons[0]


def test_snapshot_publishes_prometheus_objective_metrics() -> None:
    evaluated = datetime(2026, 7, 27, 12, tzinfo=UTC)
    policy = OperationalSLOPolicy()
    scheduled = policy.expected_screening_time(evaluated)
    snapshot = OperationalSLOEvaluator(policy).evaluate(
        OperationalSLOInputs(
            security_master=_provider(),
            cycles=(_cycle(scheduled),),
        ),
        evaluated_at=evaluated,
    )
    registry = MetricRegistry()
    snapshot.publish_metrics(registry)
    output = registry.render()
    assert "capital_intelligence_operational_slo_ready" in output
    assert 'objective="provider_freshness"' in output
    assert 'status="met"' in output
