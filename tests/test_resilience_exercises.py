"""Incident, recovery, and reconciliation exercise contract tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from operations import (
    ResilienceExerciseHarness,
    ResilienceExerciseIntegrityError,
    ResilienceExerciseKind,
    ResilienceExerciseOutcome,
    ResilienceExercisePolicy,
    ResilienceExerciseScenario,
    ResilienceExerciseStatus,
    SQLiteResilienceExerciseStore,
)
from tests.resilience_factories import PassingProvider


NOW = datetime(2026, 7, 27, 13, tzinfo=timezone.utc)


def _scenario(kind: ResilienceExerciseKind) -> ResilienceExerciseScenario:
    return ResilienceExerciseScenario(
        identifier=f"scenario:{kind.value}",
        kind=kind,
        description=f"Exercise {kind.value}",
        expected_invariants=("journal_hash", "portfolio_state", "policy_version"),
    )


def _suite():
    return tuple(_scenario(kind) for kind in ResilienceExerciseKind)


def test_complete_isolated_campaign_passes_release_gate() -> None:
    outcomes, report = ResilienceExerciseHarness().run(
        _suite(), PassingProvider(), evaluated_at=NOW
    )
    assert len(outcomes) == len(ResilienceExerciseKind)
    assert report.release_gate_passed
    assert report.passed_count == len(outcomes)
    assert not report.real_money_authorized
    assert not report.performance_claims_permitted
    assert report.blockers == ()


def test_missing_required_kind_blocks_campaign() -> None:
    _, report = ResilienceExerciseHarness().run(
        _suite()[:-1], PassingProvider(), evaluated_at=NOW
    )
    assert not report.release_gate_passed
    assert report.missing_required_kinds == (ResilienceExerciseKind.MODEL_ROLLBACK,)


def test_deadline_failure_is_reclassified_and_blocks() -> None:
    class SlowProvider(PassingProvider):
        def execute(self, scenario):
            outcome = super().execute(scenario)
            return replace(
                outcome,
                detected_at=outcome.injected_at + timedelta(seconds=301),
                recovered_at=outcome.injected_at + timedelta(seconds=302),
                reconciled_at=outcome.injected_at + timedelta(seconds=303),
            )

    _, report = ResilienceExerciseHarness(
        ResilienceExercisePolicy(required_kinds=(ResilienceExerciseKind.PROVIDER_OUTAGE,))
    ).run((_scenario(ResilienceExerciseKind.PROVIDER_OUTAGE),), SlowProvider(), evaluated_at=NOW)
    assert not report.release_gate_passed
    assert any("detection deadline" in item for item in report.blockers)


def test_provider_exception_becomes_blocked_evidence() -> None:
    class BrokenProvider:
        def execute(self, scenario):
            raise RuntimeError("sandbox unavailable")

    outcomes, report = ResilienceExerciseHarness(
        ResilienceExercisePolicy(required_kinds=(ResilienceExerciseKind.PROVIDER_OUTAGE,))
    ).run((_scenario(ResilienceExerciseKind.PROVIDER_OUTAGE),), BrokenProvider(), evaluated_at=NOW)
    assert outcomes[0].status is ResilienceExerciseStatus.BLOCKED
    assert "sandbox unavailable" in outcomes[0].error
    assert not report.release_gate_passed


def test_future_known_outcome_is_rejected() -> None:
    class FutureProvider(PassingProvider):
        def execute(self, scenario):
            outcome = super().execute(scenario)
            future = NOW + timedelta(minutes=1)
            return ResilienceExerciseOutcome(
                identifier=outcome.identifier,
                scenario_identifier=outcome.scenario_identifier,
                kind=outcome.kind,
                status=outcome.status,
                started_at=future,
                injected_at=future,
                detected_at=future,
                recovered_at=future,
                reconciled_at=future,
                isolated_environment=True,
                production_mutation_count=0,
                before_fingerprint=outcome.before_fingerprint,
                after_fingerprint=outcome.after_fingerprint,
                verified_invariants=outcome.verified_invariants,
                detection_evidence_identifiers=outcome.detection_evidence_identifiers,
                recovery_evidence_identifiers=outcome.recovery_evidence_identifiers,
                reconciliation_evidence_identifiers=outcome.reconciliation_evidence_identifiers,
            )

    with pytest.raises(ValueError, match="future-known"):
        ResilienceExerciseHarness().run(_suite(), FutureProvider(), evaluated_at=NOW)


def test_append_only_store_is_idempotent_and_tamper_evident(tmp_path) -> None:
    outcomes, report = ResilienceExerciseHarness().run(
        _suite(), PassingProvider(), evaluated_at=NOW
    )
    store = SQLiteResilienceExerciseStore(tmp_path / "resilience.db")
    store.append_outcome(outcomes[0], recorded_at=NOW)
    store.append_outcome(outcomes[0], recorded_at=NOW)
    store.append_report(report, recorded_at=NOW)
    assert store.event_count() == 2
    store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM resilience_events")
        connection.execute("DROP TRIGGER resilience_events_no_update")
        connection.execute("UPDATE resilience_events SET payload = '{}' WHERE sequence = 1")
    with pytest.raises(ResilienceExerciseIntegrityError, match="payload hash"):
        store.verify_integrity()
