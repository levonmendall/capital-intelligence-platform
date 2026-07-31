from __future__ import annotations

from datetime import datetime, timedelta, timezone

from delivery.models import CycleStatus
from delivery.store import SQLiteAlertStore


NOW = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def test_cycle_retry_cooldown_blocks_collection(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    key = "canonical-cio:test"
    assert store.begin_cycle(key, scheduled_for=NOW, now=NOW) is True
    record = store.fail_cycle(
        key,
        error="temporary provider outage",
        now=NOW,
        retry_delay=timedelta(minutes=15),
    )
    assert record.status is CycleStatus.FAILED
    assert store.cycle_attempt_due(key, now=NOW + timedelta(minutes=14)) is False
    assert store.cycle_attempt_due(key, now=NOW + timedelta(minutes=15)) is True


def test_latest_cycle_exposes_failure_detail(tmp_path) -> None:
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    key = "canonical-cio:test"
    store.begin_cycle(key, scheduled_for=NOW, now=NOW)
    store.fail_cycle(
        key,
        error="provider failed",
        now=NOW,
        retry_delay=timedelta(minutes=15),
    )
    latest = store.latest_cycle()
    assert latest is not None
    assert latest.cycle_key == key
    assert latest.error == "provider failed"


def test_render_declares_market_provider_secrets_and_required_journal() -> None:
    source = open("render.yaml", encoding="utf-8").read()
    assert "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN" in source
    assert "CAPITAL_INTELLIGENCE_DATABENTO_API_KEY" in source
    assert 'CAPITAL_INTELLIGENCE_REQUIRE_JOURNAL\n        value: "true"' in source


def test_sidebar_no_longer_claims_system_online_unconditionally() -> None:
    source = open("premium_ui.py", encoding="utf-8").read()
    assert "System online" not in source
    assert "operating_status.label" in source
