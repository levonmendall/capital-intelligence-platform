import json
from datetime import datetime, timedelta, timezone

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


def test_material_scan_is_held_when_market_is_closed(tmp_path) -> None:
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
