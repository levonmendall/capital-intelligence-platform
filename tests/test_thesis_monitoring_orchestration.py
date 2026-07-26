from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from cio import ThesisState
from cio.persistence import CIOJournalEventType, CIOJournalIntegrityError, SQLiteCIOJournal
from tests.cio_test_fixtures import AS_OF, build_candidate, build_decision, build_queue
from thesis import LivingThesis, ThesisEvidenceUpdate
from thesis.orchestration import (
    SQLiteThesisMonitoringStore,
    ThesisMonitoringEventType,
    ThesisMonitoringOrchestrator,
    ThesisMonitoringTrigger,
    ThesisReviewPriority,
    ThesisTriggerSource,
)


RUN_AT = AS_OF + timedelta(days=31)


class EvidenceProvider:
    def __init__(self, *, mode: str = "stable") -> None:
        self.mode = mode
        self.calls = 0
        self.contexts = []

    def update_for(self, thesis, *, as_of, opportunity_context):
        self.calls += 1
        self.contexts.append(opportunity_context)
        invalidations = ()
        expected_return = thesis.expected_return
        confidence = thesis.current_confidence
        weakened = ()
        strengthened = ()
        replacement = thesis.expected_return
        data_current = True
        if self.mode == "invalidate":
            invalidations = (thesis.invalidation_conditions[0],)
            expected_return = -0.10
        elif self.mode == "replacement":
            replacement = thesis.expected_return + 0.08
        elif self.mode == "strengthen":
            expected_return += 0.05
            confidence = min(1.0, confidence + 0.12)
            strengthened = (thesis.monitoring_indicators[0],)
        elif self.mode == "stale":
            data_current = False
        elif self.mode == "fail":
            raise RuntimeError("provider unavailable")
        return ThesisEvidenceUpdate(
            thesis_identifier=thesis.identifier,
            as_of=as_of,
            expected_return=expected_return,
            expected_downside=thesis.expected_downside,
            confidence=confidence,
            evidence_identifiers=(f"evidence:{self.mode}:{as_of.isoformat()}",),
            strengthened_indicators=strengthened,
            weakened_indicators=weakened,
            triggered_invalidation_conditions=invalidations,
            data_current=data_current,
            performance_since_approval=0.01,
            best_replacement_expected_return=replacement,
            next_review_at=as_of + timedelta(days=30),
        )


class Publisher:
    def __init__(self) -> None:
        self.items = []

    def publish(self, item):
        self.items.append(item)
        return f"notification:{item.identifier}"


def _journal(tmp_path, *, count: int = 1):
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    theses = []
    for index in range(count):
        candidate = build_candidate(symbol=f"ACM{index}")
        decision = build_decision(candidate)
        thesis = LivingThesis.from_decision(candidate, decision)
        journal.append_thesis_snapshot(thesis)
        theses.append(thesis)
    journal.append_opportunity_queue(build_queue(), occurred_at=AS_OF)
    return journal, tuple(theses)


def _orchestrator(tmp_path, journal, provider, publisher=None):
    store = SQLiteThesisMonitoringStore(tmp_path / "monitoring.db")
    return ThesisMonitoringOrchestrator(
        journal=journal,
        store=store,
        evidence_provider=provider,
        notification_publisher=publisher,
    ), store


def test_scheduled_stable_review_updates_snapshot_without_alert(tmp_path):
    journal, (thesis,) = _journal(tmp_path)
    provider = EvidenceProvider()
    publisher = Publisher()
    orchestrator, store = _orchestrator(tmp_path, journal, provider, publisher)

    result = orchestrator.run(as_of=RUN_AT)

    assert result.all_success
    assert result.results[0].status == "completed"
    assert result.results[0].required_cio_review is False
    assert publisher.items == []
    latest = journal.latest(
        aggregate_identifier=thesis.identifier,
        event_type=CIOJournalEventType.THESIS_SNAPSHOT,
    )
    assert latest.payload["state"] == ThesisState.STABLE.value
    assert latest.payload["review_count"] == 1
    assert store.has_event(
        trigger_identifier=result.results[0].trigger_identifier,
        event_type=ThesisMonitoringEventType.NOTIFICATION_SUPPRESSED,
    )
    assert provider.contexts[0]["context_identifier"]


def test_invalidation_queues_urgent_cio_review_and_notifies(tmp_path):
    journal, (thesis,) = _journal(tmp_path)
    provider = EvidenceProvider(mode="invalidate")
    publisher = Publisher()
    orchestrator, store = _orchestrator(tmp_path, journal, provider, publisher)

    result = orchestrator.run(as_of=RUN_AT)

    item = publisher.items[0]
    assert result.results[0].required_cio_review is True
    assert item.priority is ThesisReviewPriority.URGENT
    assert item.thesis_identifier == thesis.identifier
    assert journal.latest(
        aggregate_identifier=thesis.identifier,
        event_type=CIOJournalEventType.THESIS_SNAPSHOT,
    ).payload["state"] == ThesisState.INVALIDATED.value
    assert store.has_event(
        trigger_identifier=result.results[0].trigger_identifier,
        event_type=ThesisMonitoringEventType.REVIEW_QUEUED,
    )


def test_event_trigger_runs_before_scheduled_deadline(tmp_path):
    journal, (thesis,) = _journal(tmp_path)
    provider = EvidenceProvider(mode="replacement")
    orchestrator, _ = _orchestrator(tmp_path, journal, provider)
    event_at = AS_OF + timedelta(days=2)
    trigger = ThesisMonitoringTrigger(
        identifier="trigger:event:replacement",
        thesis_identifier=thesis.identifier,
        source=ThesisTriggerSource.EVENT,
        as_of=event_at,
        reason="A superior qualified replacement emerged.",
        evidence_fingerprint="replacement-evidence-v1",
        priority=ThesisReviewPriority.HIGH,
    )

    result = orchestrator.run(
        as_of=event_at,
        event_triggers=(trigger,),
        include_scheduled=False,
    )

    assert result.results[0].required_cio_review is True
    review = journal.latest(
        aggregate_identifier=thesis.identifier,
        event_type=CIOJournalEventType.THESIS_REVIEW,
    )
    assert review.payload["proposal"] == "review_reduce"


def test_no_due_thesis_and_no_event_produces_no_work(tmp_path):
    journal, _ = _journal(tmp_path)
    provider = EvidenceProvider()
    orchestrator, store = _orchestrator(tmp_path, journal, provider)

    result = orchestrator.run(as_of=AS_OF + timedelta(days=1))

    assert result.results == ()
    assert provider.calls == 0
    assert store.events() == ()


def test_duplicate_trigger_replays_without_provider_or_notification_duplication(tmp_path):
    journal, (thesis,) = _journal(tmp_path)
    provider = EvidenceProvider(mode="invalidate")
    publisher = Publisher()
    orchestrator, _ = _orchestrator(tmp_path, journal, provider, publisher)
    trigger = ThesisMonitoringTrigger(
        identifier="trigger:event:invalidate",
        thesis_identifier=thesis.identifier,
        source=ThesisTriggerSource.EVENT,
        as_of=AS_OF + timedelta(days=2),
        reason="Invalidation evidence appeared.",
        evidence_fingerprint="invalid-v1",
        priority=ThesisReviewPriority.URGENT,
    )

    first = orchestrator.run(as_of=trigger.as_of, event_triggers=(trigger,), include_scheduled=False)
    second = orchestrator.run(as_of=trigger.as_of, event_triggers=(trigger,), include_scheduled=False)

    assert first.results[0].review_identifier == second.results[0].review_identifier
    assert provider.calls == 1
    assert len(publisher.items) == 1
    assert journal.count() == 4  # thesis, queue, review, updated thesis


def test_same_evidence_fingerprint_is_suppressed_inside_window(tmp_path):
    journal, (thesis,) = _journal(tmp_path)
    provider = EvidenceProvider()
    orchestrator, store = _orchestrator(tmp_path, journal, provider)
    first = ThesisMonitoringTrigger(
        identifier="trigger:event:first",
        thesis_identifier=thesis.identifier,
        source=ThesisTriggerSource.EVENT,
        as_of=AS_OF + timedelta(days=2),
        reason="Event evidence.",
        evidence_fingerprint="same-evidence",
    )
    second = replace(first, identifier="trigger:event:second", as_of=first.as_of + timedelta(hours=1))

    orchestrator.run(as_of=first.as_of, event_triggers=(first,), include_scheduled=False)
    result = orchestrator.run(as_of=second.as_of, event_triggers=(second,), include_scheduled=False)

    assert result.results[0].status == "deduplicated"
    assert provider.calls == 1
    assert store.has_event(
        trigger_identifier=second.identifier,
        event_type=ThesisMonitoringEventType.DEDUPLICATED,
    )


def test_provider_failure_isolated_and_writes_no_thesis_review(tmp_path):
    journal, theses = _journal(tmp_path, count=2)
    stable = EvidenceProvider()

    class MixedProvider:
        def update_for(self, thesis, *, as_of, opportunity_context):
            if thesis.identifier == theses[0].identifier:
                raise RuntimeError("first failed")
            return stable.update_for(thesis, as_of=as_of, opportunity_context=opportunity_context)

    orchestrator, store = _orchestrator(tmp_path, journal, MixedProvider())
    result = orchestrator.run(as_of=RUN_AT)

    assert len(result.failures) == 1
    assert sum(item.status == "completed" for item in result.results) == 1
    assert journal.latest(
        aggregate_identifier=theses[0].identifier,
        event_type=CIOJournalEventType.THESIS_REVIEW,
    ) is None
    assert store.has_event(
        trigger_identifier=result.failures[0].trigger_identifier,
        event_type=ThesisMonitoringEventType.REVIEW_FAILED,
    )


def test_missing_thesis_trigger_fails_cleanly(tmp_path):
    journal, _ = _journal(tmp_path)
    orchestrator, _ = _orchestrator(tmp_path, journal, EvidenceProvider())
    trigger = ThesisMonitoringTrigger(
        identifier="trigger:missing",
        thesis_identifier="thesis:missing",
        source=ThesisTriggerSource.EVENT,
        as_of=RUN_AT,
        reason="Test missing thesis.",
        evidence_fingerprint="missing",
    )
    result = orchestrator.run(as_of=RUN_AT, event_triggers=(trigger,), include_scheduled=False)
    assert result.failures[0].error == "thesis snapshot is unavailable"


def test_corrupt_journal_blocks_entire_monitoring_cycle(tmp_path):
    journal, _ = _journal(tmp_path)
    orchestrator, _ = _orchestrator(tmp_path, journal, EvidenceProvider())
    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER cio_journal_prevent_update")
        connection.execute("UPDATE cio_journal_events SET payload_json = '{}' WHERE sequence = 1")
    with pytest.raises(CIOJournalIntegrityError):
        orchestrator.run(as_of=RUN_AT)


def test_monitoring_store_is_append_only_and_tamper_evident(tmp_path):
    journal, _ = _journal(tmp_path)
    orchestrator, store = _orchestrator(tmp_path, journal, EvidenceProvider())
    orchestrator.run(as_of=RUN_AT)
    assert store.verify_integrity()
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM thesis_monitoring_events")
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER thesis_monitoring_prevent_update")
        connection.execute("UPDATE thesis_monitoring_events SET payload_json = '{}' WHERE sequence = 1")
    with pytest.raises(Exception):
        store.verify_integrity()
