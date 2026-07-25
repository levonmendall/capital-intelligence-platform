"""Idempotent daily scheduling, selective alert policy, and delivery workers."""

from __future__ import annotations

import smtplib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from delivery.models import (
    AlertCandidate,
    AlertPreference,
    AlertTopic,
    CycleRecord,
    DeliveryChannel,
    DeliveryRecord,
    DeliveryStatus,
)
from delivery.store import SQLiteDeliveryStore


@dataclass(frozen=True, slots=True)
class ScheduledCycleResult:
    cycle: CycleRecord | None
    snapshot_identifier: str | None
    candidates: tuple[AlertCandidate, ...]
    deliveries: tuple[DeliveryRecord, ...]
    skipped: bool = False


class SelectiveAlertPolicy:
    """Convert one canonical snapshot into a small set of material candidates."""

    def candidates(self, *, cycle_id: str, snapshot: Mapping[str, object]) -> tuple[AlertCandidate, ...]:
        identifier = str(snapshot.get("identifier", "unknown-snapshot"))
        as_of = datetime.fromisoformat(str(snapshot["as_of"]))
        score = snapshot.get("score") if isinstance(snapshot.get("score"), Mapping) else {}
        environment = snapshot.get("environment") if isinstance(snapshot.get("environment"), Mapping) else {}
        change = snapshot.get("change") if isinstance(snapshot.get("change"), Mapping) else {}
        decision = snapshot.get("decision_card") if isinstance(snapshot.get("decision_card"), Mapping) else {}
        results: list[AlertCandidate] = []

        should_alert = bool(snapshot.get("should_alert", False))
        changed_materially = bool(snapshot.get("changed_materially", False))
        risk = str(score.get("risk", "Unknown"))
        alert_level = str(environment.get("alert_level", "silent"))
        change_summary = str(snapshot.get("change_summary", "No material change."))
        portfolio_impact = str(score.get("portfolio_impact", "Review the portfolio context."))

        if should_alert and alert_level.lower() == "urgent":
            results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.URGENT_RISK, "urgent", "Urgent portfolio risk review", change_summary))
        if changed_materially:
            results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.ENVIRONMENT_CHANGE, "material", "Market environment changed", change_summary))
        committee_outcome = str(decision.get("committee_outcome", ""))
        if change.get("committee_changed") is True or (changed_materially and committee_outcome):
            results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.COMMITTEE_CHANGE, "material", "Committee stance changed", str(decision.get("decision", change_summary))))
        if should_alert and portfolio_impact:
            results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.PORTFOLIO_REVIEW, "material", "Portfolio review recommended", portfolio_impact))
        score_delta = snapshot.get("score_delta")
        if isinstance(score_delta, int) and score_delta != 0:
            results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.CONVICTION_CHANGE, "informational", "Capital Intelligence changed", f"The daily score moved {score_delta:+d} points. Risk remains {risk}."))
        results.append(self._candidate(cycle_id, identifier, as_of, AlertTopic.DAILY_SUMMARY, "summary", "Today's Capital Intelligence", f"Score {score.get('score', '—')}. {change_summary}"))
        return tuple(results)

    @staticmethod
    def _candidate(cycle_id: str, snapshot_id: str, as_of: datetime, topic: AlertTopic,
                   severity: str, headline: str, explanation: str) -> AlertCandidate:
        return AlertCandidate(cycle_id, snapshot_id, as_of, topic, severity, headline, explanation)


class DeliveryPlanner:
    """Apply user preferences and enqueue deduplicated deliveries."""

    def __init__(self, store: SQLiteDeliveryStore) -> None:
        self.store = store

    def plan(self, candidates: tuple[AlertCandidate, ...]) -> tuple[DeliveryRecord, ...]:
        planned: list[DeliveryRecord] = []
        for preference in self.store.preferences():
            for candidate in candidates:
                if candidate.topic not in preference.enabled_topics:
                    continue
                if candidate.topic is AlertTopic.CONVICTION_CHANGE:
                    points = self._change_points(candidate.explanation)
                    if points < preference.conviction_threshold:
                        continue
                if not self._delivery_window_open(preference, candidate.as_of):
                    continue
                for channel in preference.channels:
                    key = ":".join((candidate.snapshot_identifier, preference.user_id, candidate.topic.value, channel.value))
                    planned.append(self.store.enqueue(
                        deduplication_key=key,
                        cycle_id=candidate.cycle_id,
                        user_id=preference.user_id,
                        investor_identifier=preference.investor_identifier,
                        topic=candidate.topic,
                        channel=channel,
                        headline=candidate.headline,
                        explanation=candidate.explanation,
                    ))
        return tuple(planned)

    @staticmethod
    def _change_points(explanation: str) -> int:
        for token in explanation.replace("+", "").split():
            try:
                return abs(int(token))
            except ValueError:
                continue
        return 0

    @staticmethod
    def _delivery_window_open(preference: AlertPreference, as_of: datetime) -> bool:
        try:
            local = as_of.astimezone(ZoneInfo(preference.timezone_name))
        except ZoneInfoNotFoundError:
            return False
        if AlertTopic.DAILY_SUMMARY not in preference.enabled_topics:
            return True
        # Event alerts are immediate. Daily summary is available once the preferred local time arrives.
        return local.timetz().replace(tzinfo=None) >= preference.delivery_time


class InAppSender:
    def send(self, record: DeliveryRecord) -> None:
        del record


class SmtpEmailSender:
    def __init__(self, *, host: str, port: int, sender: str, username: str | None = None,
                 password: str | None = None, use_starttls: bool = True) -> None:
        self.host, self.port, self.sender = host, port, sender
        self.username, self.password, self.use_starttls = username, password, use_starttls

    def send(self, record: DeliveryRecord, *, recipient: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = record.headline
        message.set_content(record.explanation)
        with smtplib.SMTP(self.host, self.port, timeout=20) as client:
            if self.use_starttls:
                client.starttls()
            if self.username:
                client.login(self.username, self.password or "")
            client.send_message(message)


class DeliveryWorker:
    """Send due deliveries with bounded exponential retry and no cycle rerun."""

    def __init__(self, store: SQLiteDeliveryStore, *, in_app_sender=None, email_sender=None,
                 email_lookup: Callable[[str], str | None] | None = None, max_attempts: int = 5) -> None:
        self.store = store
        self.in_app_sender = in_app_sender or InAppSender()
        self.email_sender = email_sender
        self.email_lookup = email_lookup or (lambda user_id: None)
        self.max_attempts = max_attempts

    def run_once(self, *, limit: int = 100) -> tuple[DeliveryRecord, ...]:
        results: list[DeliveryRecord] = []
        for record in self.store.due(limit=limit):
            if record.attempts >= self.max_attempts:
                continue
            try:
                if record.channel is DeliveryChannel.IN_APP:
                    self.in_app_sender.send(record)
                else:
                    recipient = self.email_lookup(record.user_id)
                    if not recipient or self.email_sender is None:
                        raise RuntimeError("email delivery is not configured")
                    self.email_sender.send(record, recipient=recipient)
            except Exception as error:
                delay = timedelta(minutes=min(60, 2 ** record.attempts))
                results.append(self.store.mark_failed(record.delivery_id, str(error), retry_after=delay))
            else:
                results.append(self.store.mark_sent(record.delivery_id))
        return tuple(results)


class DailyCycleScheduler:
    """Acquire one market-date lease, run once, persist, then plan delivery."""

    def __init__(self, store: SQLiteDeliveryStore, *, run_snapshot: Callable[[datetime], Mapping[str, object]],
                 policy: SelectiveAlertPolicy | None = None) -> None:
        self.store = store
        self.run_snapshot = run_snapshot
        self.policy = policy or SelectiveAlertPolicy()
        self.planner = DeliveryPlanner(store)

    def run_market_date(self, market_date: date, *, as_of: datetime | None = None) -> ScheduledCycleResult:
        cycle = self.store.acquire_cycle(market_date.isoformat())
        if cycle is None:
            return ScheduledCycleResult(None, None, (), (), skipped=True)
        resolved_as_of = as_of or datetime.combine(market_date, datetime.min.time(), tzinfo=timezone.utc)
        try:
            snapshot = self.run_snapshot(resolved_as_of)
            snapshot_identifier = str(snapshot["identifier"])
            candidates = self.policy.candidates(cycle_id=cycle.cycle_id, snapshot=snapshot)
            deliveries = self.planner.plan(candidates)
            completed = self.store.complete_cycle(cycle.cycle_id, snapshot_identifier)
        except Exception as error:
            self.store.fail_cycle(cycle.cycle_id, str(error))
            raise
        return ScheduledCycleResult(completed, snapshot_identifier, candidates, deliveries)


__all__ = [
    "DailyCycleScheduler",
    "DeliveryPlanner",
    "DeliveryWorker",
    "InAppSender",
    "ScheduledCycleResult",
    "SelectiveAlertPolicy",
    "SmtpEmailSender",
]
