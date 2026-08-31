from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import comprehensive_discovery_structural_prewarm as overlap
from operations import epoch_scoped_provider_acquisition as acquisition


def _as_of() -> datetime:
    return datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _publication_path(directory: Path, index: int, value: str) -> Path:
    return directory / f"provider-preselection-{index:03d}-{value}.json"


def test_replay_prioritizes_absent_exact_request_publication(monkeypatch, tmp_path) -> None:
    early = SimpleNamespace(value="us_equity")
    late = SimpleNamespace(value="international_equity")
    lanes = ((0, early), (4, late))
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)

    _publication_path(tmp_path, 0, early.value).write_text("{}", encoding="utf-8")

    selected = overlap._provider_replay_lane_items(
        tmp_path / "request.json",
        acquisition=acquisition,
        decision_epoch=_as_of(),
    )

    assert selected == ((4, late),)


def test_replay_falls_back_to_full_schedule_when_paths_all_exist(monkeypatch, tmp_path) -> None:
    early = SimpleNamespace(value="us_equity")
    late = SimpleNamespace(value="international_equity")
    lanes = ((0, early), (4, late))
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)

    for index, lane in lanes:
        _publication_path(tmp_path, index, lane.value).write_text("{}", encoding="utf-8")

    selected = overlap._provider_replay_lane_items(
        tmp_path / "request.json",
        acquisition=acquisition,
        decision_epoch=_as_of(),
    )

    assert selected == lanes


def test_bounded_replay_applies_target_schedule_and_restores_it(monkeypatch, tmp_path) -> None:
    clock = SimpleNamespace(now=100.0)
    early = SimpleNamespace(value="us_equity")
    late = SimpleNamespace(value="international_equity")
    lanes = ((0, early), (4, late))
    schedules_seen = []
    calls = 0

    original_schedule = lambda _epoch: lanes
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", original_schedule)
    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *_args, **_kwargs: 42.0)
    monkeypatch.setattr(
        overlap,
        "_provider_replay_lane_items",
        lambda *_args, **_kwargs: ((4, late),),
    )

    def fake_fanout(request_path, *, values, decision_epoch):
        nonlocal calls
        calls += 1
        schedules_seen.append(tuple(acquisition._scheduled_lane_items(decision_epoch)))
        clock.now += 1.0
        if calls == 1:
            return {
                "attempted": True,
                "scheduled_lanes": 2,
                "completed": 1,
                "failed": 1,
                "provider_skipped_lanes": 0,
            }
        return {
            "attempted": True,
            "scheduled_lanes": 1,
            "completed": 1,
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    result = overlap._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_as_of(),
    )

    assert schedules_seen == [lanes, ((4, late),)]
    assert acquisition._scheduled_lane_items is original_schedule
    assert result["provider_replay_targeted_lanes"] == 1
    assert result["provider_replay_final_unresolved"] == 0
    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
