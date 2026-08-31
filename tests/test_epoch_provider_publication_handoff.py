from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import comprehensive_discovery_structural_prewarm as overlap
from operations import epoch_scoped_provider_acquisition as acquisition


def _as_of() -> datetime:
    return datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def test_render_handoff_fails_before_serial_builder_on_missing_publication(
    monkeypatch, tmp_path, capsys
) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    serial_calls: list[Path] = []
    validation_calls: list[tuple[int, str, bool]] = []

    def serial_builder(request_path, *, values=None):
        serial_calls.append(Path(request_path))
        return object()

    lanes = (
        (0, CandidateAssetClass.US_EQUITY),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
    )
    monkeypatch.setattr(spawn_safe, "build_spool", serial_builder)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)
    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda path, values: ({"decision_epoch": _as_of().isoformat()}, object()),
    )
    monkeypatch.setattr(
        legacy,
        "_parse_timestamp",
        lambda value, *, field_name: _as_of(),
    )
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("handoff validation must not consume provider fanout budget")
        ),
    )
    monkeypatch.setattr(
        acquisition,
        "run_provider_acquisition_fanout",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("handoff validation must not start provider fanout")
        ),
    )

    def validate_lane(
        request_path,
        *,
        values,
        asset_class_value,
        index,
    ):
        validation_calls.append(
            (
                int(index),
                str(asset_class_value),
                acquisition._reuse_only(values),
            )
        )
        if asset_class_value == CandidateAssetClass.INTERNATIONAL_EQUITY.value:
            raise RuntimeError(
                "international_equity exact-epoch provider publication is unavailable; "
                "reuse-only comprehensive fanout refuses provider reacquisition"
            )
        return {"publication_ready": True, "reused": True}

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", validate_lane)
    acquisition.install_epoch_scoped_provider_acquisition()

    with pytest.raises(RuntimeError, match="international_equity exact-epoch"):
        spawn_safe.build_spool(
            tmp_path / "request.json",
            values={"RENDER": "true"},
        )

    assert validation_calls == [
        (0, CandidateAssetClass.US_EQUITY.value, True),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY.value, True),
    ]
    assert serial_calls == []
    emitted = capsys.readouterr().out
    assert "epoch_scoped_provider_publication_handoff_failed" in emitted
    assert "international_equity exact-epoch provider publication is unavailable" in emitted
    assert '"advisory_only": false' in emitted


def test_render_handoff_calls_serial_builder_once_after_complete_validation(
    monkeypatch, tmp_path
) -> None:
    from operations import bounded_comprehensive_discovery_spool as bounded
    from operations import comprehensive_discovery_input_spool as legacy
    from operations import spawn_safe_authoritative_acquisition as spawn_safe

    serial_calls: list[Path] = []
    validation_calls: list[str] = []
    lanes = (
        (0, CandidateAssetClass.US_EQUITY),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
    )

    def serial_builder(request_path, *, values=None):
        serial_calls.append(Path(request_path))
        return "serialized"

    monkeypatch.setattr(spawn_safe, "build_spool", serial_builder)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)
    monkeypatch.setattr(
        bounded,
        "_validate_request",
        lambda path, values: ({"decision_epoch": _as_of().isoformat()}, object()),
    )
    monkeypatch.setattr(
        legacy,
        "_parse_timestamp",
        lambda value, *, field_name: _as_of(),
    )

    def validate_lane(
        request_path,
        *,
        values,
        asset_class_value,
        index,
    ):
        assert acquisition._reuse_only(values) is True
        validation_calls.append(str(asset_class_value))
        return {"publication_ready": True, "reused": True}

    monkeypatch.setattr(acquisition, "prepare_lane_provider_publication", validate_lane)
    acquisition.install_epoch_scoped_provider_acquisition()

    result = spawn_safe.build_spool(
        tmp_path / "request.json",
        values={"RENDER": "true"},
    )

    assert result == "serialized"
    assert validation_calls == [
        CandidateAssetClass.US_EQUITY.value,
        CandidateAssetClass.INTERNATIONAL_EQUITY.value,
    ]
    assert serial_calls == [tmp_path / "request.json"]


def test_bounded_replay_prioritizes_only_missing_publication_lane(
    monkeypatch, tmp_path
) -> None:
    clock = SimpleNamespace(now=100.0)
    observed_schedules: list[tuple[tuple[int, CandidateAssetClass], ...]] = []
    observed_caps: list[float] = []
    lanes = (
        (0, CandidateAssetClass.US_EQUITY),
        (4, CandidateAssetClass.INTERNATIONAL_EQUITY),
    )
    original_ceiling = acquisition._MAX_FANOUT_SECONDS

    monkeypatch.setattr(overlap.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(acquisition, "_scheduled_lane_items", lambda _epoch: lanes)
    monkeypatch.setattr(
        acquisition,
        "_fanout_budget_seconds",
        lambda decision_epoch, values: 42.0,
    )

    def fake_fanout(request_path, *, values, decision_epoch):
        observed_caps.append(float(acquisition._MAX_FANOUT_SECONDS))
        observed_schedules.append(tuple(acquisition._scheduled_lane_items(decision_epoch)))
        if len(observed_schedules) == 1:
            (tmp_path / "provider-preselection-000-us_equity.json").write_text(
                "{}", encoding="utf-8"
            )
            clock.now += 4.0
            return {
                "attempted": True,
                "scheduled_lanes": 2,
                "completed": 1,
                "failed": 1,
                "provider_skipped_lanes": 0,
            }
        clock.now += 2.0
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

    assert observed_schedules == [
        lanes,
        ((4, CandidateAssetClass.INTERNATIONAL_EQUITY),),
    ]
    assert observed_caps == [10.0, 6.0]
    assert acquisition._MAX_FANOUT_SECONDS == original_ceiling
    assert result["provider_replay_attempted"] is True
    assert result["provider_replay_initial_unresolved"] == 1
    assert result["provider_replay_final_unresolved"] == 0
    assert result["provider_prewarm_handoff_margin_seconds"] == 30.0
    assert result["provider_prewarm_cleanup_reserve_seconds"] == 2.0
