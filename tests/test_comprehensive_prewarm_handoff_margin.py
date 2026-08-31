from __future__ import annotations

from datetime import datetime, timezone

from operations import comprehensive_discovery_structural_prewarm as prewarm
from operations import epoch_scoped_provider_acquisition as acquisition


def test_early_provider_owner_surrenders_operational_handoff_margin(monkeypatch, tmp_path) -> None:
    observed_caps: list[float] = []
    original = acquisition._MAX_FANOUT_SECONDS
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *args, **kwargs: 100.0)

    def fake_fanout(*args, **kwargs):
        del args, kwargs
        observed_caps.append(float(acquisition._MAX_FANOUT_SECONDS))
        return {
            "attempted": True,
            "scheduled_lanes": 1,
            "completed": 1,
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)
    report = prewarm._run_epoch_provider_fanout_with_bounded_replay(
        tmp_path / "request",
        values={},
        decision_epoch=datetime(2026, 8, 31, tzinfo=timezone.utc),
    )

    assert observed_caps == [68.0]
    assert acquisition._MAX_FANOUT_SECONDS == original
    assert report["provider_prewarm_handoff_margin_seconds"] == 30.0
    assert report["provider_prewarm_cleanup_reserve_seconds"] == 2.0
    assert acquisition._DOWNSTREAM_RESERVE_SECONDS == 480.0
    assert original == 300.0
