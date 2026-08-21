"""Regressions for integrity-checked bounded-discovery parent liveness."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from operations import bounded_comprehensive_discovery_spool as bounded
from operations import comprehensive_discovery_input_spool as spool
from operations import release_prequalification_parent_watchdog as watchdog


def _raise_missing(*_args, **_kwargs):
    raise RuntimeError("missing")


def _install_request(monkeypatch, tmp_path, *, request_mtime: datetime):
    request_path = tmp_path / "epoch" / "request-id" / "request.json"
    request_path.parent.mkdir(parents=True)
    request_path.write_text("{}\n", encoding="utf-8")
    timestamp = request_mtime.timestamp()
    os.utime(request_path, (timestamp, timestamp))
    monkeypatch.setattr(spool, "_root", lambda _values: tmp_path)
    monkeypatch.setattr(spool, "_release", lambda _values: "release-sha")
    monkeypatch.setattr(
        spool,
        "load_request",
        lambda _path: (
            {"request_id": "request-id", "release": "release-sha"},
            object(),
        ),
    )
    monkeypatch.setattr(spool, "load_manifest_for_request", _raise_missing)
    return request_path


def _touch(path, value: datetime) -> None:
    path.write_text("{}\n", encoding="utf-8")
    timestamp = value.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_bounded_lane_completion_advances_parent_liveness(monkeypatch, tmp_path) -> None:
    boundary = datetime.now(timezone.utc)
    request_path = _install_request(
        monkeypatch,
        tmp_path,
        request_mtime=boundary + timedelta(seconds=1),
    )
    catalog_path = request_path.parent / "catalog-stage.json"
    publication_path = request_path.parent / "publication-stage.json"
    lane_path = request_path.parent / "lane-stage-000.json"
    _touch(catalog_path, boundary + timedelta(seconds=2))
    _touch(publication_path, boundary + timedelta(seconds=3))
    _touch(lane_path, boundary + timedelta(seconds=4))

    states = {
        "catalog-stage": {
            "request_id": "request-id",
            "catalog_record_count": 2400,
        },
        "publication-stage": {
            "request_id": "request-id",
            "merged_catalog_record_count": 2200,
            "lane_catalog_shards": [
                {"index": 0, "asset_class": "us_equity"},
                {"index": 1, "asset_class": "crypto"},
            ],
        },
        "lane-stage-000": {
            "request_id": "request-id",
            "node": {
                "asset_class": "us_equity",
                "decision_eligible_count": 180,
            },
        },
    }

    def load_stage(_request_path, name):
        if name not in states:
            raise RuntimeError("missing")
        return states[name]

    monkeypatch.setattr(bounded, "_load_stage_state", load_stage)

    progress = watchdog._bounded_discovery_progress({}, boundary=boundary)

    assert progress is not None
    assert progress.phase == "discovery_preparation"
    assert progress.component == "bounded-lane-complete:us_equity"
    assert progress.metrics["scheduled_lanes"] == 2
    assert progress.metrics["completed_lanes"] == 1
    assert progress.metrics["decision_eligible_records"] == 180
    assert progress.progress_token == "request-id:30-lane-000"


def test_touching_same_bounded_stage_does_not_create_new_progress_marker(
    monkeypatch, tmp_path
) -> None:
    boundary = datetime.now(timezone.utc)
    request_path = _install_request(
        monkeypatch,
        tmp_path,
        request_mtime=boundary + timedelta(seconds=1),
    )
    catalog_path = request_path.parent / "catalog-stage.json"
    _touch(catalog_path, boundary + timedelta(seconds=2))
    monkeypatch.setattr(
        bounded,
        "_load_stage_state",
        lambda _path, name: (
            {"request_id": "request-id", "catalog_record_count": 10}
            if name == "catalog-stage"
            else _raise_missing()
        ),
    )

    first = watchdog._bounded_discovery_progress({}, boundary=boundary)
    assert first is not None

    _touch(catalog_path, boundary + timedelta(minutes=5))
    second = watchdog._bounded_discovery_progress({}, boundary=boundary)

    assert second is not None
    assert second.updated_at > first.updated_at
    assert second.marker == first.marker
    assert second.progress_token == "request-id:10-catalog"


def test_next_bounded_lane_changes_logical_progress_marker(monkeypatch, tmp_path) -> None:
    boundary = datetime.now(timezone.utc)
    request_path = _install_request(
        monkeypatch,
        tmp_path,
        request_mtime=boundary + timedelta(seconds=1),
    )
    for offset, name in enumerate(
        ("catalog-stage.json", "publication-stage.json", "lane-stage-000.json"),
        start=2,
    ):
        _touch(request_path.parent / name, boundary + timedelta(seconds=offset))

    states = {
        "catalog-stage": {"request_id": "request-id", "catalog_record_count": 10},
        "publication-stage": {
            "request_id": "request-id",
            "merged_catalog_record_count": 10,
            "lane_catalog_shards": [
                {"index": 0, "asset_class": "us_equity"},
                {"index": 1, "asset_class": "crypto"},
            ],
        },
        "lane-stage-000": {
            "request_id": "request-id",
            "node": {"asset_class": "us_equity", "decision_eligible_count": 5},
        },
    }

    def load_stage(_request_path, name):
        if name not in states:
            raise RuntimeError("missing")
        return states[name]

    monkeypatch.setattr(bounded, "_load_stage_state", load_stage)
    first = watchdog._bounded_discovery_progress({}, boundary=boundary)
    assert first is not None

    states["lane-stage-001"] = {
        "request_id": "request-id",
        "node": {"asset_class": "crypto", "decision_eligible_count": 4},
    }
    _touch(request_path.parent / "lane-stage-001.json", boundary + timedelta(seconds=8))
    second = watchdog._bounded_discovery_progress({}, boundary=boundary)

    assert second is not None
    assert second.component == "bounded-lane-complete:crypto"
    assert second.metrics["completed_lanes"] == 2
    assert second.marker != first.marker
    assert second.progress_token == "request-id:30-lane-001"


def test_stale_bounded_request_cannot_masquerade_as_current_attempt(
    monkeypatch, tmp_path
) -> None:
    boundary = datetime.now(timezone.utc)
    _install_request(
        monkeypatch,
        tmp_path,
        request_mtime=boundary - timedelta(minutes=10),
    )
    monkeypatch.setattr(bounded, "_load_stage_state", _raise_missing)

    assert watchdog._bounded_discovery_progress({}, boundary=boundary) is None
