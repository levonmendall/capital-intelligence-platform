"""Durable scheduled and material-event execution for the canonical CIO cycle."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from datetime import datetime, time as clock_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from delivery.models import CycleStatus
from delivery.service import WorkerRunResult
from delivery.store import SQLiteAlertStore


_SCHEDULE_PATTERN = re.compile(r"^(?P<hour>\d{2}):(?P<minute>\d{2})$")
_TRIGGER_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def _schedule_time(value: str) -> clock_time:
    if not isinstance(value, str):
        raise TypeError("schedule time must be a string")
    match = _SCHEDULE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("schedule times must use HH:MM")
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("schedule times must be valid clock times")
    return clock_time(hour=hour, minute=minute)


def _trigger_slug(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("trigger_key cannot be empty")
    normalized = _TRIGGER_PATTERN.sub("-", value.strip()).strip("-").lower()
    if not normalized:
        raise ValueError("trigger_key must contain an alphanumeric character")
    return normalized[:120]


class ScheduledCanonicalCIOWorker:
    """Run idempotent scheduled and material-event canonical CIO cycles.

    A scheduled slot and an event trigger receive different durable cycle keys, so
    frequent reassessment cannot duplicate the same review or collapse multiple
    legitimate reviews into one market-date record.
    """

    def __init__(
        self,
        executor: Any,
        cycle_store: SQLiteAlertStore,
        *,
        delivery_service: Any | None = None,
        identity_store: Any | None = None,
        schedule_timezone: str = "America/New_York",
        schedule_hour: int = 7,
        schedule_times: Sequence[str] | None = None,
        clock: Callable[[], datetime] | None = None,
        cycle_retry_delay: timedelta = timedelta(minutes=15),
        cycle_lease: timedelta = timedelta(minutes=30),
    ) -> None:
        run = getattr(executor, "run", None)
        if not callable(run):
            raise TypeError("executor must expose run(as_of=...)")
        if not isinstance(cycle_store, SQLiteAlertStore):
            raise TypeError("cycle_store must be SQLiteAlertStore")
        if delivery_service is not None and not callable(
            getattr(delivery_service, "dispatch_pending", None)
        ):
            raise TypeError("delivery_service must expose dispatch_pending()")
        if delivery_service is not None and not callable(
            getattr(delivery_service, "queue_cycle_result", None)
        ):
            raise TypeError("delivery_service must expose queue_cycle_result()")
        if delivery_service is not None and not callable(
            getattr(identity_store, "list_users", None)
        ):
            raise TypeError("identity_store must expose list_users() when delivery is enabled")
        if not schedule_timezone.strip():
            raise ValueError("schedule_timezone cannot be empty")
        if not 0 <= schedule_hour <= 23:
            raise ValueError("schedule_hour must be between 0 and 23")
        if cycle_retry_delay <= timedelta(0):
            raise ValueError("cycle_retry_delay must be positive")
        if cycle_lease <= timedelta(0):
            raise ValueError("cycle_lease must be positive")

        raw_times = tuple(schedule_times or (f"{schedule_hour:02d}:00",))
        parsed = tuple(sorted({_schedule_time(item) for item in raw_times}))
        if not parsed:
            raise ValueError("at least one schedule time is required")

        self.executor = executor
        self.cycle_store = cycle_store
        self.delivery_service = delivery_service
        self.identity_store = identity_store
        self.schedule_timezone = schedule_timezone
        self.timezone = ZoneInfo(schedule_timezone)
        self.schedule_times = parsed
        self.schedule_hour = parsed[0].hour
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.cycle_retry_delay = cycle_retry_delay
        self.cycle_lease = cycle_lease

    def scheduled_slots(self, now: datetime) -> tuple[datetime, ...]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local = now.astimezone(self.timezone)
        return tuple(
            local.replace(
                hour=item.hour,
                minute=item.minute,
                second=0,
                microsecond=0,
            ).astimezone(timezone.utc)
            for item in self.schedule_times
        )

    def scheduled_for(self, now: datetime) -> datetime:
        """Return the latest due slot, or the first slot when the day has not begun."""

        slots = self.scheduled_slots(now)
        due = tuple(item for item in slots if item <= now)
        return due[-1] if due else slots[0]

    def _scheduled_cycle_key(self, scheduled_for: datetime) -> str:
        local = scheduled_for.astimezone(self.timezone)
        date_value = local.date().isoformat()
        base = f"canonical-cio:{self.schedule_timezone}:{date_value}"
        # Preserve the original single 07:00 cycle key for compatibility with
        # existing journals and tests. Additional slots are independently keyed.
        if local.hour == 7 and local.minute == 0:
            return base
        return f"{base}:scheduled:{local.strftime('%H%M')}"

    def scheduled_cycle_key(self, now: datetime) -> str:
        return self._scheduled_cycle_key(self.scheduled_for(now))

    def needs_scheduled_cycle(self, now: datetime) -> bool:
        scheduled_for = self.scheduled_for(now)
        if now < scheduled_for:
            return False
        record = self.cycle_store.get_cycle(self._scheduled_cycle_key(scheduled_for))
        return record is None or record.status is not CycleStatus.COMPLETED

    def scheduled_attempt_due(self, now: datetime) -> bool:
        """Return whether the latest scheduled slot may collect and execute now."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        scheduled_for = self.scheduled_for(now)
        if now < scheduled_for:
            return False
        return self.cycle_store.cycle_attempt_due(
            self._scheduled_cycle_key(scheduled_for),
            now=now,
            lease=self.cycle_lease,
        )

    def triggered_cycle_key(self, trigger_key: str, *, now: datetime) -> str:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local_date = now.astimezone(self.timezone).date().isoformat()
        return (
            f"canonical-cio:{self.schedule_timezone}:{local_date}:event:"
            f"{_trigger_slug(trigger_key)}"
        )

    def triggered_attempt_due(self, trigger_key: str, *, now: datetime) -> bool:
        """Return whether a material-event cycle may collect and execute now."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return self.cycle_store.cycle_attempt_due(
            self.triggered_cycle_key(trigger_key, now=now),
            now=now,
            lease=self.cycle_lease,
        )

    def needs_triggered_cycle(self, trigger_key: str, *, now: datetime) -> bool:
        record = self.cycle_store.get_cycle(
            self.triggered_cycle_key(trigger_key, now=now)
        )
        return record is None or record.status is not CycleStatus.COMPLETED

    def _run_cycle(
        self,
        *,
        cycle_key: str,
        scheduled_for: datetime,
        timestamp: datetime,
        decision_time: datetime,
    ) -> WorkerRunResult:
        claimed = self.cycle_store.begin_cycle(
            cycle_key,
            scheduled_for=scheduled_for,
            now=timestamp,
            lease=self.cycle_lease,
        )
        if not claimed:
            record = self.cycle_store.get_cycle(cycle_key)
            return WorkerRunResult(
                cycle_key=cycle_key,
                status=(record.status.value if record else "not_claimed"),
                detail=(record.error if record else None),
                snapshot_identifier=(record.snapshot_identifier if record else None),
            )
        try:
            result = self.executor.run(as_of=decision_time)
            briefing = getattr(result, "briefing", None)
            snapshot_identifier = getattr(briefing, "identifier", None)
            if not isinstance(snapshot_identifier, str) or not snapshot_identifier.strip():
                raise RuntimeError(
                    "canonical cycle result must expose briefing.identifier"
                )
            if self.delivery_service is not None:
                accounts = tuple(self.identity_store.list_users())
                self.delivery_service.queue_cycle_result(result, accounts)
            self.cycle_store.complete_cycle(
                cycle_key,
                snapshot_identifier=snapshot_identifier,
                now=self._clock(),
            )
        except Exception as error:
            self.cycle_store.fail_cycle(
                cycle_key,
                error=str(error),
                now=self._clock(),
                retry_delay=self.cycle_retry_delay,
            )
            return WorkerRunResult(
                cycle_key=cycle_key,
                status=CycleStatus.FAILED.value,
                detail=str(error),
            )
        return WorkerRunResult(
            cycle_key=cycle_key,
            status=CycleStatus.COMPLETED.value,
            snapshot_identifier=snapshot_identifier,
        )

    def run_due(
        self,
        *,
        now: datetime | None = None,
        decision_as_of: datetime | None = None,
    ) -> WorkerRunResult:
        timestamp = now or self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        scheduled_for = self.scheduled_for(timestamp)
        cycle_key = self._scheduled_cycle_key(scheduled_for)
        if timestamp < scheduled_for:
            return WorkerRunResult(cycle_key=cycle_key, status="not_due")

        decision_time = scheduled_for if decision_as_of is None else decision_as_of
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_as_of must be timezone-aware")
        decision_time = decision_time.astimezone(timezone.utc)
        if decision_time > timestamp:
            raise ValueError("decision_as_of cannot follow now")
        if (
            decision_time.astimezone(self.timezone).date()
            != scheduled_for.astimezone(self.timezone).date()
        ):
            raise ValueError("decision_as_of must remain inside the scheduled market date")
        if decision_time < scheduled_for:
            raise ValueError("decision_as_of cannot predate the scheduled boundary")

        return self._run_cycle(
            cycle_key=cycle_key,
            scheduled_for=scheduled_for,
            timestamp=timestamp,
            decision_time=decision_time,
        )

    def run_triggered(
        self,
        trigger_key: str,
        *,
        now: datetime | None = None,
        decision_as_of: datetime | None = None,
    ) -> WorkerRunResult:
        """Run one idempotent material-event review inside the current market date."""

        timestamp = now or self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        decision_time = timestamp if decision_as_of is None else decision_as_of
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_as_of must be timezone-aware")
        decision_time = decision_time.astimezone(timezone.utc)
        if decision_time > timestamp:
            raise ValueError("decision_as_of cannot follow now")
        if (
            decision_time.astimezone(self.timezone).date()
            != timestamp.astimezone(self.timezone).date()
        ):
            raise ValueError("triggered decision must remain inside the current market date")
        cycle_key = self.triggered_cycle_key(trigger_key, now=timestamp)
        return self._run_cycle(
            cycle_key=cycle_key,
            scheduled_for=timestamp,
            timestamp=timestamp,
            decision_time=decision_time,
        )

    def dispatch_pending(self):
        if self.delivery_service is None:
            return ()
        return self.delivery_service.dispatch_pending()

    def serve_forever(self, *, poll_seconds: int = 60) -> None:
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be positive")
        while True:
            self.run_due()
            self.dispatch_pending()
            time.sleep(poll_seconds)


__all__ = ["ScheduledCanonicalCIOWorker"]
