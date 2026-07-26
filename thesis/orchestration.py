"""Production orchestration for scheduled and event-driven thesis review.

The orchestrator may challenge a thesis, persist a new immutable snapshot, and
queue a proposal for CIO review.  It has no portfolio-construction, order, or
execution authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from cio import ThesisState
from cio.persistence import (
    CIOJournalEventType,
    SQLiteCIOJournal,
    serialize_thesis_review,
    serialize_thesis_snapshot,
)
from thesis.models import (
    LivingThesis,
    ThesisEvidenceUpdate,
    ThesisReview,
    ThesisReviewProposal,
)
from thesis.service import ThesisMonitor, ThesisMonitoringPolicy


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as error:
        raise ValueError("payload must contain finite JSON values") from error


def _fingerprint(*parts: str) -> str:
    canonical = "\x1f".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ThesisMonitoringError(RuntimeError):
    """Raised when a governed monitoring cycle cannot complete safely."""


class ThesisMonitoringIntegrityError(ThesisMonitoringError):
    """Raised when append-only monitoring evidence fails integrity checks."""


class ThesisTriggerSource(str, Enum):
    SCHEDULED = "scheduled"
    EVENT = "event"
    MANUAL = "manual"


class ThesisReviewPriority(str, Enum):
    STANDARD = "standard"
    HIGH = "high"
    URGENT = "urgent"


class ThesisMonitoringEventType(str, Enum):
    TRIGGER_RECEIVED = "trigger_received"
    ATTEMPT_STARTED = "attempt_started"
    REVIEW_COMPLETED = "review_completed"
    REVIEW_FAILED = "review_failed"
    DEDUPLICATED = "deduplicated"
    REVIEW_QUEUED = "review_queued"
    NOTIFICATION_PUBLISHED = "notification_published"
    NOTIFICATION_SUPPRESSED = "notification_suppressed"


@dataclass(frozen=True, slots=True)
class ThesisMonitoringTrigger:
    identifier: str
    thesis_identifier: str
    source: ThesisTriggerSource
    as_of: datetime
    reason: str
    evidence_fingerprint: str
    priority: ThesisReviewPriority = ThesisReviewPriority.STANDARD

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "thesis_identifier",
            "reason",
            "evidence_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.source, ThesisTriggerSource):
            raise TypeError("source must be ThesisTriggerSource")
        if not isinstance(self.priority, ThesisReviewPriority):
            raise TypeError("priority must be ThesisReviewPriority")

    @classmethod
    def scheduled(cls, thesis: LivingThesis, *, as_of: datetime) -> "ThesisMonitoringTrigger":
        resolved = _aware(as_of, field_name="as_of")
        return cls(
            identifier=(
                f"thesis-trigger:scheduled:{thesis.identifier}:"
                f"{thesis.next_review_at.isoformat()}"
            ),
            thesis_identifier=thesis.identifier,
            source=ThesisTriggerSource.SCHEDULED,
            as_of=resolved,
            reason="Scheduled living-thesis review is due.",
            evidence_fingerprint=_fingerprint(
                thesis.identifier,
                thesis.next_review_at.isoformat(),
                *thesis.evidence_identifiers,
            ),
        )


@dataclass(frozen=True, slots=True)
class CIOThesisReviewQueueItem:
    identifier: str
    thesis_identifier: str
    review_identifier: str
    proposal: ThesisReviewProposal
    priority: ThesisReviewPriority
    created_at: datetime
    asset: str
    rationale: str
    evidence_identifiers: tuple[str, ...]
    replacement_opportunity_edge: float

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "thesis_identifier",
            "review_identifier",
            "asset",
            "rationale",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.created_at, field_name="created_at")
        if not isinstance(self.proposal, ThesisReviewProposal):
            raise TypeError("proposal must be ThesisReviewProposal")
        if not isinstance(self.priority, ThesisReviewPriority):
            raise TypeError("priority must be ThesisReviewPriority")
        if self.proposal is ThesisReviewProposal.CONTINUE_MONITORING:
            raise ValueError("continue-monitoring reviews do not enter the CIO queue")
        if not self.evidence_identifiers:
            raise ValueError("evidence_identifiers cannot be empty")


@dataclass(frozen=True, slots=True)
class ThesisMonitoringResult:
    trigger_identifier: str
    thesis_identifier: str
    review_identifier: str | None
    status: str
    required_cio_review: bool
    queue_item_identifier: str | None = None
    notification_reference: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ThesisMonitoringCycleResult:
    evaluated_at: datetime
    results: tuple[ThesisMonitoringResult, ...]

    @property
    def failures(self) -> tuple[ThesisMonitoringResult, ...]:
        return tuple(item for item in self.results if item.status == "failed")

    @property
    def all_success(self) -> bool:
        return not self.failures


class ThesisEvidenceProvider(Protocol):
    def update_for(
        self,
        thesis: LivingThesis,
        *,
        as_of: datetime,
        opportunity_context: Mapping[str, Any] | None,
    ) -> ThesisEvidenceUpdate: ...


class ThesisNotificationPublisher(Protocol):
    def publish(self, item: CIOThesisReviewQueueItem) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ThesisMonitoringOperationalEvent:
    sequence: int
    event_identifier: str
    thesis_identifier: str
    trigger_identifier: str
    event_type: ThesisMonitoringEventType
    occurred_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


class SQLiteThesisMonitoringStore:
    """Append-only operational evidence for thesis-monitoring orchestration."""

    _GENESIS_HASH = "0" * 64

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS thesis_monitoring_events (
                    sequence INTEGER PRIMARY KEY,
                    event_identifier TEXT NOT NULL UNIQUE,
                    thesis_identifier TEXT NOT NULL,
                    trigger_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS thesis_monitoring_trigger_sequence
                ON thesis_monitoring_events (trigger_identifier, sequence);
                CREATE INDEX IF NOT EXISTS thesis_monitoring_thesis_sequence
                ON thesis_monitoring_events (thesis_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS thesis_monitoring_prevent_update
                BEFORE UPDATE ON thesis_monitoring_events
                BEGIN SELECT RAISE(ABORT, 'thesis monitoring store is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS thesis_monitoring_prevent_delete
                BEFORE DELETE ON thesis_monitoring_events
                BEGIN SELECT RAISE(ABORT, 'thesis monitoring store is append-only'); END;
                """
            )

    def append(
        self,
        *,
        event_identifier: str,
        thesis_identifier: str,
        trigger_identifier: str,
        event_type: ThesisMonitoringEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> ThesisMonitoringOperationalEvent:
        identifier = _required_text(event_identifier, field_name="event_identifier")
        thesis_id = _required_text(thesis_identifier, field_name="thesis_identifier")
        trigger_id = _required_text(trigger_identifier, field_name="trigger_identifier")
        occurred = _aware(occurred_at, field_name="occurred_at")
        recorded = _aware(self._clock(), field_name="clock")
        payload_json = _canonical_json(payload)
        if not isinstance(event_type, ThesisMonitoringEventType):
            raise TypeError("event_type must be ThesisMonitoringEventType")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM thesis_monitoring_events WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                event = self._from_row(existing)
                if (
                    event.thesis_identifier != thesis_id
                    or event.trigger_identifier != trigger_id
                    or event.event_type is not event_type
                    or event.occurred_at != occurred
                    or event.payload_json != payload_json
                ):
                    raise ValueError("event identifier already exists with different content")
                connection.rollback()
                return event
            previous = connection.execute(
                "SELECT sequence, content_hash FROM thesis_monitoring_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous else 1
            previous_hash = str(previous["content_hash"]) if previous else self._GENESIS_HASH
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                thesis_identifier=thesis_id,
                trigger_identifier=trigger_id,
                event_type=event_type,
                occurred_at=occurred,
                recorded_at=recorded,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                """INSERT INTO thesis_monitoring_events
                (sequence,event_identifier,thesis_identifier,trigger_identifier,event_type,
                 occurred_at,recorded_at,payload_json,previous_hash,content_hash)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    sequence,
                    identifier,
                    thesis_id,
                    trigger_id,
                    event_type.value,
                    occurred.isoformat(),
                    recorded.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            connection.commit()
            return ThesisMonitoringOperationalEvent(
                sequence, identifier, thesis_id, trigger_id, event_type,
                occurred, payload_json, previous_hash, content_hash,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(
        self,
        *,
        trigger_identifier: str | None = None,
        thesis_identifier: str | None = None,
    ) -> tuple[ThesisMonitoringOperationalEvent, ...]:
        clauses: list[str] = []
        parameters: list[str] = []
        if trigger_identifier is not None:
            clauses.append("trigger_identifier = ?")
            parameters.append(trigger_identifier)
        if thesis_identifier is not None:
            clauses.append("thesis_identifier = ?")
            parameters.append(thesis_identifier)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM thesis_monitoring_events{where} ORDER BY sequence ASC",
                tuple(parameters),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def has_event(
        self,
        *,
        trigger_identifier: str,
        event_type: ThesisMonitoringEventType,
    ) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM thesis_monitoring_events WHERE trigger_identifier = ? AND event_type = ? LIMIT 1",
                (trigger_identifier, event_type.value),
            ).fetchone()
        return row is not None

    def completed_for_trigger(self, trigger_identifier: str) -> ThesisMonitoringOperationalEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM thesis_monitoring_events
                WHERE trigger_identifier = ? AND event_type = ?
                ORDER BY sequence DESC LIMIT 1""",
                (trigger_identifier, ThesisMonitoringEventType.REVIEW_COMPLETED.value),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def recent_completed_fingerprint(
        self,
        *,
        thesis_identifier: str,
        evidence_fingerprint: str,
        since: datetime,
    ) -> ThesisMonitoringOperationalEvent | None:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM thesis_monitoring_events
                WHERE thesis_identifier = ? AND event_type = ? AND occurred_at >= ?
                ORDER BY sequence DESC""",
                (
                    thesis_identifier,
                    ThesisMonitoringEventType.REVIEW_COMPLETED.value,
                    since.isoformat(),
                ),
            ).fetchall()
        for row in rows:
            event = self._from_row(row)
            if event.payload.get("trigger", {}).get("evidence_fingerprint") == evidence_fingerprint:
                return event
        return None

    def verify_integrity(self) -> bool:
        previous_hash = self._GENESIS_HASH
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM thesis_monitoring_events ORDER BY sequence ASC"
            ).fetchall()
        for expected, row in enumerate(rows, start=1):
            event = self._from_row(row)
            recorded_at = datetime.fromisoformat(str(row["recorded_at"]))
            if event.sequence != expected or event.previous_hash != previous_hash:
                raise ThesisMonitoringIntegrityError("monitoring event chain is not contiguous")
            content_hash = self._hash(
                sequence=event.sequence,
                event_identifier=event.event_identifier,
                thesis_identifier=event.thesis_identifier,
                trigger_identifier=event.trigger_identifier,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                recorded_at=recorded_at,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if content_hash != event.content_hash:
                raise ThesisMonitoringIntegrityError("monitoring event hash does not match")
            previous_hash = event.content_hash
        return True

    @staticmethod
    def _hash(**values: Any) -> str:
        normalized = dict(values)
        normalized["event_type"] = normalized["event_type"].value
        normalized["occurred_at"] = normalized["occurred_at"].isoformat()
        normalized["recorded_at"] = normalized["recorded_at"].isoformat()
        return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ThesisMonitoringOperationalEvent:
        return ThesisMonitoringOperationalEvent(
            sequence=int(row["sequence"]),
            event_identifier=str(row["event_identifier"]),
            thesis_identifier=str(row["thesis_identifier"]),
            trigger_identifier=str(row["trigger_identifier"]),
            event_type=ThesisMonitoringEventType(str(row["event_type"])),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def thesis_from_payload(payload: Mapping[str, Any]) -> LivingThesis:
    return LivingThesis(
        identifier=str(payload["identifier"]),
        decision_identifier=str(payload["decision_identifier"]),
        candidate_identifier=str(payload["candidate_identifier"]),
        asset=str(payload["asset"]),
        created_at=datetime.fromisoformat(str(payload["created_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        state=ThesisState(str(payload["state"])),
        original_rationale=str(payload["original_rationale"]),
        assumptions=tuple(payload["assumptions"]),
        expected_return=float(payload["expected_return"]),
        expected_downside=float(payload["expected_downside"]),
        horizon_days=int(payload["horizon_days"]),
        catalysts=tuple(payload["catalysts"]),
        invalidation_conditions=tuple(payload["invalidation_conditions"]),
        monitoring_indicators=tuple(payload["monitoring_indicators"]),
        initial_confidence=float(payload["initial_confidence"]),
        current_confidence=float(payload["current_confidence"]),
        evidence_identifiers=tuple(payload["evidence_identifiers"]),
        performance_since_approval=float(payload["performance_since_approval"]),
        next_review_at=datetime.fromisoformat(str(payload["next_review_at"])),
        review_count=int(payload.get("review_count", 0)),
    )


def review_from_payload(payload: Mapping[str, Any]) -> ThesisReview:
    return ThesisReview(
        identifier=str(payload["identifier"]),
        thesis_identifier=str(payload["thesis_identifier"]),
        reviewed_at=datetime.fromisoformat(str(payload["reviewed_at"])),
        prior_state=ThesisState(str(payload["prior_state"])),
        new_state=ThesisState(str(payload["new_state"])),
        proposal=ThesisReviewProposal(str(payload["proposal"])),
        rationale=str(payload["rationale"]),
        evidence_identifiers=tuple(payload["evidence_identifiers"]),
        current_expected_return=float(payload["current_expected_return"]),
        expected_return_change=float(payload["expected_return_change"]),
        current_expected_downside=float(payload["current_expected_downside"]),
        downside_change=float(payload["downside_change"]),
        current_confidence=float(payload["current_confidence"]),
        confidence_change=float(payload["confidence_change"]),
        performance_since_approval=float(payload["performance_since_approval"]),
        replacement_opportunity_edge=float(payload["replacement_opportunity_edge"]),
        triggered_invalidation_conditions=tuple(payload["triggered_invalidation_conditions"]),
        required_cio_review=bool(payload["required_cio_review"]),
        next_review_at=datetime.fromisoformat(str(payload["next_review_at"])),
        policy_version=str(payload["policy_version"]),
    )


def _trigger_payload(trigger: ThesisMonitoringTrigger) -> dict[str, Any]:
    return {
        "identifier": trigger.identifier,
        "thesis_identifier": trigger.thesis_identifier,
        "source": trigger.source.value,
        "as_of": trigger.as_of.isoformat(),
        "reason": trigger.reason,
        "evidence_fingerprint": trigger.evidence_fingerprint,
        "priority": trigger.priority.value,
    }


def _queue_priority(review: ThesisReview, trigger: ThesisMonitoringTrigger) -> ThesisReviewPriority:
    if review.proposal in {ThesisReviewProposal.INVALIDATE, ThesisReviewProposal.REVIEW_EXIT}:
        return ThesisReviewPriority.URGENT
    if review.proposal in {ThesisReviewProposal.REVIEW_REDUCE, ThesisReviewProposal.REVIEW_EVIDENCE}:
        return ThesisReviewPriority.HIGH
    return trigger.priority


class ThesisMonitoringOrchestrator:
    """Run independent thesis reviews and selectively escalate material changes."""

    _REVIEWABLE_STATES = {
        ThesisState.ACTIVE,
        ThesisState.STRENGTHENING,
        ThesisState.STABLE,
        ThesisState.WEAKENING,
        ThesisState.REDUCED,
    }

    def __init__(
        self,
        *,
        journal: SQLiteCIOJournal,
        store: SQLiteThesisMonitoringStore,
        evidence_provider: ThesisEvidenceProvider,
        monitor: ThesisMonitor | None = None,
        notification_publisher: ThesisNotificationPublisher | None = None,
        suppression_window: timedelta = timedelta(hours=24),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.journal = journal
        self.store = store
        self.evidence_provider = evidence_provider
        self.monitor = monitor or ThesisMonitor()
        self.notification_publisher = notification_publisher
        if suppression_window.total_seconds() < 0:
            raise ValueError("suppression_window cannot be negative")
        self.suppression_window = suppression_window
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        as_of: datetime | None = None,
        event_triggers: Sequence[ThesisMonitoringTrigger] = (),
        include_scheduled: bool = True,
    ) -> ThesisMonitoringCycleResult:
        evaluated_at = _aware(as_of or self._clock(), field_name="as_of")
        self.journal.verify_integrity()
        self.store.verify_integrity()
        theses = self._latest_theses()
        triggers: list[ThesisMonitoringTrigger] = list(event_triggers)
        if include_scheduled:
            triggers.extend(
                ThesisMonitoringTrigger.scheduled(thesis, as_of=evaluated_at)
                for thesis in theses.values()
                if thesis.state in self._REVIEWABLE_STATES
                and thesis.next_review_at <= evaluated_at
            )
        unique: dict[str, ThesisMonitoringTrigger] = {}
        for trigger in triggers:
            if trigger.identifier in unique and unique[trigger.identifier] != trigger:
                raise ThesisMonitoringError("trigger identifier has conflicting content")
            unique[trigger.identifier] = trigger
        opportunity_context = self._latest_opportunity_context()
        results: list[ThesisMonitoringResult] = []
        for trigger in sorted(unique.values(), key=lambda item: (item.as_of, item.identifier)):
            thesis = theses.get(trigger.thesis_identifier)
            if thesis is None:
                results.append(self._record_failure(trigger, "thesis snapshot is unavailable"))
                continue
            try:
                results.append(self._process(trigger, thesis, opportunity_context))
                latest = self.journal.latest(
                    aggregate_identifier=thesis.identifier,
                    event_type=CIOJournalEventType.THESIS_SNAPSHOT,
                )
                if latest is not None:
                    theses[thesis.identifier] = thesis_from_payload(latest.payload)
            except Exception as error:
                results.append(self._record_failure(trigger, str(error)))
        return ThesisMonitoringCycleResult(evaluated_at=evaluated_at, results=tuple(results))

    def _process(
        self,
        trigger: ThesisMonitoringTrigger,
        thesis: LivingThesis,
        opportunity_context: Mapping[str, Any] | None,
    ) -> ThesisMonitoringResult:
        prior = self.store.completed_for_trigger(trigger.identifier)
        if prior is not None:
            return self._replay_completed(prior)
        recent = self.store.recent_completed_fingerprint(
            thesis_identifier=thesis.identifier,
            evidence_fingerprint=trigger.evidence_fingerprint,
            since=trigger.as_of - self.suppression_window,
        )
        if recent is not None:
            self.store.append(
                event_identifier=f"event:{trigger.identifier}:deduplicated",
                thesis_identifier=thesis.identifier,
                trigger_identifier=trigger.identifier,
                event_type=ThesisMonitoringEventType.DEDUPLICATED,
                occurred_at=trigger.as_of,
                payload={"trigger": _trigger_payload(trigger), "prior_event": recent.event_identifier},
            )
            return ThesisMonitoringResult(
                trigger.identifier, thesis.identifier, None, "deduplicated", False
            )
        self.store.append(
            event_identifier=f"event:{trigger.identifier}:received",
            thesis_identifier=thesis.identifier,
            trigger_identifier=trigger.identifier,
            event_type=ThesisMonitoringEventType.TRIGGER_RECEIVED,
            occurred_at=trigger.as_of,
            payload={"trigger": _trigger_payload(trigger)},
        )
        self.store.append(
            event_identifier=f"event:{trigger.identifier}:attempt",
            thesis_identifier=thesis.identifier,
            trigger_identifier=trigger.identifier,
            event_type=ThesisMonitoringEventType.ATTEMPT_STARTED,
            occurred_at=trigger.as_of,
            payload={"trigger": _trigger_payload(trigger), "thesis_review_count": thesis.review_count},
        )
        update = self.evidence_provider.update_for(
            thesis, as_of=trigger.as_of, opportunity_context=opportunity_context
        )
        if update.thesis_identifier != thesis.identifier:
            raise ThesisMonitoringError("evidence provider returned the wrong thesis")
        if update.as_of != trigger.as_of:
            raise ThesisMonitoringError("evidence update timestamp must equal trigger timestamp")
        review = self.monitor.evaluate(thesis, update)
        snapshot = thesis.apply(review)
        queue_item = self._queue_item(snapshot, review, trigger) if review.required_cio_review else None
        payload = {
            "trigger": _trigger_payload(trigger),
            "review": serialize_thesis_review(review),
            "snapshot": serialize_thesis_snapshot(snapshot),
            "queue_item": None if queue_item is None else self._queue_payload(queue_item),
        }
        completed = self.store.append(
            event_identifier=f"event:{trigger.identifier}:completed",
            thesis_identifier=thesis.identifier,
            trigger_identifier=trigger.identifier,
            event_type=ThesisMonitoringEventType.REVIEW_COMPLETED,
            occurred_at=review.reviewed_at,
            payload=payload,
        )
        return self._publish_completed(completed)

    def _replay_completed(self, event: ThesisMonitoringOperationalEvent) -> ThesisMonitoringResult:
        return self._publish_completed(event)

    def _publish_completed(self, event: ThesisMonitoringOperationalEvent) -> ThesisMonitoringResult:
        payload = event.payload
        review = review_from_payload(payload["review"])
        snapshot = thesis_from_payload(payload["snapshot"])
        self.journal.append_thesis_review(review)
        self.journal.append_thesis_snapshot(snapshot)
        queue_payload = payload.get("queue_item")
        queue_item_identifier: str | None = None
        notification_reference: str | None = None
        if queue_payload is not None:
            queue = self._queue_from_payload(queue_payload)
            queue_item_identifier = queue.identifier
            self.store.append(
                event_identifier=f"event:{event.trigger_identifier}:queued",
                thesis_identifier=event.thesis_identifier,
                trigger_identifier=event.trigger_identifier,
                event_type=ThesisMonitoringEventType.REVIEW_QUEUED,
                occurred_at=queue.created_at,
                payload={"queue_item": queue_payload},
            )
            if self.notification_publisher is None:
                self.store.append(
                    event_identifier=f"event:{event.trigger_identifier}:notification-suppressed",
                    thesis_identifier=event.thesis_identifier,
                    trigger_identifier=event.trigger_identifier,
                    event_type=ThesisMonitoringEventType.NOTIFICATION_SUPPRESSED,
                    occurred_at=queue.created_at,
                    payload={"reason": "notification publisher is not configured"},
                )
            else:
                published = self.store.has_event(
                    trigger_identifier=event.trigger_identifier,
                    event_type=ThesisMonitoringEventType.NOTIFICATION_PUBLISHED,
                )
                if not published:
                    reference = self.notification_publisher.publish(queue)
                    notification_reference = reference or queue.identifier
                    self.store.append(
                        event_identifier=f"event:{event.trigger_identifier}:notification-published",
                        thesis_identifier=event.thesis_identifier,
                        trigger_identifier=event.trigger_identifier,
                        event_type=ThesisMonitoringEventType.NOTIFICATION_PUBLISHED,
                        occurred_at=queue.created_at,
                        payload={"reference": notification_reference},
                    )
                else:
                    notification_reference = queue.identifier
        else:
            self.store.append(
                event_identifier=f"event:{event.trigger_identifier}:notification-suppressed",
                thesis_identifier=event.thesis_identifier,
                trigger_identifier=event.trigger_identifier,
                event_type=ThesisMonitoringEventType.NOTIFICATION_SUPPRESSED,
                occurred_at=review.reviewed_at,
                payload={"reason": "no material CIO-review proposal"},
            )
        return ThesisMonitoringResult(
            trigger_identifier=event.trigger_identifier,
            thesis_identifier=event.thesis_identifier,
            review_identifier=review.identifier,
            status="completed",
            required_cio_review=review.required_cio_review,
            queue_item_identifier=queue_item_identifier,
            notification_reference=notification_reference,
        )

    def _record_failure(self, trigger: ThesisMonitoringTrigger, error: str) -> ThesisMonitoringResult:
        self.store.append(
            event_identifier=f"event:{trigger.identifier}:failed",
            thesis_identifier=trigger.thesis_identifier,
            trigger_identifier=trigger.identifier,
            event_type=ThesisMonitoringEventType.REVIEW_FAILED,
            occurred_at=trigger.as_of,
            payload={"trigger": _trigger_payload(trigger), "error": _required_text(error, field_name="error")},
        )
        return ThesisMonitoringResult(
            trigger.identifier, trigger.thesis_identifier, None, "failed", False, error=error
        )

    def _latest_theses(self) -> dict[str, LivingThesis]:
        events = self.journal.events(event_type=CIOJournalEventType.THESIS_SNAPSHOT, limit=10000)
        latest: dict[str, Any] = {}
        for event in events:
            latest[event.aggregate_identifier] = event
        return {identifier: thesis_from_payload(event.payload) for identifier, event in latest.items()}

    def _latest_opportunity_context(self) -> Mapping[str, Any] | None:
        event = self.journal.latest(event_type=CIOJournalEventType.OPPORTUNITY_QUEUE)
        return None if event is None else event.payload

    @staticmethod
    def _queue_item(
        snapshot: LivingThesis,
        review: ThesisReview,
        trigger: ThesisMonitoringTrigger,
    ) -> CIOThesisReviewQueueItem:
        return CIOThesisReviewQueueItem(
            identifier=f"cio-thesis-review:{review.identifier}",
            thesis_identifier=review.thesis_identifier,
            review_identifier=review.identifier,
            proposal=review.proposal,
            priority=_queue_priority(review, trigger),
            created_at=review.reviewed_at,
            asset=snapshot.asset,
            rationale=review.rationale,
            evidence_identifiers=review.evidence_identifiers,
            replacement_opportunity_edge=review.replacement_opportunity_edge,
        )

    @staticmethod
    def _queue_payload(item: CIOThesisReviewQueueItem) -> dict[str, Any]:
        return {
            "identifier": item.identifier,
            "thesis_identifier": item.thesis_identifier,
            "review_identifier": item.review_identifier,
            "proposal": item.proposal.value,
            "priority": item.priority.value,
            "created_at": item.created_at.isoformat(),
            "asset": item.asset,
            "rationale": item.rationale,
            "evidence_identifiers": list(item.evidence_identifiers),
            "replacement_opportunity_edge": item.replacement_opportunity_edge,
        }

    @staticmethod
    def _queue_from_payload(payload: Mapping[str, Any]) -> CIOThesisReviewQueueItem:
        return CIOThesisReviewQueueItem(
            identifier=str(payload["identifier"]),
            thesis_identifier=str(payload["thesis_identifier"]),
            review_identifier=str(payload["review_identifier"]),
            proposal=ThesisReviewProposal(str(payload["proposal"])),
            priority=ThesisReviewPriority(str(payload["priority"])),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            asset=str(payload["asset"]),
            rationale=str(payload["rationale"]),
            evidence_identifiers=tuple(payload["evidence_identifiers"]),
            replacement_opportunity_edge=float(payload["replacement_opportunity_edge"]),
        )


__all__ = [
    "CIOThesisReviewQueueItem",
    "SQLiteThesisMonitoringStore",
    "ThesisEvidenceProvider",
    "ThesisMonitoringCycleResult",
    "ThesisMonitoringError",
    "ThesisMonitoringEventType",
    "ThesisMonitoringIntegrityError",
    "ThesisMonitoringOperationalEvent",
    "ThesisMonitoringOrchestrator",
    "ThesisMonitoringResult",
    "ThesisMonitoringTrigger",
    "ThesisNotificationPublisher",
    "ThesisReviewPriority",
    "ThesisTriggerSource",
    "review_from_payload",
    "thesis_from_payload",
]
