"""Typed scheduling and selective-alert delivery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AlertChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"


class AlertTopic(str, Enum):
    CIO_DECISION = "cio_decision"
    THESIS = "thesis"
    OPPORTUNITY = "opportunity"
    IMPLEMENTATION = "implementation"
    EVIDENCE = "evidence"
    DAILY_BRIEFING = "daily_briefing"

    # Compatibility-only topics retained for archived delivery rows and tests.
    URGENT_RISK = "urgent_risk"
    ENVIRONMENT_TRANSITION = "environment_transition"
    COMMITTEE_CHANGE = "committee_change"
    PORTFOLIO_REVIEW = "portfolio_review"
    CONVICTION_CHANGE = "conviction_change"
    DATA_QUALITY = "data_quality"
    DAILY_SUMMARY = "daily_summary"


class AlertPriority(str, Enum):
    STANDARD = "standard"
    URGENT = "urgent"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    ACKNOWLEDGED = "acknowledged"


class CycleStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _enum_value(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


@dataclass(frozen=True, slots=True)
class DeliveryPreference:
    user_id: str
    timezone_name: str = "UTC"
    delivery_hour: int = 8
    channels: tuple[AlertChannel, ...] = (AlertChannel.IN_APP,)
    topics: tuple[AlertTopic, ...] = (
        AlertTopic.CIO_DECISION,
        AlertTopic.THESIS,
        AlertTopic.OPPORTUNITY,
        AlertTopic.IMPLEMENTATION,
        AlertTopic.EVIDENCE,
        AlertTopic.DAILY_BRIEFING,
        # Compatibility-only defaults for archived planners; active API/UI filters these.
        AlertTopic.URGENT_RISK,
        AlertTopic.ENVIRONMENT_TRANSITION,
        AlertTopic.COMMITTEE_CHANGE,
        AlertTopic.PORTFOLIO_REVIEW,
        AlertTopic.CONVICTION_CHANGE,
        AlertTopic.DATA_QUALITY,
    )
    email_address: str | None = None
    minimum_conviction_change: int | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _required_text(self.user_id, "user_id"))
        timezone_name = _required_text(self.timezone_name, "timezone_name")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown timezone: {timezone_name}") from error
        object.__setattr__(self, "timezone_name", timezone_name)
        if isinstance(self.delivery_hour, bool) or not isinstance(self.delivery_hour, int):
            raise TypeError("delivery_hour must be an int")
        if not 0 <= self.delivery_hour <= 23:
            raise ValueError("delivery_hour must be between 0 and 23")
        normalized_channels = tuple(dict.fromkeys(AlertChannel(value) for value in self.channels))
        normalized_topics = tuple(dict.fromkeys(AlertTopic(value) for value in self.topics))
        if not normalized_channels:
            raise ValueError("at least one delivery channel is required")
        if not normalized_topics:
            raise ValueError("at least one alert topic is required")
        object.__setattr__(self, "channels", normalized_channels)
        object.__setattr__(self, "topics", normalized_topics)
        if self.email_address is not None:
            email = _required_text(self.email_address, "email_address").casefold()
            if "@" not in email or email.startswith("@") or email.endswith("@"):
                raise ValueError("email_address must be valid")
            object.__setattr__(self, "email_address", email)
        if AlertChannel.EMAIL in normalized_channels and self.email_address is None:
            raise ValueError("email_address is required when email delivery is enabled")
        if self.minimum_conviction_change is not None:
            if (
                isinstance(self.minimum_conviction_change, bool)
                or not isinstance(self.minimum_conviction_change, int)
            ):
                raise TypeError("minimum_conviction_change must be an int or None")
            if not 1 <= self.minimum_conviction_change <= 100:
                raise ValueError("minimum_conviction_change must be between 1 and 100")
        if self.updated_at is not None:
            _aware(self.updated_at, "updated_at")

    @property
    def daily_summary_enabled(self) -> bool:
        return (
            AlertTopic.DAILY_BRIEFING in self.topics
            or AlertTopic.DAILY_SUMMARY in self.topics
        )

    @classmethod
    def default_for(cls, user_id: str, *, email_address: str | None = None) -> "DeliveryPreference":
        return cls(user_id=user_id, email_address=email_address)


@dataclass(frozen=True, slots=True)
class AlertSnapshot:
    snapshot_identifier: str
    as_of: datetime
    status: str
    score: int
    score_delta: int | None
    environment: str
    risk: str
    committee: str
    portfolio_impact: str
    change_summary: str
    should_alert: bool
    alert_level: str
    change_categories: tuple[str, ...] = ()
    conviction_change_points: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_identifier",
            "status",
            "environment",
            "risk",
            "committee",
            "portfolio_impact",
            "change_summary",
            "alert_level",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        _aware(self.as_of, "as_of")
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise TypeError("score must be an int")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if self.score_delta is not None and (
            isinstance(self.score_delta, bool) or not isinstance(self.score_delta, int)
        ):
            raise TypeError("score_delta must be an int or None")
        if self.conviction_change_points is not None and (
            isinstance(self.conviction_change_points, bool)
            or not isinstance(self.conviction_change_points, int)
        ):
            raise TypeError("conviction_change_points must be an int or None")
        if not isinstance(self.should_alert, bool):
            raise TypeError("should_alert must be a bool")
        normalized_categories = tuple(
            dict.fromkeys(_required_text(value, "change_category") for value in self.change_categories)
        )
        object.__setattr__(self, "change_categories", normalized_categories)

    @classmethod
    def from_daily_snapshot(
        cls,
        snapshot: Any,
        *,
        conviction_change_points: int | None = None,
    ) -> "AlertSnapshot":
        change = getattr(snapshot, "change_assessment", None)
        categories: tuple[str, ...] = ()
        alert_level = "silent"
        if change is not None:
            categories = tuple(
                _enum_value(getattr(item, "category", "unknown"))
                for item in getattr(change, "changes", ())
            )
            alert_level = _enum_value(getattr(change, "alert_level", "silent"))
        environment = getattr(snapshot, "environment")
        score = getattr(snapshot, "score")
        if change is None:
            alert_level = _enum_value(getattr(environment, "alert_level", "silent"))
        return cls(
            snapshot_identifier=str(getattr(snapshot, "identifier")),
            as_of=getattr(snapshot, "as_of"),
            status=_enum_value(getattr(snapshot, "status")),
            score=int(getattr(score, "score")),
            score_delta=getattr(snapshot, "score_delta", None),
            environment=str(getattr(score, "environment")),
            risk=str(getattr(score, "risk")),
            committee=str(getattr(score, "committee")),
            portfolio_impact=str(getattr(score, "portfolio_impact")),
            change_summary=str(getattr(snapshot, "change_summary")),
            should_alert=bool(getattr(snapshot, "should_alert")),
            alert_level=alert_level,
            change_categories=categories,
            conviction_change_points=conviction_change_points,
        )


@dataclass(frozen=True, slots=True)
class AlertMessage:
    user_id: str
    snapshot_identifier: str
    as_of: datetime
    topics: tuple[AlertTopic, ...]
    priority: AlertPriority
    subject: str
    body: str
    channels: tuple[AlertChannel, ...]
    email_address: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("user_id", "snapshot_identifier", "subject", "body"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        _aware(self.as_of, "as_of")
        topics = tuple(dict.fromkeys(AlertTopic(value) for value in self.topics))
        channels = tuple(dict.fromkeys(AlertChannel(value) for value in self.channels))
        if not topics:
            raise ValueError("topics cannot be empty")
        if not channels:
            raise ValueError("channels cannot be empty")
        object.__setattr__(self, "topics", topics)
        object.__setattr__(self, "channels", channels)
        if not isinstance(self.priority, AlertPriority):
            object.__setattr__(self, "priority", AlertPriority(self.priority))
        if AlertChannel.EMAIL in channels:
            if self.email_address is None:
                raise ValueError("email_address is required for email delivery")
            email = _required_text(self.email_address, "email_address").casefold()
            if "@" not in email:
                raise ValueError("email_address must be valid")
            object.__setattr__(self, "email_address", email)

    @property
    def event_identifier(self) -> str:
        return self.snapshot_identifier


@dataclass(frozen=True, slots=True)
class AlertDelivery:
    delivery_id: str
    user_id: str
    snapshot_identifier: str
    channel: AlertChannel
    topics: tuple[AlertTopic, ...]
    priority: AlertPriority
    status: DeliveryStatus
    subject: str
    body: str
    created_at: datetime
    updated_at: datetime
    attempts: int
    next_attempt_at: datetime | None = None
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "delivery_id",
            "user_id",
            "snapshot_identifier",
            "subject",
            "body",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        for field_name in ("next_attempt_at", "sent_at", "acknowledged_at"):
            value = getattr(self, field_name)
            if value is not None:
                _aware(value, field_name)
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise TypeError("attempts must be an int")
        if self.attempts < 0:
            raise ValueError("attempts cannot be negative")

    @property
    def event_identifier(self) -> str:
        return self.snapshot_identifier


@dataclass(frozen=True, slots=True)
class ScheduledCycleRecord:
    cycle_key: str
    scheduled_for: datetime
    status: CycleStatus
    attempts: int
    started_at: datetime | None
    completed_at: datetime | None
    snapshot_identifier: str | None
    next_attempt_at: datetime | None
    error: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cycle_key", _required_text(self.cycle_key, "cycle_key"))
        _aware(self.scheduled_for, "scheduled_for")
        for field_name in ("started_at", "completed_at", "next_attempt_at"):
            value = getattr(self, field_name)
            if value is not None:
                _aware(value, field_name)
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise TypeError("attempts must be an int")
        if self.attempts < 0:
            raise ValueError("attempts cannot be negative")


__all__ = [
    "AlertChannel",
    "AlertDelivery",
    "AlertMessage",
    "AlertPriority",
    "AlertSnapshot",
    "AlertTopic",
    "CycleStatus",
    "DeliveryPreference",
    "DeliveryStatus",
    "ScheduledCycleRecord",
]
