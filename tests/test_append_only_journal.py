"""Tests for the tamper-evident institutional journal."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from evaluation import (
    DecisionOutcome,
    DecisionQualityReview,
    ProcessVerdict,
)
from intelligence.regime_pipeline import (
    InstitutionalRegimePipeline,
)
from journal import (
    JournalEventType,
    JournalIntegrityError,
    SQLiteAppendOnlyJournal,
)
from tests.test_regime_pipeline import AS_OF, FakeRegimeProvider


RECORDED_AT = datetime(
    2026,
    2,
    1,
    12,
    tzinfo=timezone.utc,
)


def _journal(tmp_path) -> SQLiteAppendOnlyJournal:
    identifiers = iter(
        [
            "event-regime-1",
            "event-review-1",
            "event-generic-1",
        ]
    )
    return SQLiteAppendOnlyJournal(
        tmp_path / "institutional-journal.db",
        clock=lambda: RECORDED_AT,
        identifier_factory=lambda: next(identifiers),
    )


def _regime_run():
    return InstitutionalRegimePipeline(
        FakeRegimeProvider()
    ).run(as_of=AS_OF)


def _review() -> DecisionQualityReview:
    return DecisionQualityReview(
        decision_identifier="decision-42",
        reviewed_at=datetime(
            2026,
            4,
            30,
            12,
            tzinfo=timezone.utc,
        ),
        process_verdict=ProcessVerdict.DISCIPLINED,
        outcome=DecisionOutcome.NEGATIVE,
        process_evidence=(
            "Evidence was point-in-time complete.",
        ),
        outcome_evidence=(
            "The position lost 8 percent.",
        ),
        lessons=(
            "Retain the process and revisit sizing.",
        ),
        reviewer="investment-committee",
    )


def test_regime_run_round_trips_complete_lineage(
    tmp_path,
) -> None:
    journal = _journal(tmp_path)

    appended = journal.append_regime_run(
        _regime_run(),
        run_identifier="regime-run-42",
        code_version="test-commit-sha",
    )
    recovered = journal.events()[0]
    payload = recovered.payload

    assert appended == recovered
    assert recovered.sequence == 1
    assert (
        recovered.event_type is JournalEventType.REGIME_RUN
    )
    assert recovered.schema_version == "regime-run.v1"
    assert recovered.aggregate_identifier == "regime-run-42"
    assert payload["evidence"]["rules_version"] == "fred-us-v1"
    assert payload["code_version"] == "test-commit-sha"
    assert payload["classification"]["regime"] == "Goldilocks"
    assert payload["loaded_count"] == 5
    assert len(payload["loads"]) == 5
    growth = next(
        signal
        for signal in payload["evidence"]["signals"]
        if signal["name"] == "growth"
    )
    assert {
        item["series_identifier"]
        for item in growth["lineage"]
    } == {"INDPRO"}
    assert journal.verify_integrity()


def test_payload_property_returns_a_fresh_copy(tmp_path) -> None:
    journal = _journal(tmp_path)
    event = journal.append_regime_run(_regime_run())

    mutated = event.payload
    mutated["provider"] = "tampered-in-memory"

    assert event.payload["provider"] == "FRED"
    assert journal.events()[0].payload["provider"] == "FRED"


def test_quality_review_links_to_decision_and_hash_chain(
    tmp_path,
) -> None:
    journal = _journal(tmp_path)
    regime_event = journal.append_regime_run(_regime_run())
    review_event = journal.append_decision_quality_review(
        _review()
    )

    assert review_event.sequence == 2
    assert review_event.previous_hash == (
        regime_event.content_hash
    )
    assert review_event.aggregate_identifier == (
        "decision:decision-42"
    )
    assert review_event.event_type is (
        JournalEventType.DECISION_QUALITY_REVIEW
    )
    assert review_event.payload["classification"] == (
        "disciplined_negative"
    )
    assert journal.verify_integrity()


def test_database_triggers_reject_update_and_delete(
    tmp_path,
) -> None:
    journal = _journal(tmp_path)
    journal.append_regime_run(_regime_run())

    with sqlite3.connect(journal.path) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="append-only",
        ):
            connection.execute(
                """
                UPDATE journal_events
                SET payload_json = '{}'
                WHERE sequence = 1
                """
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="append-only",
        ):
            connection.execute(
                "DELETE FROM journal_events WHERE sequence = 1"
            )

    assert journal.verify_integrity()


def test_hash_chain_detects_out_of_band_tampering(
    tmp_path,
) -> None:
    journal = _journal(tmp_path)
    journal.append_regime_run(_regime_run())

    with sqlite3.connect(journal.path) as connection:
        connection.execute(
            "DROP TRIGGER journal_events_prevent_update"
        )
        connection.execute(
            """
            UPDATE journal_events
            SET payload_json = '{"tampered":true}'
            WHERE sequence = 1
            """
        )

    assert not journal.verify_integrity()
    with pytest.raises(JournalIntegrityError):
        journal.require_integrity()


def test_events_can_be_filtered_by_aggregate(tmp_path) -> None:
    journal = _journal(tmp_path)
    journal.append_regime_run(
        _regime_run(),
        run_identifier="regime-run-42",
    )
    journal.append_decision_quality_review(_review())

    events = journal.events(
        aggregate_identifier="decision:decision-42"
    )

    assert len(events) == 1
    assert events[0].sequence == 2


def test_payload_rejects_non_json_numbers(tmp_path) -> None:
    journal = _journal(tmp_path)

    with pytest.raises(
        ValueError,
        match="finite JSON-serializable",
    ):
        journal.append(
            event_type=JournalEventType.REGIME_RUN,
            aggregate_identifier="invalid",
            occurred_at=AS_OF,
            payload={"confidence": float("nan")},
        )
