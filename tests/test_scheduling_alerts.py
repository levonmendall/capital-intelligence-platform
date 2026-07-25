"""Contract tests for scheduled cycles and selective alert delivery."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from delivery import (
    AlertChannel,
    AlertDeliveryService,
    AlertSnapshot,
    AlertTopic,
    CycleStatus,
    DeliveryPreference,
    DeliveryStatus,
    SQLiteAlertStore,
    ScheduledDailyIntelligenceWorker,
    SelectiveAlertPlanner,
)
from delivery.service import CanonicalCycleResult


NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def _snapshot(
    *,
    identifier: str = "daily:1",
    should_alert: bool = False,
    alert_level: str = "silent",
    categories: tuple[str, ...] = (),
    conviction_change: int | None = None,
) -> AlertSnapshot:
    return AlertSnapshot(
        snapshot_identifier=identifier,
        as_of=NOW,
        status="current",
        score=82,
        score_delta=4,
        environment="Constructive",
        risk="Moderate",
        committee="6–0 Favor Risk Assets",
        portfolio_impact="Increase equity exposure modestly.",
        change_summary="Liquidity improved while inflation remained contained.",
        should_alert=should_alert,
        alert_level=alert_level,
        change_categories=categories,
        conviction_change_points=conviction_change,
    )


def test_default_preferences_are_quiet_and_in_app_only(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")

    preference = store.get_preference("user:1", fallback_email="user@example.com")

    assert preference.channels == (AlertChannel.IN_APP,)
    assert AlertTopic.DAILY_SUMMARY not in preference.topics
    assert preference.email_address == "user@example.com"


def test_unchanged_cycle_records_suppression_instead_of_notification(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )

    queued = service.queue_for_accounts(_snapshot(), (account,))

    assert len(queued) == 1
    assert queued[0].status is DeliveryStatus.SUPPRESSED
    assert store.pending(now=NOW) == ()
    assert store.list_deliveries("user:1") == ()
    assert len(store.list_deliveries("user:1", include_suppressed=True)) == 1


def test_material_alert_uses_enabled_topics_and_deduplicates(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    store.save_preference(
        DeliveryPreference(
            user_id="user:1",
            channels=(AlertChannel.IN_APP, AlertChannel.EMAIL),
            topics=(
                AlertTopic.URGENT_RISK,
                AlertTopic.ENVIRONMENT_TRANSITION,
            ),
            email_address="user@example.com",
        ),
        now=NOW,
    )
    sent: list[str] = []

    def email_dispatcher(delivery) -> None:
        sent.append(delivery.delivery_id)

    service = AlertDeliveryService(
        store,
        dispatchers={AlertChannel.EMAIL: email_dispatcher},
        clock=lambda: NOW,
    )
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )
    snapshot = _snapshot(
        should_alert=True,
        alert_level="urgent",
        categories=("regime",),
    )

    first = service.queue_for_accounts(snapshot, (account,))
    second = service.queue_for_accounts(snapshot, (account,))
    dispatched = service.dispatch_pending()

    assert {item.delivery_id for item in first} == {
        item.delivery_id for item in second
    }
    assert len(first) == 2
    assert all(item.status is DeliveryStatus.SENT for item in dispatched)
    assert len(sent) == 1
    assert store.unread_count("user:1") == 1


def test_email_dispatcher_receives_persisted_recipient(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    store.save_preference(
        DeliveryPreference(
            user_id="user:1",
            channels=(AlertChannel.EMAIL,),
            topics=(AlertTopic.PORTFOLIO_REVIEW,),
            email_address="user@example.com",
        ),
        now=NOW,
    )
    recipients: list[str] = []

    def send(delivery) -> None:
        recipients.append(delivery.email_address)

    service = AlertDeliveryService(
        store,
        dispatchers={AlertChannel.EMAIL: send},
        clock=lambda: NOW,
    )
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )
    service.queue_for_accounts(
        _snapshot(should_alert=True, categories=("signal",)),
        (account,),
    )

    delivered = service.dispatch_pending()

    assert recipients == ["user@example.com"]
    assert delivered[0].status is DeliveryStatus.SENT


def test_email_failures_retry_then_dead_letter(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    store.save_preference(
        DeliveryPreference(
            user_id="user:1",
            channels=(AlertChannel.EMAIL,),
            topics=(AlertTopic.PORTFOLIO_REVIEW,),
            email_address="user@example.com",
        ),
        now=NOW,
    )

    def fail(_delivery) -> None:
        raise RuntimeError("SMTP unavailable")

    clock_values = iter(
        (
            NOW,
            NOW,
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=3),
        )
    )
    service = AlertDeliveryService(
        store,
        dispatchers={AlertChannel.EMAIL: fail},
        maximum_attempts=2,
        base_retry_delay=timedelta(minutes=1),
        clock=lambda: next(clock_values),
    )
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )
    service.queue_for_accounts(
        _snapshot(should_alert=True, categories=("signal",)),
        (account,),
    )

    first = service.dispatch_pending()
    second = service.dispatch_pending()

    assert first[0].status is DeliveryStatus.PENDING
    assert second[0].status is DeliveryStatus.FAILED
    assert second[0].attempts == 2
    assert store.attempt_count(second[0].delivery_id) == 2


def test_sent_in_app_alert_can_be_acknowledged_only_by_owner(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )
    queued = service.queue_for_accounts(
        _snapshot(should_alert=True, categories=("signal",)),
        (account,),
    )
    service.dispatch_pending()

    with pytest.raises(KeyError):
        store.acknowledge(queued[0].delivery_id, user_id="user:2", now=NOW)
    acknowledged = store.acknowledge(
        queued[0].delivery_id,
        user_id="user:1",
        now=NOW,
    )

    assert acknowledged.status is DeliveryStatus.ACKNOWLEDGED
    assert store.unread_count("user:1") == 0


def test_delivery_attempt_history_is_append_only(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )
    queued = service.queue_for_accounts(
        _snapshot(should_alert=True, categories=("signal",)),
        (account,),
    )
    service.dispatch_pending()

    with sqlite3.connect(store.path) as connection:
        attempt_id = connection.execute(
            "SELECT attempt_id FROM delivery_attempts WHERE delivery_id = ?",
            (queued[0].delivery_id,),
        ).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE delivery_attempts SET detail = 'changed' WHERE attempt_id = ?",
                (attempt_id,),
            )


class _FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, as_of: datetime) -> CanonicalCycleResult:
        self.calls += 1
        snapshot = AlertSnapshot(
            snapshot_identifier=f"daily:{as_of.date().isoformat()}",
            as_of=as_of,
            status="current",
            score=80 + self.calls,
            score_delta=None if self.calls == 1 else 3,
            environment="Constructive",
            risk="Moderate",
            committee="6–0 Favor Risk Assets",
            portfolio_impact="Review equity exposure.",
            change_summary=(
                "First scheduled baseline."
                if self.calls == 1
                else "The governed material-change policy requires review."
            ),
            should_alert=self.calls > 1,
            alert_level="notify" if self.calls > 1 else "silent",
            change_categories=("governance",) if self.calls > 1 else (),
        )
        return CanonicalCycleResult(snapshot, object(), object())


class _Identity:
    def list_users(self):
        return (
            SimpleNamespace(
                user_id="user:1",
                email="user@example.com",
                is_active=True,
            ),
        )


def test_worker_runs_once_per_market_date_and_retries_are_durable(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    worker = ScheduledDailyIntelligenceWorker(
        _FakeExecutor(),
        _Identity(),
        service,
        schedule_timezone="UTC",
        schedule_hour=8,
        clock=lambda: NOW,
    )

    first = worker.run_due(now=NOW)
    duplicate = worker.run_due(now=NOW + timedelta(hours=1))

    assert first.status == CycleStatus.COMPLETED.value
    assert duplicate.status == CycleStatus.COMPLETED.value
    assert first.snapshot_identifier == duplicate.snapshot_identifier
    assert len(store.list_deliveries("user:1", include_suppressed=True)) == 1


def test_worker_does_not_run_before_configured_hour(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    service = AlertDeliveryService(store, clock=lambda: NOW)
    worker = ScheduledDailyIntelligenceWorker(
        _FakeExecutor(),
        _Identity(),
        service,
        schedule_timezone="UTC",
        schedule_hour=13,
        clock=lambda: NOW,
    )

    result = worker.run_due(now=NOW)

    assert result.status == "not_due"
    assert store.get_cycle(result.cycle_key) is None


def test_standard_alert_waits_for_user_local_delivery_hour(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    store.save_preference(
        DeliveryPreference(
            user_id="user:1",
            timezone_name="UTC",
            delivery_hour=14,
            channels=(AlertChannel.IN_APP,),
            topics=(AlertTopic.PORTFOLIO_REVIEW,),
        ),
        now=NOW,
    )
    service = AlertDeliveryService(store, clock=lambda: NOW)
    account = SimpleNamespace(
        user_id="user:1",
        email="user@example.com",
        is_active=True,
    )

    queued = service.queue_for_accounts(
        _snapshot(should_alert=True, categories=("signal",)),
        (account,),
    )

    assert queued[0].next_attempt_at == datetime(
        2026, 7, 25, 14, tzinfo=timezone.utc
    )
    assert service.dispatch_pending() == ()
