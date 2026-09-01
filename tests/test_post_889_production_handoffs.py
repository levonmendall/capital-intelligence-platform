from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_prewarm as prewarm
from operations import epoch_scoped_provider_acquisition as acquisition


def _epoch() -> datetime:
    return datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)


def test_initial_provider_pass_prioritizes_missing_publications_without_dropping_lanes(
    monkeypatch, tmp_path
) -> None:
    epoch = _epoch()
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    lanes = (
        (0, CandidateAssetClass.US_EQUITY),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
        (5, CandidateAssetClass.FX),
    )
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)

    reusable = {
        CandidateAssetClass.US_EQUITY.value,
        CandidateAssetClass.FX.value,
    }

    def validate(_request_path, *, values, asset_class_value, index):
        del index
        assert values[acquisition._REUSE_ONLY_ENV] == "true"
        if asset_class_value not in reusable:
            raise RuntimeError("exact-request publication is unavailable")
        return {
            "scheduled": True,
            "asset_class": asset_class_value,
            "publication_ready": True,
            "reused": True,
        }

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", validate)

    ordered = prewarm._provider_initial_lane_items(
        request,
        acquisition=acquisition,
        decision_epoch=epoch,
    )

    assert ordered[0] == lanes[1]
    assert set(ordered) == set(lanes)
    assert len(ordered) == len(lanes)


def test_bounded_fanout_uses_missing_first_on_first_pass(monkeypatch, tmp_path) -> None:
    epoch = _epoch()
    request = tmp_path / "request.json"
    request.write_text("{}", encoding="utf-8")
    lanes = (
        (0, CandidateAssetClass.US_EQUITY),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
        (5, CandidateAssetClass.FX),
    )
    original_schedule = lambda _epoch: lanes
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", original_schedule)
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *_args, **_kwargs: 120.0)

    reusable = {
        CandidateAssetClass.US_EQUITY.value,
        CandidateAssetClass.FX.value,
    }

    def validate(_request_path, *, values, asset_class_value, index):
        del index
        assert values[acquisition._REUSE_ONLY_ENV] == "true"
        if asset_class_value not in reusable:
            raise RuntimeError("exact-request publication is unavailable")
        return {
            "scheduled": True,
            "asset_class": asset_class_value,
            "publication_ready": True,
            "reused": True,
        }

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", validate)

    observed = []

    def fake_fanout(_request, *, values, decision_epoch):
        del values
        scheduled = tuple(acquisition._scheduled_lane_items(decision_epoch))
        observed.append(scheduled)
        # Model successful canonical promotion for the missing lane. The scheduling
        # regression now keys off reuse validation rather than mere file presence.
        if lanes[1] in scheduled:
            reusable.add(CandidateAssetClass.INTERNATIONAL_EQUITY.value)
        return {
            "attempted": True,
            "scheduled_lanes": len(scheduled),
            "completed": len(scheduled),
            "failed": 0,
            "provider_skipped_lanes": 0,
        }

    monkeypatch.setattr(acquisition, "run_provider_acquisition_fanout", fake_fanout)

    result = prewarm._run_epoch_provider_fanout_with_bounded_replay(
        request,
        values={"RENDER": "true"},
        decision_epoch=epoch,
    )

    assert observed == [
        (
            lanes[1],
            lanes[0],
            lanes[2],
        )
    ]
    assert result["provider_initial_missing_priority_count"] == 1
    assert result["provider_initial_missing_prioritized"] is True
    assert acquisition._scheduled_lane_items is original_schedule


def test_pre_us_equity_cache_release_is_bounded_and_advisory(monkeypatch) -> None:
    observed = {}

    def fake_run(*args, **kwargs):
        observed["args"] = args
        observed["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(prewarm.subprocess, "run", fake_run)

    prewarm._release_pre_us_equity_file_cache(
        {
            "RENDER": "true",
            "CAPITAL_INTELLIGENCE_DATA_DIR": "/tmp/cio-data",
        }
    )

    assert observed["kwargs"]["timeout"] == prewarm._PRE_US_EQUITY_CACHE_RECLAMATION_TIMEOUT_SECONDS
    assert observed["kwargs"]["check"] is False
    assert observed["kwargs"]["start_new_session"] is False
    command = observed["args"][0]
    assert command[:2] == (prewarm.sys.executable, "-c")
    assert "release_pre_comprehensive_completed_stage_file_cache" in command[2]


def test_start_prewarm_reclaims_before_sidecar_launch(monkeypatch, tmp_path) -> None:
    epoch = _epoch()
    events = []
    values = {
        "RENDER": "true",
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        prewarm._REFERENCE_MANIFEST_ID_ENV: "manifest-id",
        prewarm._REFERENCE_MANIFEST_PATH_ENV: str(tmp_path / "manifest.json"),
    }

    monkeypatch.setattr(
        prewarm,
        "_release_pre_us_equity_file_cache",
        lambda _values: events.append("reclaim"),
    )
    monkeypatch.setattr(acquisition, "_fanout_budget_seconds", lambda *_args, **_kwargs: 120.0)

    class FakeProcess:
        def poll(self):
            return 0

    def fake_popen(*args, **kwargs):
        events.append("popen")
        return FakeProcess()

    monkeypatch.setattr(prewarm.subprocess, "Popen", fake_popen)

    handle = prewarm.start_render_structural_prewarm(
        evidence_as_of=epoch,
        values=values,
    )

    assert events == ["reclaim", "popen"]
    assert handle.process is not None
