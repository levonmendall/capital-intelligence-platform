"""Typed scheduled-cycle and selective-delivery contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum


class AlertTopic(str, Enum):
    DAILY_SUMMARY = "daily_summary"
    URGENT_RISK = "urgent_risk"
    ENVIRONMENT_CHANGE = "environment_change"
    COMMITTEE_CHANGE = "committee_change"
    PORTFOLIO_REVIEW = "portfolio_review"
    CONVICTION_CHANGE = "conviction_change"


class DeliveryChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"


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


@dataclass(frozen=True, slots=True)
class AlertPreference:
    user_id: str
    investor_identifier: str
    timezone_name: str = "UTC"
    delivery_time: time = time(8, 0)
    enabled_topics: frozenset[AlertTopic] = frozenset({
        AlertTopic.URGENT_RISK,
        AlertTopic.ENVIRONMENT_CHANGE,
        AlertTopic.COMMITTEE_CHANGE,
        AlertTopic.PORTFOLIO_REVIEW,
    })
    channels: frozenset[DeliveryChannel] = frozenset({DeliveryChannel.IN_APP})
    email_address: str | None = None
    conviction_threshold: int = 5

    def __post_init__(self) -> None:
        if not self.user_id.strip() or not self.investor_identifier.strip():
            raise ValueError("user_id and investor_identifier are required")
        if not self.timezone_name.strip():
            raise ValueError("timezone_name is required")
        if not 1 <= self.conviction_threshold <= 100:
            raise ValueError("conviction_threshold must be between 1 and 100")
        if DeliveryChannel.EMAIL in self.channels and not self.email_address:
            raise ValueError("email_address is required when email delivery is enabled")


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    cycle_id: str
    snapshot_identifier: str
    as_of: datetime
    topic: AlertTopic
    severity: str
    headline: str
    explanation: str
    mandate_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    delivery_id: str
    deduplication_key: str
    cycle_id: str
    user_id: str
    investor_identifier: str
    topic: AlertTopic
    channel: DeliveryChannel
    status: DeliveryStatus
    headline: str
    explanation: str
    attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class CycleRecord:
    cycle_id: str
    market_date: str
    status: CycleStatus
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    snapshot_identifier: str | None = None
    error: str | None = None


__all__ = [
    "AlertCandidate",
    "AlertPreference",
    "AlertTopic",
    "CycleRecord",
    "CycleStatus",
    "DeliveryChannel",
    "DeliveryRecord",
    "DeliveryStatus",
]
