from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cio import CandidateAssetClass
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
