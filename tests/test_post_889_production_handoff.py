from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_prewarm as prewarm
import run_stage_isolated_evidence_stage as stage_runner


def _epoch() -> datetime:
    return datetime(2026, 9, 1, 0, 24, 38, tzinfo=timezone.utc)


def test_provider_first_pass_reserves_suffix_for_targeted_replay(monkeypatch, tmp_path):
    from operations import epoch_scoped_provider_acquisition as acquisition

    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(prewarm.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda _epoch, _values: 300.0,
    )

    full_schedule = (
        (0, CandidateAssetClass.US_EQUITY),
        (1, CandidateAssetClass.US_ETF),
        (2, CandidateAssetClass.CASH_EQUIVALENT),
        (3, CandidateAssetClass.FIXED_INCOME),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
    )
    monkeypatch.setattr(
        acquisition,
        "_scheduled_lane_items",
        lambda _epoch: full_schedule,
    )
    monkeypatch.setattr(
        prewarm,
        "_provider_replay_lane_items",
        lambda *args, **kwargs: ((4, CandidateAssetClass.INTERNATIONAL_EQUITY),),
    )

    observed_caps: list[float] = []
    observed_schedules: list[tuple[tuple[int, CandidateAssetClass], ...]] = []

    def fake_fanout(request_path, *, values, decision_epoch):
        del request_path, values
        observed_caps.append(float(acquisition._MAX_FANOUT_SECONDS))
        observed_schedules.append(tuple(acquisition._scheduled_lane_items(decision_epoch)))
        if len(observed_caps) == 1:
            clock.now += observed_caps[-1]
            return {
                "attempted": True,
                "scheduled_lanes": 5,
                "completed": 4,
                "failed": 1,
                "provider_skipped_lanes": 0,
            }
        clock.now += 5.0
        return {
            "attempted": True,
            "scheduled_lanes": 1,
            "completed": 1,
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    report = prewarm._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request.json",
        values={"RENDER": "true"},
        decision_epoch=_epoch(),
    )

    assert report["provider_replay_initial_budget_seconds"] == 268.0
    assert report["provider_replay_reserved_seconds"] == 45.0
    assert observed_caps == [223.0, 45.0]
    assert observed_schedules[0] == full_schedule
    assert observed_schedules[1] == (
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
    )
    assert report["provider_replay_attempted"] is True
    assert report["provider_replay_targeted_lanes"] == 1
    assert report["provider_replay_final_unresolved"] == 0
    assert clock.now <= 100.0 + 268.0
    assert acquisition._MAX_FANOUT_SECONDS == 300.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0


def test_provider_replay_reserve_scales_down_for_short_legal_window():
    assert prewarm._provider_replay_reserve_seconds(0.0) == 0.0
    assert prewarm._provider_replay_reserve_seconds(40.0) == 10.0
    assert prewarm._provider_replay_reserve_seconds(268.0) == 45.0


def test_post_public_live_cache_reclamation_is_advisory(monkeypatch):
    from operations import pre_comprehensive_cache_reclamation as cache

    observed = []

    def fake_release(values):
        observed.append(dict(values))
        return {
            "status": "completed",
            "released_file_count": 9,
            "released_bytes": 12345,
            "raw_current_reclaimed_kib": 16012,
            "inactive_file_reclaimed_kib": 8192,
        }

    monkeypatch.setattr(
        cache,
        "release_pre_comprehensive_completed_stage_file_cache",
        fake_release,
    )

    report = stage_runner._post_public_live_cache_reclamation(
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/data"}
    )

    assert observed == [
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/data"}
    ]
    assert report["status"] == "completed"
    assert report["raw_current_reclaimed_kib"] == 16012
    assert report["advisory_only"] is True
    assert report["evidence_certified"] is False


def test_post_public_live_cache_reclamation_failure_does_not_advance_authority(
    monkeypatch,
):
    from operations import pre_comprehensive_cache_reclamation as cache

    def fail_release(_values):
        raise OSError("cache advice unavailable")

    monkeypatch.setattr(
        cache,
        "release_pre_comprehensive_completed_stage_file_cache",
        fail_release,
    )

    report = stage_runner._post_public_live_cache_reclamation({"RENDER": "true"})

    assert report == {
        "status": "unavailable",
        "advisory_only": True,
        "evidence_certified": False,
    }
