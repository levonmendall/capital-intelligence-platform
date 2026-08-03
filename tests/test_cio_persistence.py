"""Tests for canonical CIO append-only and hash-chained persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import timedelta

import pytest

from cio.persistence import (
    CIOJournalEventType,
    CIOJournalIntegrityError,
    SQLiteCIOJournal,
    serialize_candidate_decision,
    serialize_cio_decision,
    serialize_specialist_packet,
)
from tests.cio_test_fixtures import (
    AS_OF,
    build_candidate,
    build_decision,
    build_queue,
    build_specialist_packet,
)
from thesis import LivingThesis, ThesisEvidenceUpdate, ThesisMonitor


def _workflow():
    candidate = build_candidate()
    queue = build_queue(candidate)
    packet = build_specialist_packet(candidate)
    decision = build_decision(candidate)
    thesis = LivingThesis.from_decision(candidate, decision)
    update = ThesisEvidenceUpdate(
        thesis_identifier=thesis.identifier,
        as_of=AS_OF + timedelta(days=1),
        expected_return=thesis.expected_return + 0.04,
        expected_downside=thesis.expected_downside,
        confidence=min(1.0, thesis.current_confidence + 0.05),
        evidence_identifiers=("evidence:thesis-review",),
        strengthened_indicators=("Forward revisions accelerated",),
        weakened_indicators=(),
        triggered_invalidation_conditions=(),
        data_current=True,
        performance_since_approval=0.02,
        best_replacement_expected_return=0.04,
        next_review_at=AS_OF + timedelta(days=31),
    )
    review = ThesisMonitor().evaluate(thesis, update)
    updated_thesis = thesis.apply(review)
    return candidate, queue, packet, decision, thesis, review, updated_thesis


def _journal(tmp_path) -> SQLiteCIOJournal:
    recorded_at = AS_OF + timedelta(days=2)
    return SQLiteCIOJournal(
        tmp_path / "institutional_journal.db",
        clock=lambda: recorded_at,
    )


def test_complete_cio_workflow_is_hash_chained_and_replayable(tmp_path) -> None:
    candidate, queue, packet, decision, thesis, review, updated = _workflow()
    journal = _journal(tmp_path)

    events = (
        journal.append_candidate(candidate, code_version="commit-1"),
        journal.append_opportunity_queue(
            queue,
            occurred_at=candidate.as_of,
            code_version="commit-1",
        ),
        journal.append_specialist_packet(
            packet,
            occurred_at=max(item.completed_at for item in packet.analyses),
            code_version="commit-1",
        ),
        journal.append_decision(decision, code_version="commit-1"),
        journal.append_thesis_snapshot(thesis, code_version="commit-1"),
        journal.append_thesis_review(review, code_version="commit-2"),
        journal.append_thesis_snapshot(updated, code_version="commit-2"),
    )

    assert [item.sequence for item in events] == list(range(1, 8))
    assert events[0].previous_hash == "0" * 64
    assert all(
        current.previous_hash == previous.content_hash
        for previous, current in zip(events, events[1:])
    )
    assert journal.count() == 7
    assert journal.verify_integrity()
    assert journal.latest().event_type is CIOJournalEventType.THESIS_SNAPSHOT
    assert [
        item.event_type
        for item in journal.events(aggregate_identifier=thesis.identifier)
    ] == [
        CIOJournalEventType.THESIS_SNAPSHOT,
        CIOJournalEventType.THESIS_REVIEW,
        CIOJournalEventType.THESIS_SNAPSHOT,
    ]


def test_exact_candidate_append_is_idempotent(tmp_path) -> None:
    candidate = build_candidate()
    journal = _journal(tmp_path)

    first = journal.append_candidate(candidate, code_version="commit-1")
    second = journal.append_candidate(candidate, code_version="commit-1")

    assert first == second
    assert journal.count() == 1


def test_event_identifier_cannot_be_reused_for_different_content(tmp_path) -> None:
    candidate = build_candidate()
    journal = _journal(tmp_path)
    journal.append_candidate(candidate, code_version="commit-1")

    changed = replace(candidate, current_price=101.0)
    with pytest.raises(ValueError, match="different content"):
        journal.append_candidate(changed, code_version="commit-1")


def test_database_triggers_block_update_and_delete(tmp_path) -> None:
    candidate = build_candidate()
    journal = _journal(tmp_path)
    journal.append_candidate(candidate, code_version="commit-1")

    with sqlite3.connect(journal.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE cio_journal_events SET payload_json = '{}' WHERE sequence = 1"
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM cio_journal_events WHERE sequence = 1"
            )


def test_hash_verification_detects_out_of_band_tampering(tmp_path) -> None:
    candidate = build_candidate()
    journal = _journal(tmp_path)
    journal.append_candidate(candidate, code_version="commit-1")

    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER cio_journal_prevent_update")
        connection.execute(
            "UPDATE cio_journal_events SET payload_json = '{}' WHERE sequence = 1"
        )
        connection.commit()

    with pytest.raises(CIOJournalIntegrityError, match="content hash"):
        journal.verify_integrity()


def test_candidate_serializer_preserves_quantitative_lineage() -> None:
    candidate = build_candidate()

    payload = serialize_candidate_decision(
        candidate,
        code_version="commit-1",
    )

    assert payload["code_version"] == "commit-1"
    assert payload["scenarios"]["probability_weighted_expected_return"] == (
        candidate.probability_weighted_expected_return
    )
    assert payload["net_expected_return"] == candidate.net_expected_return
    assert payload["opportunity_edge"] == candidate.opportunity_edge
    assert payload["evidence_identifiers"] == list(
        candidate.evidence_identifiers
    )
    assert payload["model_versions"] == list(candidate.model_versions)
    assert payload["evidence_quality"]["confidence_ceiling"] == (
        candidate.evidence_quality.ceiling
    )


def test_specialist_and_decision_serializers_preserve_authority_and_dissent() -> None:
    candidate = build_candidate()
    packet = build_specialist_packet(candidate)
    decision = build_decision(candidate)

    packet_payload = serialize_specialist_packet(
        packet,
        code_version="commit-1",
    )
    decision_payload = serialize_cio_decision(
        decision,
        code_version="commit-1",
    )

    assert len(packet_payload["analyses"]) == 6
    assert all(
        item["independent_first_pass"]
        for item in packet_payload["analyses"]
    )
    portfolio_analysis = next(
        item
        for item in packet_payload["analyses"]
        if item["role"] == "portfolio_risk_manager"
    )
    assert portfolio_analysis["recommended_position_weight"] == pytest.approx(
        0.06
    )
    assert decision_payload["action"] == "buy"
    assert decision_payload["recommended_position_weight"] == pytest.approx(
        0.06
    )
    assert (
        decision_payload["policy_version"]
        == "cio-synthesis.v9-independent-evidence"
    )


def test_event_payload_is_canonical_json(tmp_path) -> None:
    journal = _journal(tmp_path)
    event = journal.append(
        event_type=CIOJournalEventType.CANDIDATE_DECISION,
        aggregate_identifier="candidate:test",
        occurred_at=AS_OF,
        payload={"z": 1, "a": {"y": 2, "x": 1}},
        schema_version="test.v1",
        event_identifier="event:test",
    )

    assert event.payload_json == '{"a":{"x":1,"y":2},"z":1}'
    assert json.loads(event.payload_json) == {
        "a": {"x": 1, "y": 2},
        "z": 1,
    }


def test_event_filters_return_only_requested_type(tmp_path) -> None:
    candidate, _, packet, decision, _, _, _ = _workflow()
    journal = _journal(tmp_path)
    journal.append_candidate(candidate, code_version="commit-1")
    journal.append_specialist_packet(
        packet,
        occurred_at=max(item.completed_at for item in packet.analyses),
        code_version="commit-1",
    )
    journal.append_decision(decision, code_version="commit-1")

    decisions = journal.events(event_type=CIOJournalEventType.CIO_DECISION)

    assert len(decisions) == 1
    assert decisions[0].payload["action"] == "buy"
