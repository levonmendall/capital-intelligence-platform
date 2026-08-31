from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from operations import comprehensive_discovery_structural_prewarm as overlap
from operations import epoch_scoped_provider_acquisition as acquisition


def _as_of() -> datetime:
    return datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def test_unresolved_provider_lane_replays_inside_original_budget(monkeypatch, tmp_path) -> None:
    clock = SimpleNamespace(now=100.0)
    observed_caps: list[float] = []
    original_ceiling = acquisition._MAX_FANOUT_SECONDS

    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        # 42 governed spare seconds leave the same 10-second replay window after the
        # separate 30-second operational handoff + 2-second cleanup reserve.
        lambda decision_epoch, values: 42.0,
    )

    def fake_fanout(request_path, *, values, decision_epoch):
        observed_caps.append(float(acquisition._MAX_FANOUT_SECONDS))
        assert Path(request_path) == tmp_path / "request.json"
        assert decision_epoch == _as_of()
        if len(observed_caps) == 1:
            clock.now += 4.0
            return {
                "attempted": True,
                "scheduled_lanes": 5,
                "completed": 4,
                "failed": 1,
                "provider_skipped_lanes": 0,
            }
        clock.now += 2.0
        return {
            "attempted": True,
            "scheduled_lanes": 5,
            "completed": 5,
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    result = overlap._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_as_of(),
    )

    assert observed_caps == [10.0, 6.0]
    assert acquisition._MAX_FANOUT_SECONDS == original_ceiling
    assert result["completed"] == 5
    assert result["failed"] == 0
    assert result["provider_replay_attempted"] is True
    assert result["provider_replay_count"] == 1
    assert result["provider_replay_initial_unresolved"] == 1
    assert result["provider_replay_final_unresolved"] == 0
    assert result["provider_replay_initial_budget_seconds"] == 10.0
    assert result["provider_replay_remaining_budget_seconds"] == 4.0
    assert result["provider_prewarm_governed_budget_seconds"] == 42.0
    assert result["provider_prewarm_handoff_margin_seconds"] == 30.0
    assert result["provider_prewarm_cleanup_reserve_seconds"] == 2.0


def test_structural_skip_is_treated_as_unresolved_and_replayed(monkeypatch, tmp_path) -> None:
    clock = SimpleNamespace(now=50.0)
    calls = 0

    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda decision_epoch, values: 40.0,
    )

    def fake_fanout(request_path, *, values, decision_epoch):
        nonlocal calls
        calls += 1
        if calls == 1:
            clock.now += 1.0
            return {
                "attempted": True,
                "scheduled_lanes": 5,
                "completed": 4,
                "failed": 0,
                "provider_skipped_lanes": 1,
            }
        return {
            "attempted": True,
            "scheduled_lanes": 5,
            "completed": 5,
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    result = overlap._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_as_of(),
    )

    assert calls == 2
    assert result["provider_replay_attempted"] is True
    assert result["provider_replay_final_unresolved"] == 0


def test_replay_does_not_extend_exhausted_original_window(monkeypatch, tmp_path) -> None:
    clock = SimpleNamespace(now=200.0)
    calls = 0
    expected = {
        "attempted": True,
        "scheduled_lanes": 5,
        "completed": 4,
        "failed": 1,
        "provider_skipped_lanes": 0,
    }

    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda decision_epoch, values: 39.0,
    )

    def fake_fanout(request_path, *, values, decision_epoch):
        nonlocal calls
        calls += 1
        clock.now += 7.0
        return dict(expected)

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    result = overlap._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_as_of(),
    )

    assert calls == 1
    assert result == expected


def test_no_replay_preserves_existing_fanout_return_shape(monkeypatch, tmp_path) -> None:
    expected = {"attempted": True, "completed": 5, "failed": 0}

    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda decision_epoch, values: 0.0,
    )
    monkeypatch.setattr(
        acquisition,
        "run_provider_acquisition_fanout",
        lambda *args, **kwargs: dict(expected),
    )

    result = overlap._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_as_of(),
    )

    assert result == expected


def test_provider_ceiling_is_restored_when_fanout_raises(monkeypatch, tmp_path) -> None:
    original_ceiling = acquisition._MAX_FANOUT_SECONDS

    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda decision_epoch, values: 3.0,
    )
    monkeypatch.setattr(
        acquisition,
        "run_provider_acquisition_fanout",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider child failed")),
    )

    with pytest.raises(RuntimeError, match="provider child failed"):
        overlap._run_epoch_provider_fanout_with_bounded_replay(
            tmp_path / "request.json",
            values={"RENDER": "true"},
            decision_epoch=_as_of(),
        )

    assert acquisition._MAX_FANOUT_SECONDS == original_ceiling


def test_governed_provider_limits_remain_unchanged() -> None:
    assert overlap._PROVIDER_REPLAY_LIMIT == 1
    assert overlap._OPERATIONAL_HANDOFF_MARGIN_SECONDS == 30.0
    assert overlap._COMPLETION_CLEANUP_RESERVE_SECONDS == 2.0
    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
    assert acquisition._DEFAULT_WORKERS == 6
    assert acquisition._MAX_WORKERS == 6
