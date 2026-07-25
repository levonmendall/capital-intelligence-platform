"""SQLite persistence for idempotent cycles, preferences, and alert delivery."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from delivery.models import (
    AlertPreference,
    AlertTopic,
    CycleRecord,
    CycleStatus,
    DeliveryChannel,
    DeliveryRecord,
    DeliveryStatus,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SQLiteDeliveryStore:
    """Durable queue with unique cycle and delivery deduplication keys."""

    def __init__(self, path: str | Path, *, clock=_utc_now) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._initialize()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scheduled_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    market_date TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    snapshot_identifier TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS alert_preferences (
                    user_id TEXT PRIMARY KEY,
                    investor_identifier TEXT NOT NULL,
                    timezone_name TEXT NOT NULL,
                    delivery_time TEXT NOT NULL,
                    enabled_topics_json TEXT NOT NULL,
                    channels_json TEXT NOT NULL,
                    email_address TEXT,
                    conviction_threshold INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    deduplication_key TEXT NOT NULL UNIQUE,
                    cycle_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    investor_identifier TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    status TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    sent_at TEXT,
                    acknowledged_at TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_delivery_pending
                ON alert_deliveries(status, next_attempt_at);
                CREATE INDEX IF NOT EXISTS idx_delivery_user
                ON alert_deliveries(user_id, created_at DESC);
                CREATE TRIGGER IF NOT EXISTS prevent_delivery_delete
                BEFORE DELETE ON alert_deliveries
                BEGIN SELECT RAISE(ABORT, 'delivery history is append-preserving'); END;
                """
            )

    def acquire_cycle(self, market_date: str, *, stale_after: timedelta = timedelta(hours=2)) -> CycleRecord | None:
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_cycles WHERE market_date = ?",
                (market_date,),
            ).fetchone()
            if row is not None:
                existing = self._cycle(row)
                if existing.status is CycleStatus.COMPLETED:
                    return None
                if existing.status is CycleStatus.RUNNING and now - existing.updated_at < stale_after:
                    return None
                cycle_id = existing.cycle_id
                connection.execute(
                    """UPDATE scheduled_cycles SET status=?, started_at=?, updated_at=?,
                       completed_at=NULL, snapshot_identifier=NULL, error=NULL WHERE cycle_id=?""",
                    (CycleStatus.RUNNING.value, now.isoformat(), now.isoformat(), cycle_id),
                )
            else:
                cycle_id = f"scheduled-cycle:{uuid4()}"
                connection.execute(
                    "INSERT INTO scheduled_cycles VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL)",
                    (cycle_id, market_date, CycleStatus.RUNNING.value, now.isoformat(), now.isoformat()),
                )
        return self.get_cycle(cycle_id)

    def complete_cycle(self, cycle_id: str, snapshot_identifier: str) -> CycleRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE scheduled_cycles SET status=?, updated_at=?, completed_at=?,
                   snapshot_identifier=?, error=NULL WHERE cycle_id=?""",
                (CycleStatus.COMPLETED.value, now.isoformat(), now.isoformat(), snapshot_identifier, cycle_id),
            )
        return self.get_cycle(cycle_id)

    def fail_cycle(self, cycle_id: str, error: str) -> CycleRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE scheduled_cycles SET status=?, updated_at=?, error=? WHERE cycle_id=?",
                (CycleStatus.FAILED.value, now.isoformat(), str(error)[:2000], cycle_id),
            )
        return self.get_cycle(cycle_id)

    def get_cycle(self, cycle_id: str) -> CycleRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM scheduled_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
        if row is None:
            raise KeyError(cycle_id)
        return self._cycle(row)

    def set_preference(self, preference: AlertPreference) -> AlertPreference:
        now = self._now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO alert_preferences VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET investor_identifier=excluded.investor_identifier,
                   timezone_name=excluded.timezone_name, delivery_time=excluded.delivery_time,
                   enabled_topics_json=excluded.enabled_topics_json, channels_json=excluded.channels_json,
                   email_address=excluded.email_address, conviction_threshold=excluded.conviction_threshold,
                   updated_at=excluded.updated_at""",
                (
                    preference.user_id,
                    preference.investor_identifier,
                    preference.timezone_name,
                    preference.delivery_time.isoformat(timespec="minutes"),
                    json.dumps(sorted(item.value for item in preference.enabled_topics)),
                    json.dumps(sorted(item.value for item in preference.channels)),
                    preference.email_address,
                    preference.conviction_threshold,
                    now,
                ),
            )
        return preference

    def preference(self, user_id: str) -> AlertPreference | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM alert_preferences WHERE user_id=?", (user_id,)).fetchone()
        return None if row is None else self._preference(row)

    def preferences(self) -> tuple[AlertPreference, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM alert_preferences ORDER BY user_id").fetchall()
        return tuple(self._preference(row) for row in rows)

    def enqueue(self, *, deduplication_key: str, cycle_id: str, user_id: str,
                investor_identifier: str, topic: AlertTopic, channel: DeliveryChannel,
                headline: str, explanation: str, status: DeliveryStatus = DeliveryStatus.PENDING) -> DeliveryRecord:
        now = self._now()
        delivery_id = f"delivery:{uuid4()}"
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO alert_deliveries
                   (delivery_id,deduplication_key,cycle_id,user_id,investor_identifier,topic,channel,status,
                    headline,explanation,attempts,next_attempt_at,created_at,updated_at,sent_at,acknowledged_at,last_error)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,NULL,NULL)""",
                (delivery_id, deduplication_key, cycle_id, user_id, investor_identifier,
                 topic.value, channel.value, status.value, headline, explanation,
                 now.isoformat() if status is DeliveryStatus.PENDING else None,
                 now.isoformat(), now.isoformat(), None),
            )
            row = connection.execute(
                "SELECT * FROM alert_deliveries WHERE deduplication_key=?", (deduplication_key,)
            ).fetchone()
        return self._delivery(row)

    def due(self, *, limit: int = 100) -> tuple[DeliveryRecord, ...]:
        now = self._now().isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM alert_deliveries WHERE status IN (?,?)
                   AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY created_at LIMIT ?""",
                (DeliveryStatus.PENDING.value, DeliveryStatus.FAILED.value, now, limit),
            ).fetchall()
        return tuple(self._delivery(row) for row in rows)

    def mark_sent(self, delivery_id: str) -> DeliveryRecord:
        now = self._now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """UPDATE alert_deliveries SET status=?, attempts=attempts+1, updated_at=?, sent_at=?,
                   next_attempt_at=NULL, last_error=NULL WHERE delivery_id=?""",
                (DeliveryStatus.SENT.value, now, now, delivery_id),
            )
        return self.get_delivery(delivery_id)

    def mark_failed(self, delivery_id: str, error: str, *, retry_after: timedelta) -> DeliveryRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE alert_deliveries SET status=?, attempts=attempts+1, updated_at=?,
                   next_attempt_at=?, last_error=? WHERE delivery_id=?""",
                (DeliveryStatus.FAILED.value, now.isoformat(), (now + retry_after).isoformat(), str(error)[:2000], delivery_id),
            )
        return self.get_delivery(delivery_id)

    def acknowledge(self, delivery_id: str, *, user_id: str) -> DeliveryRecord:
        now = self._now().isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE alert_deliveries SET status=?, acknowledged_at=?, updated_at=?
                   WHERE delivery_id=? AND user_id=? AND status=?""",
                (DeliveryStatus.ACKNOWLEDGED.value, now, now, delivery_id, user_id, DeliveryStatus.SENT.value),
            )
        if cursor.rowcount != 1:
            raise KeyError(delivery_id)
        return self.get_delivery(delivery_id)

    def history(self, *, user_id: str, limit: int = 100) -> tuple[DeliveryRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alert_deliveries WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return tuple(self._delivery(row) for row in rows)

    def get_delivery(self, delivery_id: str) -> DeliveryRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM alert_deliveries WHERE delivery_id=?", (delivery_id,)).fetchone()
        if row is None:
            raise KeyError(delivery_id)
        return self._delivery(row)

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1 FROM scheduled_cycles LIMIT 1").fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"delivery store unavailable: {error}"
        return True, "delivery store ready"

    def _preference(self, row: sqlite3.Row) -> AlertPreference:
        from datetime import time
        return AlertPreference(
            user_id=row["user_id"], investor_identifier=row["investor_identifier"],
            timezone_name=row["timezone_name"], delivery_time=time.fromisoformat(row["delivery_time"]),
            enabled_topics=frozenset(AlertTopic(item) for item in json.loads(row["enabled_topics_json"])),
            channels=frozenset(DeliveryChannel(item) for item in json.loads(row["channels_json"])),
            email_address=row["email_address"], conviction_threshold=int(row["conviction_threshold"]),
        )

    def _cycle(self, row: sqlite3.Row) -> CycleRecord:
        return CycleRecord(
            cycle_id=row["cycle_id"], market_date=row["market_date"], status=CycleStatus(row["status"]),
            started_at=datetime.fromisoformat(row["started_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=None if row["completed_at"] is None else datetime.fromisoformat(row["completed_at"]),
            snapshot_identifier=row["snapshot_identifier"], error=row["error"],
        )

    def _delivery(self, row: sqlite3.Row) -> DeliveryRecord:
        parse = lambda value: None if value is None else datetime.fromisoformat(value)
        return DeliveryRecord(
            delivery_id=row["delivery_id"], deduplication_key=row["deduplication_key"], cycle_id=row["cycle_id"],
            user_id=row["user_id"], investor_identifier=row["investor_identifier"], topic=AlertTopic(row["topic"]),
            channel=DeliveryChannel(row["channel"]), status=DeliveryStatus(row["status"]), headline=row["headline"],
            explanation=row["explanation"], attempts=int(row["attempts"]), next_attempt_at=parse(row["next_attempt_at"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
            sent_at=parse(row["sent_at"]), acknowledged_at=parse(row["acknowledged_at"]), last_error=row["last_error"],
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("delivery clock must be timezone-aware")
        return value

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


__all__ = ["SQLiteDeliveryStore"]
