from __future__ import annotations

from screening.resilient_store import SQLiteFullUniverseScreeningStore


def test_resilient_store_preserves_memory_and_concurrency_pragmas(tmp_path) -> None:
    store = SQLiteFullUniverseScreeningStore(tmp_path / "screening.sqlite3")

    with store._connect() as connection:
        temp_store = connection.execute("PRAGMA temp_store").fetchone()[0]
        cache_size = connection.execute("PRAGMA cache_size").fetchone()[0]
        mmap_size = connection.execute("PRAGMA mmap_size").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

    assert temp_store == 1  # FILE
    assert cache_size == -store._SQLITE_CACHE_KIB
    assert mmap_size == 0
    assert busy_timeout == int(store._BUSY_TIMEOUT_SECONDS * 1000)
    assert str(journal_mode).lower() == "wal"
    assert synchronous == 1  # NORMAL
