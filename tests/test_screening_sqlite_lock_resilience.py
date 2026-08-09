from datetime import datetime, timezone

from screening import SQLiteFullUniverseScreeningStore, ScreeningEventType


def test_screening_append_commits_while_reader_transaction_is_open(tmp_path):
    store = SQLiteFullUniverseScreeningStore(tmp_path / "full_universe_screening.db")

    reader = store._connect()
    try:
        journal_mode = reader.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).lower() == "wal"

        reader.execute("BEGIN")
        reader.execute(
            "SELECT * FROM full_universe_screening_events ORDER BY sequence"
        ).fetchall()

        occurred_at = datetime(2026, 8, 9, 2, 51, tzinfo=timezone.utc)
        events = store.append_many(
            (
                (
                    "screening:test-cycle:start",
                    "test-cycle",
                    ScreeningEventType.CYCLE_STARTED,
                    occurred_at,
                    {"state": "started"},
                ),
            )
        )

        assert len(events) == 1
        assert events[0].event_identifier == "screening:test-cycle:start"
        assert store.verify_integrity() is None
    finally:
        reader.rollback()
        reader.close()
