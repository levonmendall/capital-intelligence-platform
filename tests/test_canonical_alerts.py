"""Canonical event alert contracts and production integration."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from delivery import (
    AlertChannel,
    AlertDeliveryService,
    AlertPriority,
    AlertTopic,
    CanonicalAlertEvent,
    CanonicalAlertPlanner,
    DeliveryPreference,
    DeliveryStatus,
    SQLiteAlertStore,
    ScheduledCanonicalCIOWorker,
    events_from_canonical_cycle,
)

NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)


def _account():
    return SimpleNamespace(
        user_id="user:canonical",
        email="canonical@example.com",
        is_active=True,
    )


def _result():
    return SimpleNamespace(
        identifier="canonical-cycle:test",
        as_of=NOW,
        opportunity_queue=SimpleNamespace(
            identifier="opportunity-queue:test",
            ranked_opportunities=(SimpleNamespace(),),
        ),
        decisions=(
            SimpleNamespace(
                identifier="decision:test",
                candidate_identifier="candidate:test",
                action=SimpleNamespace(value="buy"),
                plain_english_explanation="The candidate exceeds every available use of capital after cost.",
                evidence_identifiers=("evidence:decision",),
            ),
        ),
        construction=SimpleNamespace(
            identifier="construction:test",
            status=SimpleNamespace(value="feasible"),
            trades=(SimpleNamespace(),),
        ),
        theses=(
            SimpleNamespace(
                identifier="thesis:test",
                evidence_identifiers=("evidence:thesis",),
            ),
        ),
        evaluation_snapshots=(SimpleNamespace(identifier="evidence-snapshot:test"),),
        briefing=SimpleNamespace(
            identifier="daily-cio:test",
            what_changed="A superior opportunity qualified.",
            portfolio_decision="Buy within the approved portfolio constraints.",
        ),
    )


def test_cycle_translates_only_to_canonical_event_topics() -> None:
    events = events_from_canonical_cycle(_result())

    assert {event.topic for event in events} == {
        AlertTopic.OPPORTUNITY,
        AlertTopic.CIO_DECISION,
        AlertTopic.IMPLEMENTATION,
        AlertTopic.THESIS,
        AlertTopic.EVIDENCE,
        AlertTopic.DAILY_BRIEFING,
    }
    assert all("score" not in event.body.casefold() for event in events)
    assert all("conviction" not in event.body.casefold() for event in events)


def test_planner_uses_event_topic_not_score_or_threshold() -> None:
    event = CanonicalAlertEvent(
        identifier="alert:decision:test",
        aggregate_identifier="canonical-cycle:test",
        occurred_at=NOW,
        topic=AlertTopic.CIO_DECISION,
        priority=AlertPriority.URGENT,
        subject="CIO decision: exit",
        body="The CIO issued an exit after thesis invalidation.",
        evidence_identifiers=("evidence:test",),
    )
    preference = DeliveryPreference(
        user_id="user:canonical",
        topics=(AlertTopic.CIO_DECISION,),
        channels=(AlertChannel.IN_APP,),
    )

    result = CanonicalAlertPlanner().plan(event, preference)

    assert result.message is not None
    assert result.message.event_identifier == event.identifier
    assert result.message.topics == (AlertTopic.CIO_DECISION,)
    assert "evidence:test" in result.message.body


def test_disabled_canonical_topic_is_recorded_as_suppressed(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    store.save_preference(
        DeliveryPreference(
            user_id="user:canonical",
            topics=(AlertTopic.THESIS,),
        ),
        now=NOW,
    )
    service = AlertDeliveryService(store, clock=lambda: NOW)
    event = CanonicalAlertEvent(
        identifier="alert:decision:test",
        aggregate_identifier="canonical-cycle:test",
        occurred_at=NOW,
        topic=AlertTopic.CIO_DECISION,
        priority=AlertPriority.STANDARD,
        subject="CIO decision",
        body="No portfolio change.",
    )

    queued = service.queue_event_for_accounts(event, (_account(),))

    assert queued[0].status is DeliveryStatus.SUPPRESSED
    assert store.pending(now=NOW) == ()


def test_scheduler_queues_cycle_events_idempotently(tmp_path) -> None:
    class Executor:
        calls = 0

        def run(self, *, as_of):
            self.calls += 1
            return _result()

    class IdentityStore:
        def list_users(self):
            return (_account(),)

    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    executor = Executor()
    worker = ScheduledCanonicalCIOWorker(
        executor,
        store,
        delivery_service=service,
        identity_store=IdentityStore(),
        schedule_timezone="UTC",
        schedule_hour=11,
        clock=lambda: NOW,
    )

    first = worker.run_due(now=NOW)
    second = worker.run_due(now=NOW)

    assert first.status == "completed"
    assert second.status == "completed"
    assert executor.calls == 1
    deliveries = store.list_deliveries("user:canonical", include_suppressed=True)
    assert len(deliveries) == 6
    assert {delivery.topics[0] for delivery in deliveries} == {
        AlertTopic.OPPORTUNITY,
        AlertTopic.CIO_DECISION,
        AlertTopic.IMPLEMENTATION,
        AlertTopic.THESIS,
        AlertTopic.EVIDENCE,
        AlertTopic.DAILY_BRIEFING,
    }


def test_active_alert_surfaces_exclude_score_and_conviction_contracts() -> None:
    from pathlib import Path

    scheduler = Path("run_scheduler.py").read_text(encoding="utf-8")
    api_route = Path("api/routes/alerts.py").read_text(encoding="utf-8")
    api_schema = Path("api/schemas.py").read_text(encoding="utf-8")
    app = Path("secure_app.py").read_text(encoding="utf-8")

    assert "SelectiveAlertPlanner" not in scheduler
    assert "AlertSnapshot" not in scheduler
    assert "minimum_conviction_change" not in api_route
    alert_schema = api_schema.split("class AlertPreferenceRequest", 1)[1].split(
        "class AlertPreferenceResponse", 1
    )[0]
    assert "conviction" not in alert_schema.casefold()
    assert "minimum material confidence change" not in app.casefold()
    assert "canonical_topics" in app
