"""Production-hardened SQLite screening persistence.

The governed screening history remains append-only and fail-closed.  This
adapter only changes SQLite concurrency behavior so readers and independent
production processes do not cause transient lock errors to terminate the
critical paper-operator process.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from screening.orchestration import (
    SQLiteFullUniverseScreeningStore as _SQLiteFullUniverseScreeningStore,
    ScreeningEvent,
    ScreeningEventType,
)


def _flush_and_advise_file_cache_dontneed(path: Path) -> bool:
    """Make committed SQLite pages clean, then advise their cache as reclaimable.

    Terminal screening uses WAL mode in production.  The base screening store already
    releases the main database while verifying historical payloads, but newly committed
    terminal-screening rows can remain charged to the service cgroup through the WAL.
    Flushing before POSIX_FADV_DONTNEED makes those committed pages eligible for reclaim
    without deleting or rewriting any screening evidence.  Unsupported filesystem/kernel
    behavior is advisory only; the unchanged outer memory guard remains fail-closed.
    """

    posix_fadvise = getattr(os, "posix_fadvise", None)
    advice = getattr(os, "POSIX_FADV_DONTNEED", None)
    fsync = getattr(os, "fsync", None)
    if (
        posix_fadvise is None
        or advice is None
        or not callable(fsync)
        or not path.is_file()
    ):
        return False
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        try:
            fsync(descriptor)
            posix_fadvise(descriptor, 0, 0, advice)
        except OSError:
            return False
        return True
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


class SQLiteFullUniverseScreeningStore(_SQLiteFullUniverseScreeningStore):
    """Append-only screening store with bounded SQLite lock resilience."""

    _BUSY_TIMEOUT_SECONDS = 10.0
    _LOCK_RETRY_DELAYS_SECONDS = (0.25, 0.75)

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)

    def _connect(self) -> sqlite3.Connection:
        # Preserve the base store's memory-bounded SQLite configuration
        # (file-backed temp storage, bounded page cache, and mmap disabled),
        # then layer production concurrency protections on top.
        connection = super()._connect()
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

    def _release_committed_file_cache(self) -> None:
        """Release durable screening DB/WAL cache immediately after a successful commit.

        The WAL is advised first because it owns the newest committed pages.  The database
        follows for pages dirtied by checkpoints or integrity reads.  Both files stay on
        disk and every failure is fail-soft; resource admission remains solely with the
        existing governed memory guard.
        """

        for path in (Path(f"{self.path}-wal"), self.path):
            try:
                _flush_and_advise_file_cache_dontneed(path)
            except Exception:  # noqa: BLE001 - cache advice has no screening authority.
                pass

    def _append_values(
        self,
        values: Iterable[
            tuple[str, str, ScreeningEventType, datetime, Mapping[str, Any]]
        ],
        *,
        retain_events: bool,
    ) -> tuple[ScreeningEvent, ...] | int:
        """Persist canonically, then release only cache owned by the committed write."""

        result = super()._append_values(values, retain_events=retain_events)
        self._release_committed_file_cache()
        return result

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
