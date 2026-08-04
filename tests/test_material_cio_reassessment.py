import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.config import ApiSettings
from operations.cio_reassessment import (
    AfterCloseOpportunityReviewer,
    MaterialCIOReassessmentEngine,
)


class _Client:
    def __init__(self, snapshots, *, market_open=True) -> None:
        self._snapshots = snapshots
        self._market_open = market_open

    def clock(self):
        return {"is_open": self._market_open}

    def snapshots(self, symbols):
        return {
            symbol: self._snapshots[symbol]
            for symbol in symbols
            if symbol in self._snapshots
        }


def _snapshot(price: float, previous: float):
    return {
        "latestTrade": {"p": price},
        "prevDailyBar": {"c": previous},
    }


def _active_universe(path) -> None:
    path.write_text(
        json.dumps(
            {
                "eligible_universe_publication_identifier": "eligible:test",
                "universe": {
                    "instruments": [
                        {"symbol": "VTI", "instrument_type": "fund"},
                        {"symbol": "MSFT", "instrument_type": "common_stock"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def _public_collection(tmp_path, *, completed_at, records):
    records_path = tmp_path / "public-records.json"
    state_path = tmp_path / "public-state.json"
    records_path.write_text(
        json.dumps({"records": records}),
        encoding="utf-8",
    )
    state_path.write_text(
        json.dumps(
            {
                "completed_at": completed_at.isoformat(),
                "record_count": len(records),
            }
        ),
        encoding="utf-8",
    )
    return SimpleNamespace(records_path=records_path, state_path=state_path)


def _material_record(identifier, available_at, *, channels, topic):
    return {
        "identifier": identifier,
        "topic": topic,
        "event_at": available_at.isoformat(),
        "published_at": available_at.isoformat(),
        "available_at": available_at.isoformat(),
        "knowledge_cutoff": available_at.isoformat(),
        "impact_channels": list(channels),
        "reliability": 0.90,
        "relevance": 0.85,
        "materiality": 0.80,
        "independence": 0.80,
        "provenance": {"quality_state": "live"},
    }


def test_material_scan_triggers_deduplicates_and_rebases(tmp_path) -> None:
    universe = tmp_path / "active-paper-universe.json"
    _active_universe(universe)
    snapshots = {
        "VTI": _snapshot(102.0, 100.0),
        "MSFT": _snapshot(106.0, 100.0),
    }
    engine = MaterialCIOReassessmentEngine(
        state_path=tmp_path / "state.json",
        timezone_name="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
        client_factory=lambda: _Client(snapshots),
        active_universe_path=universe,
        fallback_universe_path=tmp_path / "unused.json",
    )
    first_time = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)

    first = engine.scan_if_due(now=first_time)
    assert first.triggered
    assert any("benchmark VTI" in reason for reason in first.reasons)
    assert any("company MSFT" in reason for reason in first.reasons)

    not_due = engine.scan_if_due(now=first_time + timedelta(minutes=2))
    assert not_due.state == "not_due"

    duplicate = engine.scan_if_due(now=first_time + timedelta(minutes=6))
    assert duplicate.state == "deduplicated"

    engine.acknowledge_assessment(now=first_time + timedelta(minutes=7))
    snapshots["MSFT"] = _snapshot(110.0, 100.0)
    retrigger = engine.scan_if_due(now=first_time + timedelta(minutes=38))
    assert retrigger.triggered
    assert any("since the last full CIO assessment" in reason for reason in retrigger.reasons)


def test_material_scan_triggers_from_credit_currency_and_positioning_evidence(tmp_path) -> None:
    universe = tmp_path / "active-paper-universe.json"
    _active_universe(universe)
    snapshots = {
        "VTI": _snapshot(100.0, 100.0),
        "MSFT": _snapshot(100.0, 100.0),
    }
    engine = MaterialCIOReassessmentEngine(
        state_path=tmp_path / "state.json",
        timezone_name="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
        client_factory=lambda: _Client(snapshots),
        active_universe_path=universe,
        fallback_universe_path=tmp_path / "unused.json",
    )
    first_time = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)
    first_record = _material_record(
        "record:credit-dollar",
        first_time - timedelta(minutes=1),
        channels=("credit", "currency", "positioning"),
        topic="Dollar funding pressure and credit positioning changed materially",
    )
    collection = _public_collection(
        tmp_path,
        completed_at=first_time,
        records=(first_record,),
    )

    first = engine.scan_if_due(
        now=first_time,
        public_collection=collection,
    )
    assert first.triggered is True
    assert any(
        "credit, currency, positioning" in reason
        for reason in first.reasons
    )
    assert first.trigger_key.startswith("material-evidence-")

    duplicate = engine.scan_if_due(
        now=first_time + timedelta(minutes=6),
        public_collection=collection,
    )
    assert duplicate.state == "deduplicated"

    engine.acknowledge_assessment(now=first_time + timedelta(minutes=7))
    same = engine.scan_if_due(
        now=first_time + timedelta(minutes=38),
        public_collection=collection,
    )
    assert same.state == "no_material_change"

    second_time = first_time + timedelta(minutes=100)
    second_record = _material_record(
        "record:inflation-rates",
        second_time - timedelta(minutes=1),
        channels=("inflation", "discount_rate", "volatility"),
        topic="Inflation expectations and rate volatility repriced",
    )
    collection = _public_collection(
        tmp_path,
        completed_at=second_time,
        records=(first_record, second_record),
    )
    second = engine.scan_if_due(
        now=second_time,
        public_collection=collection,
    )
    assert second.triggered is True
    assert any(
        "inflation, discount_rate, volatility" in reason
        for reason in second.reasons
    )


def test_weak_or_unverified_public_records_do_not_trigger(tmp_path) -> None:
    universe = tmp_path / "active-paper-universe.json"
    _active_universe(universe)
    snapshots = {
        "VTI": _snapshot(100.0, 100.0),
        "MSFT": _snapshot(100.0, 100.0),
    }
    engine = MaterialCIOReassessmentEngine(
        state_path=tmp_path / "state.json",
        timezone_name="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
        client_factory=lambda: _Client(snapshots),
        active_universe_path=universe,
        fallback_universe_path=tmp_path / "unused.json",
    )
    now = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)
    record = _material_record(
        "record:weak",
        now - timedelta(minutes=1),
        channels=("credit",),
        topic="Unverified credit rumor",
    )
    record["provenance"]["quality_state"] = "unverified"
    collection = _public_collection(
        tmp_path,
        completed_at=now,
        records=(record,),
    )

    result = engine.scan_if_due(now=now, public_collection=collection)

    assert result.state == "no_material_change"
    assert result.triggered is False


def test_material_scan_is_held_when_market_is_closed_without_new_evidence(tmp_path) -> None:
    universe = tmp_path / "active-paper-universe.json"
    _active_universe(universe)
    engine = MaterialCIOReassessmentEngine(
        state_path=tmp_path / "state.json",
        timezone_name="America/Los_Angeles",
        schedule_times=("07:00", "10:00", "12:45"),
        client_factory=lambda: _Client({}, market_open=False),
        active_universe_path=universe,
        fallback_universe_path=tmp_path / "unused.json",
    )

    result = engine.scan_if_due(
        now=datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc)
    )
    assert result.state == "market_closed"
    assert not result.triggered


def test_after_close_review_is_research_only_and_idempotent(tmp_path) -> None:
    reviewer = AfterCloseOpportunityReviewer(
        state_path=tmp_path / "after-close.json",
        outcome_store_path=tmp_path / "outcomes.db",
        timezone_name="America/Los_Angeles",
        review_time="13:15",
        universe_path=tmp_path / "unused.json",
    )
    now = datetime(2026, 7, 30, 20, 20, tzinfo=timezone.utc)

    first = reviewer.run_if_due(now=now)
    second = reviewer.run_if_due(now=now + timedelta(minutes=10))

    assert first.state == "completed"
    assert first.resolved_outcomes == 0
    assert first.execution_authority is False
    assert second.state == "reused"


def test_api_settings_parse_multi_cycle_configuration() -> None:
    settings = ApiSettings.from_env(
        {
            "CAPITAL_INTELLIGENCE_SCHEDULER_TIMEZONE": "America/Los_Angeles",
            "CAPITAL_INTELLIGENCE_SCHEDULER_TIMES": "07:00,10:00,12:45",
            "CAPITAL_INTELLIGENCE_SCHEDULER_SCAN_SECONDS": "300",
            "CAPITAL_INTELLIGENCE_SCHEDULER_EVENT_COOLDOWN_MINUTES": "30",
            "CAPITAL_INTELLIGENCE_SCHEDULER_AFTER_CLOSE_TIME": "13:15",
        }
    )

    assert settings.scheduler_times == ("07:00", "10:00", "12:45")
    assert settings.scheduler_hour == 7
    assert settings.scheduler_scan_seconds == 300
    assert settings.scheduler_event_cooldown_minutes == 30
