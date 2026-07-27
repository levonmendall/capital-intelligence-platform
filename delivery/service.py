"""Selective alert planning, delivery dispatch, and scheduled cycle execution."""

from __future__ import annotations

import smtplib
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from delivery.canonical_alerts import (
    CanonicalAlertEvent,
    CanonicalAlertPlanner,
    events_from_canonical_cycle,
)
from delivery.models import (
    AlertChannel,
    AlertMessage,
    AlertPriority,
    AlertSnapshot,
    AlertTopic,
    CycleStatus,
    DeliveryPreference,
)
from delivery.store import SQLiteAlertStore


class DeliveryDispatcher(Protocol):
    def __call__(self, delivery: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class AlertPlanningResult:
    message: AlertMessage | None
    suppression_reason: str | None


class SelectiveAlertPlanner:
    """Translate governed materiality plus user preferences into one message."""

    _CATEGORY_TOPICS: Mapping[str, AlertTopic] = {
        "regime": AlertTopic.ENVIRONMENT_TRANSITION,
        "recommendation": AlertTopic.COMMITTEE_CHANGE,
        "governance": AlertTopic.COMMITTEE_CHANGE,
        "signal": AlertTopic.PORTFOLIO_REVIEW,
        "data_quality": AlertTopic.DATA_QUALITY,
        "confidence": AlertTopic.CONVICTION_CHANGE,
    }

    def plan(
        self,
        snapshot: AlertSnapshot,
        preference: DeliveryPreference,
    ) -> AlertPlanningResult:
        topics: list[AlertTopic] = []
        if snapshot.should_alert:
            if snapshot.alert_level == "urgent":
                topics.append(AlertTopic.URGENT_RISK)
            for category in snapshot.change_categories:
                topic = self._CATEGORY_TOPICS.get(category)
                if topic is not None:
                    topics.append(topic)
            if not topics:
                topics.append(AlertTopic.PORTFOLIO_REVIEW)
        if (
            snapshot.conviction_change_points is not None
            and abs(snapshot.conviction_change_points)
            >= (preference.minimum_conviction_change or 5)
        ):
            topics.append(AlertTopic.CONVICTION_CHANGE)
        if preference.daily_summary_enabled:
            topics.append(AlertTopic.DAILY_SUMMARY)
        selected = tuple(
            topic
            for topic in dict.fromkeys(topics)
            if topic in preference.topics
        )
        if not selected:
            if not snapshot.should_alert and not preference.daily_summary_enabled:
                return AlertPlanningResult(
                    message=None,
                    suppression_reason=(
                        "The scheduled analysis completed, but the governed material-change "
                        "policy remained silent and daily summaries are disabled."
                    ),
                )
            return AlertPlanningResult(
                message=None,
                suppression_reason=(
                    "The scheduled analysis produced topics that are disabled in this "
                    "user's alert preferences."
                ),
            )
        channels = tuple(
            channel
            for channel in preference.channels
            if channel is not AlertChannel.EMAIL or preference.email_address is not None
        )
        if not channels:
            return AlertPlanningResult(
                message=None,
                suppression_reason="No configured delivery channel is currently usable.",
            )
        priority = (
            AlertPriority.URGENT
            if AlertTopic.URGENT_RISK in selected
            else AlertPriority.STANDARD
        )
        topic_labels = ", ".join(topic.value.replace("_", " ") for topic in selected)
        subject = (
            "Urgent Capital Intelligence review"
            if priority is AlertPriority.URGENT
            else "Capital Intelligence update"
        )
        body = (
            f"Capital Intelligence Score: {snapshot.score}"
            + ("" if snapshot.score_delta is None else f" ({snapshot.score_delta:+d})")
            + f"\nEnvironment: {snapshot.environment}"
            + f"\nRisk: {snapshot.risk}"
            + f"\nCommittee: {snapshot.committee}"
            + f"\nPortfolio impact: {snapshot.portfolio_impact}"
            + f"\nWhat changed: {snapshot.change_summary}"
            + f"\nAlert topics: {topic_labels}."
        )
        return AlertPlanningResult(
            message=AlertMessage(
                user_id=preference.user_id,
                snapshot_identifier=snapshot.snapshot_identifier,
                as_of=snapshot.as_of,
                topics=selected,
                priority=priority,
                subject=subject,
                body=body,
                channels=channels,
                email_address=preference.email_address,
            ),
            suppression_reason=None,
        )


class SMTPEmailDispatcher:
    """Small SMTP adapter; credentials remain in runtime configuration."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not host.strip():
            raise ValueError("host cannot be empty")
        if not 1 <= int(port) <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if "@" not in from_address:
            raise ValueError("from_address must be a valid email address")
        if bool(username) != bool(password):
            raise ValueError("SMTP username and password must be supplied together")
        self.host = host.strip()
        self.port = int(port)
        self.from_address = from_address.strip().casefold()
        self.username = username
        self.password = password
        self.use_tls = bool(use_tls)
        self.timeout_seconds = float(timeout_seconds)

    def __call__(self, delivery: Any) -> None:
        recipient = getattr(delivery, "email_address", None)
        if not recipient:
            raise ValueError("email delivery is missing a recipient")
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = recipient
        message["Subject"] = delivery.subject
        message.set_content(delivery.body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            if self.use_tls:
                client.starttls(context=ssl.create_default_context())
            if self.username and self.password:
                client.login(self.username, self.password)
            client.send_message(message)


class AlertDeliveryService:
    def __init__(
        self,
        store: SQLiteAlertStore,
        *,
        planner: SelectiveAlertPlanner | None = None,
        canonical_planner: CanonicalAlertPlanner | None = None,
        dispatchers: Mapping[AlertChannel, DeliveryDispatcher] | None = None,
        maximum_attempts: int = 4,
        base_retry_delay: timedelta = timedelta(minutes=5),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.planner = planner or SelectiveAlertPlanner()
        self.canonical_planner = canonical_planner or CanonicalAlertPlanner()
        self.dispatchers = dict(dispatchers or {})
        self.maximum_attempts = maximum_attempts
        self.base_retry_delay = base_retry_delay
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def queue_event_for_accounts(
        self,
        event: CanonicalAlertEvent,
        accounts: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        queued: list[Any] = []
        now = self._clock()
        for account in accounts:
            if not bool(getattr(account, "is_active", False)):
                continue
            user_id = str(getattr(account, "user_id"))
            email = str(getattr(account, "email", "")) or None
            preference = self.store.get_preference(user_id, fallback_email=email)
            result = self.canonical_planner.plan(event, preference)
            if result.message is None:
                queued.append(
                    self.store.record_suppression(
                        user_id=user_id,
                        snapshot_identifier=event.identifier,
                        reason=result.suppression_reason or "Canonical event suppressed.",
                        now=now,
                    )
                )
                continue
            available_at = self._available_at(
                preference,
                now=now,
                priority=result.message.priority,
            )
            for channel in result.message.channels:
                queued.append(
                    self.store.enqueue(
                        result.message,
                        channel,
                        now=now,
                        available_at=available_at,
                    )
                )
        return tuple(queued)

    def queue_cycle_result(
        self,
        result: Any,
        accounts: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        queued: list[Any] = []
        for event in events_from_canonical_cycle(result):
            queued.extend(self.queue_event_for_accounts(event, accounts))
        return tuple(queued)

    def queue_for_accounts(
        self,
        snapshot: AlertSnapshot,
        accounts: tuple[Any, ...],
    ) -> tuple[Any, ...]:
        queued: list[Any] = []
        now = self._clock()
        for account in accounts:
            if not bool(getattr(account, "is_active", False)):
                continue
            user_id = str(getattr(account, "user_id"))
            email = str(getattr(account, "email", "")) or None
            preference = self.store.get_preference(user_id, fallback_email=email)
            result = self.planner.plan(snapshot, preference)
            if result.message is None:
                queued.append(
                    self.store.record_suppression(
                        user_id=user_id,
                        snapshot_identifier=snapshot.snapshot_identifier,
                        reason=result.suppression_reason or "Alert suppressed.",
                        now=now,
                    )
                )
                continue
            available_at = self._available_at(
                preference,
                now=now,
                priority=result.message.priority,
            )
            for channel in result.message.channels:
                queued.append(
                    self.store.enqueue(
                        result.message,
                        channel,
                        now=now,
                        available_at=available_at,
                    )
                )
        return tuple(queued)

    @staticmethod
    def _available_at(
        preference: DeliveryPreference,
        *,
        now: datetime,
        priority: AlertPriority,
    ) -> datetime:
        if priority is AlertPriority.URGENT:
            return now
        local_now = now.astimezone(ZoneInfo(preference.timezone_name))
        preferred = local_now.replace(
            hour=preference.delivery_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if preferred <= local_now:
            return now
        return preferred.astimezone(timezone.utc)

    def dispatch_pending(self, *, limit: int = 100) -> tuple[Any, ...]:
        completed: list[Any] = []
        now = self._clock()
        for delivery in self.store.pending(now=now, limit=limit):
            try:
                if delivery.channel is AlertChannel.IN_APP:
                    detail = "In-app alert is available in the authenticated inbox."
                else:
                    dispatcher = self.dispatchers.get(delivery.channel)
                    if dispatcher is None:
                        raise RuntimeError(
                            f"no dispatcher is configured for {delivery.channel.value}"
                        )
                    dispatcher(delivery)
                    detail = f"{delivery.channel.value} delivery succeeded."
            except Exception as error:
                completed.append(
                    self.store.record_attempt(
                        delivery.delivery_id,
                        success=False,
                        detail=str(error),
                        now=now,
                        maximum_attempts=self.maximum_attempts,
                        base_retry_delay=self.base_retry_delay,
                    )
                )
            else:
                completed.append(
                    self.store.record_attempt(
                        delivery.delivery_id,
                        success=True,
                        detail=detail,
                        now=now,
                        maximum_attempts=self.maximum_attempts,
                        base_retry_delay=self.base_retry_delay,
                    )
                )
        return tuple(completed)


@dataclass(frozen=True, slots=True)
class CanonicalCycleResult:
    alert_snapshot: AlertSnapshot
    run: object
    decision: object


class CanonicalDailyCycleExecutor:
    """Keep the previous governed cycle in memory for material comparison."""

    def __init__(
        self,
        daily_service: Any,
        *,
        conviction_change_reader: Callable[[], int | None] | None = None,
    ) -> None:
        self.daily_service = daily_service
        self.conviction_change_reader = conviction_change_reader
        self._previous_run: object | None = None
        self._previous_decision: object | None = None

    def run(self, *, as_of: datetime) -> CanonicalCycleResult:
        kwargs: dict[str, object] = {"as_of": as_of}
        if self._previous_run is not None and self._previous_decision is not None:
            kwargs["previous_run"] = self._previous_run
            kwargs["previous_decision"] = self._previous_decision
        cycle = self.daily_service.run(**kwargs)
        self._previous_run = cycle.run
        self._previous_decision = cycle.decision
        conviction_change = (
            None
            if self.conviction_change_reader is None
            else self.conviction_change_reader()
        )
        return CanonicalCycleResult(
            alert_snapshot=AlertSnapshot.from_daily_snapshot(
                cycle.snapshot,
                conviction_change_points=conviction_change,
            ),
            run=cycle.run,
            decision=cycle.decision,
        )


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    cycle_key: str
    status: str
    snapshot_identifier: str | None = None
    detail: str | None = None


class ScheduledDailyIntelligenceWorker:
    """Persistent worker with one idempotent daily cycle per market date."""

    def __init__(
        self,
        executor: Any,
        identity_store: Any,
        alert_service: AlertDeliveryService,
        *,
        schedule_timezone: str = "America/New_York",
        schedule_hour: int = 7,
        clock: Callable[[], datetime] | None = None,
        cycle_retry_delay: timedelta = timedelta(minutes=15),
        cycle_lease: timedelta = timedelta(minutes=30),
    ) -> None:
        self.executor = executor
        self.identity_store = identity_store
        self.alert_service = alert_service
        self.schedule_timezone = schedule_timezone
        self.timezone = ZoneInfo(schedule_timezone)
        if not 0 <= schedule_hour <= 23:
            raise ValueError("schedule_hour must be between 0 and 23")
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

    def run_due(self, *, now: datetime | None = None) -> WorkerRunResult:
        timestamp = now or self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        scheduled_for = self.scheduled_for(timestamp)
        local_date = scheduled_for.astimezone(self.timezone).date().isoformat()
        cycle_key = f"daily-intelligence:{self.schedule_timezone}:{local_date}"
        if timestamp < scheduled_for:
            return WorkerRunResult(cycle_key=cycle_key, status="not_due")
        claimed = self.alert_service.store.begin_cycle(
            cycle_key,
            scheduled_for=scheduled_for,
            now=timestamp,
            lease=self.cycle_lease,
        )
        if not claimed:
            record = self.alert_service.store.get_cycle(cycle_key)
            return WorkerRunResult(
                cycle_key=cycle_key,
                status=(record.status.value if record else "not_claimed"),
                snapshot_identifier=(record.snapshot_identifier if record else None),
            )
        try:
            result = self.executor.run(as_of=scheduled_for)
            accounts = tuple(self.identity_store.list_users())
            self.alert_service.queue_for_accounts(result.alert_snapshot, accounts)
            self.alert_service.dispatch_pending()
            self.alert_service.store.complete_cycle(
                cycle_key,
                snapshot_identifier=result.alert_snapshot.snapshot_identifier,
                now=self._clock(),
            )
        except Exception as error:
            self.alert_service.store.fail_cycle(
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
            snapshot_identifier=result.alert_snapshot.snapshot_identifier,
        )

    def serve_forever(self, *, poll_seconds: int = 60) -> None:
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be positive")
        while True:
            self.run_due()
            self.alert_service.dispatch_pending()
            time.sleep(poll_seconds)


__all__ = [
    "AlertDeliveryService",
    "AlertPlanningResult",
    "CanonicalCycleResult",
    "CanonicalDailyCycleExecutor",
    "SMTPEmailDispatcher",
    "ScheduledDailyIntelligenceWorker",
    "SelectiveAlertPlanner",
    "WorkerRunResult",
]
