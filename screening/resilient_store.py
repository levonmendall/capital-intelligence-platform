"""Production-hardened SQLite screening persistence.

The governed screening history remains append-only and fail-closed.  This
adapter only changes SQLite concurrency behavior so readers and independent
production processes do not cause transient lock errors to terminate the
critical paper-operator process.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Mapping
from datetime import datetime

from screening.orchestration import (
    SQLiteFullUniverseScreeningStore as _SQLiteFullUniverseScreeningStore,
    ScreeningEvent,
    ScreeningEventType,
)


class SQLiteFullUniverseScreeningStore(_SQLiteFullUniverseScreeningStore):
    """Append-only screening store with bounded SQLite lock resilience."""

    _BUSY_TIMEOUT_SECONDS = 10.0
    _LOCK_RETRY_DELAYS_SECONDS = (0.25, 0.75)

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self._BUSY_TIMEOUT_SECONDS,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            f"PRAGMA busy_timeout = {int(self._BUSY_TIMEOUT_SECONDS * 1000)}"
        )
        # WAL prevents ordinary readers from blocking a writer's commit while
        # BEGIN IMMEDIATE continues to serialize the append-only hash chain.
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @staticmethod
    def _transient_lock(error: sqlite3.OperationalError) -> bool:
        detail = str(error).lower()
        return "database is locked" in detail or "database is busy" in detail

    def append_many(
        self,
        values: tuple[
            tuple[str, str, ScreeningEventType, datetime, Mapping[str, Any]], ...
        ],
    ) -> tuple[ScreeningEvent, ...]:
        for attempt, delay in enumerate(
            (*self._LOCK_RETRY_DELAYS_SECONDS, None),
            start=1,
        ):
            try:
                return super().append_many(values)
            except sqlite3.OperationalError as error:
                if not self._transient_lock(error) or delay is None:
                    raise
                # The base transaction rolls back before propagating. Retrying
                # the entire idempotent append preserves chain integrity and
                # never suppresses a persistent database failure.
                time.sleep(delay)
        raise AssertionError("unreachable SQLite screening retry state")
