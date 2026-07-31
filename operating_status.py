"""Truthful read-only operating status for the CIO interface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from api.config import ApiSettings
from api.repositories import JournalRepository
from delivery.models import CycleStatus
from delivery.store import SQLiteAlertStore
from operations import OperationalSettings, WorkerHeartbeatStore


@dataclass(frozen=True, slots=True)
class CIOOperatingStatus:
    state: str
    label: str
    headline: str
    detail: str
    observed_at: datetime
    cycle_status: str | None = None
    cycle_key: str | None = None
    next_retry_at: datetime | None = None
    last_briefing_at: datetime | None = None
    release: str = "unknown"

    @property
    def healthy(self) -> bool:
        return self.state == "healthy"


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def load_cio_operating_status(*, now: datetime | None = None) -> CIOOperatingStatus:
    timestamp = now or datetime.now(timezone.utc)
    release = (
        os.getenv("CAPITAL_INTELLIGENCE_RELEASE")
        or os.getenv("RENDER_GIT_COMMIT")
        or "unknown"
    ).strip()
    try:
        settings = ApiSettings.from_env()
        operational = OperationalSettings.from_env()
        heartbeat_ok, heartbeat_detail, heartbeat = WorkerHeartbeatStore(
            operational.worker_heartbeat_path
        ).health(
            maximum_age_seconds=max(180, int(settings.scheduler_poll_seconds) * 3),
            now=timestamp,
        )
        alert_path = settings.alert_database or settings.snapshot_database.with_name(
            "alerts.db"
        )
        latest_cycle = SQLiteAlertStore(alert_path).latest_cycle()
        briefing = JournalRepository(
            settings.journal_database, required=False
        ).latest_payload("daily_cio_briefing")
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        return CIOOperatingStatus(
            state="degraded",
            label="CIO degraded",
            headline="Operating status is unavailable",
            detail=str(error),
            observed_at=timestamp,
            release=release,
        )

    briefing_at = (
        _parse_timestamp(briefing.get("as_of"))
        if isinstance(briefing, dict)
        else None
    )
    cycle_status = None if latest_cycle is None else latest_cycle.status.value
    cycle_key = None if latest_cycle is None else latest_cycle.cycle_key
    next_retry = None if latest_cycle is None else latest_cycle.next_attempt_at
    if not heartbeat_ok or heartbeat is None:
        return CIOOperatingStatus(
            state="degraded",
            label="CIO degraded",
            headline="The CIO operator is not healthy",
            detail=heartbeat_detail,
            observed_at=timestamp,
            cycle_status=cycle_status,
            cycle_key=cycle_key,
            next_retry_at=next_retry,
            last_briefing_at=briefing_at,
            release=release,
        )
    if latest_cycle is not None and latest_cycle.status is CycleStatus.FAILED:
        retry_text = (
            ""
            if latest_cycle.next_attempt_at is None
            else f" Next retry: {latest_cycle.next_attempt_at.isoformat()}."
        )
        return CIOOperatingStatus(
            state="degraded",
            label="CIO degraded",
            headline="The latest CIO cycle failed",
            detail=(latest_cycle.error or "No failure detail was recorded.") + retry_text,
            observed_at=heartbeat.observed_at,
            cycle_status=cycle_status,
            cycle_key=cycle_key,
            next_retry_at=next_retry,
            last_briefing_at=briefing_at,
            release=release,
        )
    if heartbeat.status == "degraded":
        return CIOOperatingStatus(
            state="degraded",
            label="CIO degraded",
            headline="The CIO operator completed with degraded evidence",
            detail=heartbeat.detail or heartbeat_detail,
            observed_at=heartbeat.observed_at,
            cycle_status=cycle_status,
            cycle_key=cycle_key,
            next_retry_at=next_retry,
            last_briefing_at=briefing_at,
            release=release,
        )
    if latest_cycle is not None and latest_cycle.status is CycleStatus.RUNNING:
        return CIOOperatingStatus(
            state="processing",
            label="CIO processing",
            headline="A CIO cycle is in progress",
            detail=heartbeat.detail or "Evidence collection and CIO synthesis are running.",
            observed_at=heartbeat.observed_at,
            cycle_status=cycle_status,
            cycle_key=cycle_key,
            last_briefing_at=briefing_at,
            release=release,
        )
    if briefing_at is None:
        return CIOOperatingStatus(
            state="starting",
            label="Awaiting CIO cycle",
            headline="Awaiting the first completed CIO briefing",
            detail=heartbeat.detail or heartbeat_detail,
            observed_at=heartbeat.observed_at,
            cycle_status=cycle_status,
            cycle_key=cycle_key,
            release=release,
        )
    return CIOOperatingStatus(
        state="healthy",
        label="CIO healthy",
        headline="The CIO operating path is current",
        detail=heartbeat.detail or heartbeat_detail,
        observed_at=heartbeat.observed_at,
        cycle_status=cycle_status,
        cycle_key=cycle_key,
        last_briefing_at=briefing_at,
        release=release,
    )


__all__ = ["CIOOperatingStatus", "load_cio_operating_status"]
