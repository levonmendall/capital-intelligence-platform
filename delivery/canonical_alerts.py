"""Canonical event-driven alert planning for CIO operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from delivery.models import (
    AlertChannel,
    AlertMessage,
    AlertPriority,
    AlertTopic,
    DeliveryPreference,
)


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


def _value(value: object) -> str:
    return str(getattr(value, "value", value))


@dataclass(frozen=True, slots=True)
class CanonicalAlertEvent:
    identifier: str
    aggregate_identifier: str
    occurred_at: datetime
    topic: AlertTopic
    priority: AlertPriority
    subject: str
    body: str
    evidence_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "aggregate_identifier", "subject", "body"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        _aware(self.occurred_at, "occurred_at")
        if not isinstance(self.topic, AlertTopic):
            object.__setattr__(self, "topic", AlertTopic(self.topic))
        if self.topic not in {
            AlertTopic.CIO_DECISION,
            AlertTopic.THESIS,
            AlertTopic.OPPORTUNITY,
            AlertTopic.IMPLEMENTATION,
            AlertTopic.EVIDENCE,
            AlertTopic.DAILY_BRIEFING,
        }:
            raise ValueError("canonical alert events require a canonical topic")
        if not isinstance(self.priority, AlertPriority):
            object.__setattr__(self, "priority", AlertPriority(self.priority))
        evidence = tuple(dict.fromkeys(_required_text(v, "evidence_identifier") for v in self.evidence_identifiers))
        object.__setattr__(self, "evidence_identifiers", evidence)


@dataclass(frozen=True, slots=True)
class CanonicalAlertPlanningResult:
    message: AlertMessage | None
    suppression_reason: str | None


class CanonicalAlertPlanner:
    """Deliver only canonical event topics enabled by the account."""

    def plan(
        self,
        event: CanonicalAlertEvent,
        preference: DeliveryPreference,
    ) -> CanonicalAlertPlanningResult:
        if event.topic not in preference.topics:
            return CanonicalAlertPlanningResult(
                message=None,
                suppression_reason=(
                    f"Canonical {event.topic.value} events are disabled in this account's alert preferences."
                ),
            )
        channels = tuple(
            channel
            for channel in preference.channels
            if channel is not AlertChannel.EMAIL or preference.email_address is not None
        )
        if not channels:
            return CanonicalAlertPlanningResult(
                message=None,
                suppression_reason="No configured delivery channel is currently usable.",
            )
        evidence = ""
        if event.evidence_identifiers:
            evidence = "\nEvidence: " + ", ".join(event.evidence_identifiers)
        return CanonicalAlertPlanningResult(
            message=AlertMessage(
                user_id=preference.user_id,
                snapshot_identifier=event.identifier,
                as_of=event.occurred_at,
                topics=(event.topic,),
                priority=event.priority,
                subject=event.subject,
                body=event.body + evidence,
                channels=channels,
                email_address=preference.email_address,
            ),
            suppression_reason=None,
        )


def events_from_canonical_cycle(result: Any) -> tuple[CanonicalAlertEvent, ...]:
    """Translate one canonical cycle into decision-domain events, never scores."""

    cycle_id = _required_text(getattr(result, "identifier", None), "cycle identifier")
    occurred_at = _aware(getattr(result, "as_of", None), "cycle as_of")
    events: list[CanonicalAlertEvent] = []

    queue = getattr(result, "opportunity_queue", None)
    ranked = tuple(
        getattr(queue, "ranked", getattr(queue, "ranked_opportunities", ())) or ()
    )
    queue_id = str(
        getattr(queue, "context_identifier", getattr(queue, "identifier", f"{cycle_id}:opportunities"))
    )
    events.append(
        CanonicalAlertEvent(
            identifier=f"alert:{queue_id}",
            aggregate_identifier=cycle_id,
            occurred_at=occurred_at,
            topic=AlertTopic.OPPORTUNITY,
            priority=AlertPriority.STANDARD,
            subject="Capital opportunity set reviewed",
            body=(
                f"The CIO compared {len(ranked)} qualified opportunity"
                f"{'ies' if len(ranked) != 1 else 'y'} against cash, current holdings, "
                "and every other available use of capital."
            ),
        )
    )

    for decision in tuple(getattr(result, "decisions", ()) or ()):
        decision_id = _required_text(getattr(decision, "identifier", None), "decision identifier")
        action = _value(getattr(decision, "action", "unknown"))
        candidate = str(getattr(decision, "candidate_identifier", "portfolio"))
        urgent = action in {"exit", "reduce", "insufficient_evidence"}
        events.append(
            CanonicalAlertEvent(
                identifier=f"alert:{decision_id}",
                aggregate_identifier=cycle_id,
                occurred_at=occurred_at,
                topic=AlertTopic.CIO_DECISION,
                priority=AlertPriority.URGENT if urgent else AlertPriority.STANDARD,
                subject=f"CIO decision: {action.replace('_', ' ')}",
                body=(
                    f"Candidate: {candidate}\nAction: {action}\n"
                    f"Rationale: {getattr(decision, 'explanation', getattr(decision, 'plain_english_explanation', getattr(decision, 'rationale', 'See the canonical CIO journal.')))}"
                ),
                evidence_identifiers=tuple(
                    getattr(decision, "evidence_identifiers", getattr(decision, "supporting_evidence", ())) or ()
                ),
            )
        )

    construction = getattr(result, "construction", None)
    if construction is not None:
        construction_id = _required_text(
            getattr(construction, "request_identifier", getattr(construction, "identifier", None)),
            "construction identifier",
        )
        status = _value(getattr(construction, "status", "unknown"))
        events.append(
            CanonicalAlertEvent(
                identifier=f"alert:{construction_id}",
                aggregate_identifier=cycle_id,
                occurred_at=occurred_at,
                topic=AlertTopic.IMPLEMENTATION,
                priority=AlertPriority.URGENT if status == "blocked" else AlertPriority.STANDARD,
                subject=f"Portfolio implementation: {status.replace('_', ' ')}",
                body=(
                    f"Construction status: {status}. "
                    f"Proposed trades: {len(tuple(getattr(construction, 'trades', ()) or ()))}. "
                    "Implementation remains portfolio-level and non-broker unless separately authorized."
                ),
            )
        )

    for thesis in tuple(getattr(result, "theses", ()) or ()):
        thesis_id = _required_text(getattr(thesis, "identifier", None), "thesis identifier")
        events.append(
            CanonicalAlertEvent(
                identifier=f"alert:{thesis_id}",
                aggregate_identifier=cycle_id,
                occurred_at=occurred_at,
                topic=AlertTopic.THESIS,
                priority=AlertPriority.STANDARD,
                subject="Living thesis established or updated",
                body=(
                    f"Thesis {thesis_id} is now monitored against explicit assumptions, "
                    "invalidation conditions, replacement opportunities, and review timing."
                ),
                evidence_identifiers=tuple(getattr(thesis, "evidence_identifiers", ()) or ()),
            )
        )

    snapshots = tuple(getattr(result, "evaluation_snapshots", ()) or ())
    if snapshots:
        identifiers = tuple(str(getattr(item, "identifier")) for item in snapshots)
        events.append(
            CanonicalAlertEvent(
                identifier=f"alert:{cycle_id}:evidence",
                aggregate_identifier=cycle_id,
                occurred_at=occurred_at,
                topic=AlertTopic.EVIDENCE,
                priority=AlertPriority.STANDARD,
                subject="Decision-time evidence frozen",
                body=(
                    f"{len(snapshots)} decision evidence snapshot"
                    f"{'s were' if len(snapshots) != 1 else ' was'} frozen for later point-in-time evaluation."
                ),
                evidence_identifiers=identifiers,
            )
        )

    briefing = getattr(result, "briefing", None)
    briefing_id = _required_text(getattr(briefing, "identifier", None), "briefing identifier")
    events.append(
        CanonicalAlertEvent(
            identifier=f"alert:{briefing_id}",
            aggregate_identifier=cycle_id,
            occurred_at=occurred_at,
            topic=AlertTopic.DAILY_BRIEFING,
            priority=AlertPriority.STANDARD,
            subject="Daily Capital Intelligence briefing",
            body=(
                f"What changed: {getattr(briefing, 'what_changed', 'See the canonical briefing.')}\n"
                f"Portfolio decision: {getattr(briefing, 'portfolio_decision', 'See the canonical briefing.')}"
            ),
        )
    )
    return tuple(events)


__all__ = [
    "CanonicalAlertEvent",
    "CanonicalAlertPlanner",
    "CanonicalAlertPlanningResult",
    "events_from_canonical_cycle",
]
