"""Durable delivery preferences, scheduled cycles, and alert history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from delivery.models import (
    AlertChannel,
    AlertDelivery,
    AlertMessage,
    AlertPriority,
    AlertTopic,
    CycleStatus,
    DeliveryPreference,
    DeliveryStatus,
    ScheduledCycleRecord,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class SQLiteAlertStore:
    """SQLite persistence with idempotent queueing and append-only attempts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("alert store path must be a file")
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS delivery_preferences (
                    user_id TEXT PRIMARY KEY,
                    timezone_name TEXT NOT NULL,
                    delivery_hour INTEGER NOT NULL,
                    channels_json TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    email_address TEXT,
                    minimum_conviction_change INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scheduled_cycles (
                    cycle_key TEXT PRIMARY KEY,
                    scheduled_for TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    snapshot_identifier TEXT,
                    next_attempt_at TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS scheduled_cycles_status_due
                ON scheduled_cycles (status, next_attempt_at, scheduled_for);

                CREATE TABLE IF NOT EXISTS alert_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    snapshot_identifier TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    email_address TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_attempt_at TEXT,
                    sent_at TEXT,
                    acknowledged_at TEXT,
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS alert_deliveries_user_created
                ON alert_deliveries (user_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS alert_deliveries_pending
                ON alert_deliveries (status, next_attempt_at, created_at);

                CREATE TABLE IF NOT EXISTS delivery_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL,
                    attempted_at TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    detail TEXT NOT NULL,
                    FOREIGN KEY (delivery_id) REFERENCES alert_deliveries(delivery_id)
                );

                CREATE TRIGGER IF NOT EXISTS delivery_attempts_prevent_update
                BEFORE UPDATE ON delivery_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'delivery attempt history is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS delivery_attempts_prevent_delete
                BEFORE DELETE ON delivery_attempts
                BEGIN
                    SELECT RAISE(ABORT, 'delivery attempt history is append-only');
                END;
                """
            )

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()
                connection.execute("SELECT COUNT(*) FROM alert_deliveries").fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"alert store is unavailable: {error}"
        return True, "scheduled cycles and alert delivery history are available"

    def get_preference(
        self,
        user_id: str,
        *,
        fallback_email: str | None = None,
    ) -> DeliveryPreference:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM delivery_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return DeliveryPreference.default_for(user_id, email_address=fallback_email)
        return self._preference_from_row(row)

    def save_preference(
        self,
        preference: DeliveryPreference,
        *,
        now: datetime | None = None,
    ) -> DeliveryPreference:
        if not isinstance(preference, DeliveryPreference):
            raise TypeError("preference must be a DeliveryPreference")
        timestamp = _aware(now or _utc_now(), "now")
        stored = DeliveryPreference(
            user_id=preference.user_id,
            timezone_name=preference.timezone_name,
            delivery_hour=preference.delivery_hour,
            channels=preference.channels,
            topics=preference.topics,
            email_address=preference.email_address,
            minimum_conviction_change=preference.minimum_conviction_change,
            updated_at=timestamp,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO delivery_preferences (
                    user_id, timezone_name, delivery_hour, channels_json,
                    topics_json, email_address, minimum_conviction_change,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (user_id) DO UPDATE SET
                    timezone_name = excluded.timezone_name,
                    delivery_hour = excluded.delivery_hour,
                    channels_json = excluded.channels_json,
                    topics_json = excluded.topics_json,
                    email_address = excluded.email_address,
                    minimum_conviction_change = excluded.minimum_conviction_change,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.user_id,
                    stored.timezone_name,
                    stored.delivery_hour,
                    json.dumps([value.value for value in stored.channels]),
                    json.dumps([value.value for value in stored.topics]),
                    stored.email_address,
                    stored.minimum_conviction_change,
                    timestamp.isoformat(),
                ),
            )
        return stored

    def begin_cycle(
        self,
        cycle_key: str,
        *,
        scheduled_for: datetime,
        now: datetime,
        lease: timedelta = timedelta(minutes=30),
    ) -> bool:
        scheduled_for = _aware(scheduled_for, "scheduled_for")
        now = _aware(now, "now")
        if lease <= timedelta(0):
            raise ValueError("lease must be positive")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM scheduled_cycles WHERE cycle_key = ?",
                (cycle_key,),
            ).fetchone()
            if row is not None:
                status = CycleStatus(row["status"])
                if status is CycleStatus.COMPLETED:
                    return False
                if status is CycleStatus.RUNNING and row["started_at"]:
                    started_at = datetime.fromisoformat(row["started_at"])
                    if started_at + lease > now:
                        return False
                if row["next_attempt_at"]:
                    next_attempt_at = datetime.fromisoformat(row["next_attempt_at"])
                    if next_attempt_at > now:
                        return False
                attempts = int(row["attempts"]) + 1
                connection.execute(
                    """
                    UPDATE scheduled_cycles SET
                        scheduled_for = ?, status = ?, attempts = ?,
                        started_at = ?, completed_at = NULL,
                        snapshot_identifier = NULL, next_attempt_at = NULL,
                        error = NULL, updated_at = ?
                    WHERE cycle_key = ?
                    """,
                    (
                        scheduled_for.isoformat(),
                        CycleStatus.RUNNING.value,
                        attempts,
                        now.isoformat(),
                        now.isoformat(),
                        cycle_key,
                    ),
                )
                return True
            connection.execute(
                """
                INSERT INTO scheduled_cycles (
                    cycle_key, scheduled_for, status, attempts, started_at,
                    completed_at, snapshot_identifier, next_attempt_at,
                    error, updated_at
                ) VALUES (?, ?, ?, 1, ?, NULL, NULL, NULL, NULL, ?)
                """,
                (
                    cycle_key,
                    scheduled_for.isoformat(),
                    CycleStatus.RUNNING.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return True

    def complete_cycle(
        self,
        cycle_key: str,
        *,
        snapshot_identifier: str,
        now: datetime,
    ) -> ScheduledCycleRecord:
        now = _aware(now, "now")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_cycles SET
                    status = ?, completed_at = ?, snapshot_identifier = ?,
                    next_attempt_at = NULL, error = NULL, updated_at = ?
                WHERE cycle_key = ?
                """,
                (
                    CycleStatus.COMPLETED.value,
                    now.isoformat(),
                    snapshot_identifier,
                    now.isoformat(),
                    cycle_key,
                ),
            )
        record = self.get_cycle(cycle_key)
        if record is None:
            raise RuntimeError("completed cycle could not be reloaded")
        return record

    def fail_cycle(
        self,
        cycle_key: str,
        *,
        error: str,
        now: datetime,
        retry_delay: timedelta,
    ) -> ScheduledCycleRecord:
        now = _aware(now, "now")
        if retry_delay <= timedelta(0):
            raise ValueError("retry_delay must be positive")
        next_attempt_at = now + retry_delay
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_cycles SET
                    status = ?, next_attempt_at = ?, error = ?, updated_at = ?
                WHERE cycle_key = ?
                """,
                (
                    CycleStatus.FAILED.value,
                    next_attempt_at.isoformat(),
                    str(error)[:1000],
                    now.isoformat(),
                    cycle_key,
                ),
            )
        record = self.get_cycle(cycle_key)
        if record is None:
            raise RuntimeError("failed cycle could not be reloaded")
        return record

    def get_cycle(self, cycle_key: str) -> ScheduledCycleRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_cycles WHERE cycle_key = ?",
                (cycle_key,),
            ).fetchone()
        return None if row is None else self._cycle_from_row(row)

    def enqueue(
        self,
        message: AlertMessage,
        channel: AlertChannel,
        *,
        now: datetime | None = None,
        available_at: datetime | None = None,
    ) -> AlertDelivery:
        if not isinstance(message, AlertMessage):
            raise TypeError("message must be an AlertMessage")
        channel = AlertChannel(channel)
        if channel not in message.channels:
            raise ValueError("channel is not enabled for this message")
        timestamp = _aware(now or _utc_now(), "now")
        available = _aware(available_at or timestamp, "available_at")
        dedupe_key = f"{message.user_id}|{message.snapshot_identifier}|{channel.value}"
        delivery_id = f"delivery:{uuid4()}"
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM alert_deliveries WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if existing is not None:
                return self._delivery_from_row(existing)
            connection.execute(
                """
                INSERT INTO alert_deliveries (
                    delivery_id, dedupe_key, user_id, snapshot_identifier,
                    channel, topics_json, priority, status, subject, body,
                    email_address, created_at, updated_at, attempts,
                    next_attempt_at, sent_at, acknowledged_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, NULL)
                """,
                (
                    delivery_id,
                    dedupe_key,
                    message.user_id,
                    message.snapshot_identifier,
                    channel.value,
                    json.dumps([topic.value for topic in message.topics]),
                    message.priority.value,
                    DeliveryStatus.PENDING.value,
                    message.subject,
                    message.body,
                    message.email_address if channel is AlertChannel.EMAIL else None,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    available.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        return self._delivery_from_row(row)

    def record_suppression(
        self,
        *,
        user_id: str,
        snapshot_identifier: str,
        reason: str,
        now: datetime | None = None,
    ) -> AlertDelivery:
        timestamp = _aware(now or _utc_now(), "now")
        dedupe_key = f"{user_id}|{snapshot_identifier}|suppressed"
        delivery_id = f"delivery:{uuid4()}"
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM alert_deliveries WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if existing is not None:
                return self._delivery_from_row(existing)
            connection.execute(
                """
                INSERT INTO alert_deliveries (
                    delivery_id, dedupe_key, user_id, snapshot_identifier,
                    channel, topics_json, priority, status, subject, body,
                    email_address, created_at, updated_at, attempts,
                    next_attempt_at, sent_at, acknowledged_at, error
                ) VALUES (?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, NULL, ?, ?, 0, NULL, NULL, NULL, NULL)
                """,
                (
                    delivery_id,
                    dedupe_key,
                    user_id,
                    snapshot_identifier,
                    AlertChannel.IN_APP.value,
                    AlertPriority.STANDARD.value,
                    DeliveryStatus.SUPPRESSED.value,
                    "No alert delivered",
                    reason,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        return self._delivery_from_row(row)

    def pending(self, *, now: datetime | None = None, limit: int = 100) -> tuple[AlertDelivery, ...]:
        timestamp = _aware(now or _utc_now(), "now")
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM alert_deliveries
                WHERE status = ?
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at, delivery_id
                LIMIT ?
                """,
                (DeliveryStatus.PENDING.value, timestamp.isoformat(), limit),
            ).fetchall()
        return tuple(self._delivery_from_row(row) for row in rows)

    def record_attempt(
        self,
        delivery_id: str,
        *,
        success: bool,
        detail: str,
        now: datetime | None = None,
        maximum_attempts: int = 4,
        base_retry_delay: timedelta = timedelta(minutes=5),
    ) -> AlertDelivery:
        timestamp = _aware(now or _utc_now(), "now")
        if maximum_attempts < 1:
            raise ValueError("maximum_attempts must be positive")
        if base_retry_delay <= timedelta(0):
            raise ValueError("base_retry_delay must be positive")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            if row is None:
                raise KeyError("delivery was not found")
            current = self._delivery_from_row(row)
            if current.status is not DeliveryStatus.PENDING:
                return current
            attempts = current.attempts + 1
            connection.execute(
                """
                INSERT INTO delivery_attempts (
                    attempt_id, delivery_id, attempted_at, success, detail
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    f"attempt:{uuid4()}",
                    current.delivery_id,
                    timestamp.isoformat(),
                    int(bool(success)),
                    str(detail)[:2000],
                ),
            )
            if success:
                status = DeliveryStatus.SENT
                next_attempt_at = None
                sent_at = timestamp
                error = None
            elif attempts >= maximum_attempts:
                status = DeliveryStatus.FAILED
                next_attempt_at = None
                sent_at = None
                error = str(detail)[:1000]
            else:
                status = DeliveryStatus.PENDING
                next_attempt_at = timestamp + base_retry_delay * (2 ** (attempts - 1))
                sent_at = None
                error = str(detail)[:1000]
            connection.execute(
                """
                UPDATE alert_deliveries SET
                    status = ?, attempts = ?, next_attempt_at = ?, sent_at = ?,
                    error = ?, updated_at = ?
                WHERE delivery_id = ?
                """,
                (
                    status.value,
                    attempts,
                    None if next_attempt_at is None else next_attempt_at.isoformat(),
                    None if sent_at is None else sent_at.isoformat(),
                    error,
                    timestamp.isoformat(),
                    current.delivery_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ?",
                (current.delivery_id,),
            ).fetchone()
        return self._delivery_from_row(updated)

    def acknowledge(
        self,
        delivery_id: str,
        *,
        user_id: str,
        now: datetime | None = None,
    ) -> AlertDelivery:
        timestamp = _aware(now or _utc_now(), "now")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ? AND user_id = ?",
                (delivery_id, user_id),
            ).fetchone()
            if row is None:
                raise KeyError("delivery was not found")
            current = self._delivery_from_row(row)
            if current.status is DeliveryStatus.ACKNOWLEDGED:
                return current
            if current.status is not DeliveryStatus.SENT:
                raise ValueError("only sent alerts can be acknowledged")
            connection.execute(
                """
                UPDATE alert_deliveries SET
                    status = ?, acknowledged_at = ?, updated_at = ?
                WHERE delivery_id = ?
                """,
                (
                    DeliveryStatus.ACKNOWLEDGED.value,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    delivery_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM alert_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        return self._delivery_from_row(updated)

    def list_deliveries(
        self,
        user_id: str,
        *,
        limit: int = 100,
        include_suppressed: bool = False,
    ) -> tuple[AlertDelivery, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        where = "user_id = ?"
        parameters: list[object] = [user_id]
        if not include_suppressed:
            where += " AND status != ?"
            parameters.append(DeliveryStatus.SUPPRESSED.value)
        parameters.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM alert_deliveries
                WHERE {where}
                ORDER BY created_at DESC, delivery_id DESC
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(self._delivery_from_row(row) for row in rows)

    def unread_count(self, user_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count FROM alert_deliveries
                WHERE user_id = ? AND channel = ? AND status = ?
                """,
                (
                    user_id,
                    AlertChannel.IN_APP.value,
                    DeliveryStatus.SENT.value,
                ),
            ).fetchone()
        return int(row["count"])

    def attempt_count(self, delivery_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM delivery_attempts WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _preference_from_row(row: sqlite3.Row) -> DeliveryPreference:
        return DeliveryPreference(
            user_id=row["user_id"],
            timezone_name=row["timezone_name"],
            delivery_hour=int(row["delivery_hour"]),
            channels=tuple(AlertChannel(value) for value in json.loads(row["channels_json"])),
            topics=tuple(AlertTopic(value) for value in json.loads(row["topics_json"])),
            email_address=row["email_address"],
            minimum_conviction_change=int(row["minimum_conviction_change"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _cycle_from_row(row: sqlite3.Row) -> ScheduledCycleRecord:
        return ScheduledCycleRecord(
            cycle_key=row["cycle_key"],
            scheduled_for=datetime.fromisoformat(row["scheduled_for"]),
            status=CycleStatus(row["status"]),
            attempts=int(row["attempts"]),
            started_at=(None if row["started_at"] is None else datetime.fromisoformat(row["started_at"])),
            completed_at=(None if row["completed_at"] is None else datetime.fromisoformat(row["completed_at"])),
            snapshot_identifier=row["snapshot_identifier"],
            next_attempt_at=(None if row["next_attempt_at"] is None else datetime.fromisoformat(row["next_attempt_at"])),
            error=row["error"],
        )

    @staticmethod
    def _delivery_from_row(row: sqlite3.Row) -> AlertDelivery:
        return AlertDelivery(
            delivery_id=row["delivery_id"],
            user_id=row["user_id"],
            snapshot_identifier=row["snapshot_identifier"],
            channel=AlertChannel(row["channel"]),
            topics=tuple(AlertTopic(value) for value in json.loads(row["topics_json"])),
            priority=AlertPriority(row["priority"]),
            status=DeliveryStatus(row["status"]),
            subject=row["subject"],
            body=row["body"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            attempts=int(row["attempts"]),
            next_attempt_at=(None if row["next_attempt_at"] is None else datetime.fromisoformat(row["next_attempt_at"])),
            sent_at=(None if row["sent_at"] is None else datetime.fromisoformat(row["sent_at"])),
            acknowledged_at=(None if row["acknowledged_at"] is None else datetime.fromisoformat(row["acknowledged_at"])),
            error=row["error"],
        )


__all__ = ["SQLiteAlertStore"]
