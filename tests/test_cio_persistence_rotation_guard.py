from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from portfolio.global_rotation_persistence import SQLiteGlobalRotationStore

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def test_global_rotation_store_preserves_canonical_cio_journal_contract(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SQLiteCIOJournal(path)
    required_methods = (
        "append",
        "append_candidate",
        "append_opportunity_queue",
        "append_specialist_packet",
        "append_decision",
        "append_thesis_snapshot",
        "append_thesis_review",
        "events",
        "latest",
        "prior_decision_contexts",
        "active_theses",
        "verify_integrity",
        "count",
    )
    assert all(callable(getattr(journal, name, None)) for name in required_methods)

    journal.append(
        event_type=CIOJournalEventType.DAILY_CIO_BRIEFING,
        aggregate_identifier="cycle:before-rotation-store",
        occurred_at=NOW,
        payload={"phase": "before"},
        schema_version="persistence-guard.v1",
        event_identifier="event:persistence-guard:before",
    )
    assert journal.verify_integrity() is True

    rotation_store = SQLiteGlobalRotationStore(path)
    assert journal.verify_integrity() is True
    assert rotation_store.verify_integrity() is True

    journal.append(
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
        aggregate_identifier="cycle:after-rotation-store",
        occurred_at=NOW + timedelta(seconds=1),
        payload={"phase": "after"},
        schema_version="persistence-guard.v1",
        event_identifier="event:persistence-guard:after",
    )
    assert journal.count() == 2
    assert journal.verify_integrity() is True
    assert rotation_store.verify_integrity() is True
