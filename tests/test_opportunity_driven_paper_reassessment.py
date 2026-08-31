from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations.cio_material_reassessment import MaterialCIOReassessmentEngine


def _engine(tmp_path):
    return MaterialCIOReassessmentEngine(
        state_path=tmp_path / "reassessment.json",
        timezone_name="America/Los_Angeles",
        schedule_times=("10:00",),
        scan_interval=timedelta(minutes=1),
        event_cooldown=timedelta(minutes=30),
        active_universe_path=tmp_path / "active-universe.json",
    )


def test_distinct_opportunity_is_not_blocked_by_recent_event(tmp_path):
    engine = _engine(tmp_path)
    state = {}
    now = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)

    first_trigger, first_claims = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("public-record:event-a",),
        timestamp=now,
        prefix="material",
    )
    second_trigger, second_claims = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("public-record:event-b",),
        timestamp=now + timedelta(seconds=5),
        prefix="material",
    )

    assert first_trigger is not None
    assert second_trigger is not None
    assert second_trigger != first_trigger
    assert first_claims == ("public-record:event-a",)
    assert second_claims == ("public-record:event-b",)


def test_same_opportunity_is_deduplicated_inside_its_own_window(tmp_path):
    engine = _engine(tmp_path)
    state = {}
    now = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)

    trigger, _ = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("market-move:ABC:prior-close:up",),
        timestamp=now,
        prefix="material",
    )
    duplicate, claims = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("market-move:ABC:prior-close:up",),
        timestamp=now + timedelta(minutes=2),
        prefix="material",
    )

    assert trigger is not None
    assert duplicate is None
    assert claims == ()


def test_new_member_of_existing_condition_triggers_without_replaying_old_member(tmp_path):
    engine = _engine(tmp_path)
    state = {}
    now = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)

    engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("opportunity:a",),
        timestamp=now,
        prefix="material",
    )
    trigger, claims = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("opportunity:a", "opportunity:b"),
        timestamp=now + timedelta(seconds=10),
        prefix="material",
    )

    assert trigger is not None
    assert claims == ("opportunity:b",)


def test_failed_trigger_releases_only_its_own_opportunity_claims(tmp_path):
    engine = _engine(tmp_path)
    state = {}
    now = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)

    first_trigger, _ = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("opportunity:a",),
        timestamp=now,
        prefix="material",
    )
    second_trigger, _ = engine._claim_distinct_opportunities(
        state,
        opportunity_keys=("opportunity:b",),
        timestamp=now + timedelta(seconds=5),
        prefix="material",
    )
    assert first_trigger is not None
    assert second_trigger is not None

    # Persist the same state shape used by the runtime before exercising release.
    from operations.cio_material_reassessment import save_json

    save_json(engine.state_path, state)
    engine.release_trigger(second_trigger)
    released_state = __import__(
        "operations.cio_material_reassessment",
        fromlist=["load_json"],
    ).load_json(engine.state_path)

    retry_second, _ = engine._claim_distinct_opportunities(
        released_state,
        opportunity_keys=("opportunity:b",),
        timestamp=now + timedelta(seconds=10),
        prefix="material",
    )
    still_deduped_first, _ = engine._claim_distinct_opportunities(
        released_state,
        opportunity_keys=("opportunity:a",),
        timestamp=now + timedelta(seconds=10),
        prefix="material",
    )

    assert retry_second is not None
    assert still_deduped_first is None


def test_default_scheduled_guard_does_not_suppress_event_review(tmp_path):
    engine = _engine(tmp_path)
    scheduled = datetime(2026, 8, 30, 17, 0, tzinfo=timezone.utc)

    assert engine._guarded(scheduled) is False
