"""Durable scheduled execution for the canonical CIO cycle."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from delivery.models import CycleStatus
from delivery.service import WorkerRunResult
from delivery.store import SQLiteAlertStore


class ScheduledCanonicalCIOWorker:
    """Run one idempotent canonical CIO cycle per configured market date."""

    def __init__(
        self,
        executor: Any,
        cycle_store: SQLiteAlertStore,
        *,
        delivery_service: Any | None = None,
        identity_store: Any | None = None,
        schedule_timezone: str = "America/New_York",
        schedule_hour: int = 7,
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
        self.executor = executor
        self.cycle_store = cycle_store
        self.delivery_service = delivery_service
        self.identity_store = identity_store
        self.schedule_timezone = schedule_timezone
        self.timezone = ZoneInfo(schedule_timezone)
        self.schedule_hour = schedule_hour
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.cycle_retry_delay = cycle_retry_delay
        self.cycle_lease = cycle_lease

    def scheduled_for(self, now: datetime) -> datetime:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local = now.astimezone(self.timezone)
        scheduled_local = local.replace(
            hour=self.schedule_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        return scheduled_local.astimezone(timezone.utc)

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
        local_date = scheduled_for.astimezone(self.timezone).date().isoformat()
        cycle_key = f"canonical-cio:{self.schedule_timezone}:{local_date}"
        if timestamp < scheduled_for:
            return WorkerRunResult(cycle_key=cycle_key, status="not_due")

        decision_time = scheduled_for if decision_as_of is None else decision_as_of
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_as_of must be timezone-aware")
        decision_time = decision_time.astimezone(timezone.utc)
        if decision_time > timestamp:
            raise ValueError("decision_as_of cannot follow now")
        if decision_time.astimezone(self.timezone).date().isoformat() != local_date:
            raise ValueError("decision_as_of must remain inside the scheduled market date")
        if decision_time < scheduled_for:
            raise ValueError("decision_as_of cannot predate the scheduled boundary")

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
