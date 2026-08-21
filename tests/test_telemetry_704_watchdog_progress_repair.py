"""Regressions for telemetry #704 lane-local watchdog liveness repair."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from operations import bounded_comprehensive_discovery_spool as bounded
from operations import comprehensive_discovery_input_spool as spool
from operations import lane_local_comprehensive_discovery_coordinator as coordinator
from operations import lane_local_comprehensive_discovery_spool as lane_local
from operations import lane_local_watchdog_progress as progress
from operations import release_prequalification_parent_watchdog as watchdog


def _touch(path: Path, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    timestamp = when.timestamp()
    os.utime(path, (timestamp, timestamp))


def _install_request(monkeypatch, tmp_path, *, boundary: datetime, lane_names=("us_equity", "crypto")):
    request_path = tmp_path / "epoch" / "request-id" / "request.json"
    _touch(request_path, boundary + timedelta(seconds=1))
    monkeypatch.setattr(spool, "_root", lambda _values: tmp_path)
    monkeypatch.setattr(spool, "_release", lambda _values: "release-sha")
    monkeypatch.setattr(
        progress,
        "_load_request_identity",
        lambda _path, _spool: {
            "request_id": "request-id",
            "release": "release-sha",
            "decision_epoch": "2026-08-21T21:17:53+00:00",
        },
    )
    monkeypatch.setattr(
        lane_local,
        "_candidate_lanes",
        lambda: tuple(SimpleNamespace(value=name) for name in lane_names),
    )
    monkeypatch.setattr(
        lane_local,
        "_lane_state_name",
        lambda prefix, index: f"{prefix}-{index:03d}",
    )
    return request_path


def _state_loader(states):
    def load_stage(_request_path, name):
        if name not in states:
            raise RuntimeError("missing")
        return states[name]

    return load_stage


def test_lane_local_publication_completion_advances_without_legacy_aggregate(
    monkeypatch, tmp_path
) -> None:
    boundary = datetime.now(timezone.utc)
    request_path = _install_request(monkeypatch, tmp_path, boundary=boundary)
    states = {
        "catalog-lane-000": {
            "request_id": "request-id",
            "asset_class": "us_equity",
            "record_count": 2100,
            "peak_rss_bytes": 111,
        },
        "publication-lane-000": {
            "request_id": "request-id",
            "asset_class": "us_equity",
            "record_count": 2050,
            "dynamic": True,
            "scheduled": True,
            "peak_rss_bytes": 222,
            "bounded_provider_publication": True,
        },
    }
    _touch(request_path.parent / "catalog-lane-000.json", boundary + timedelta(seconds=2))
    _touch(request_path.parent / "publication-lane-000.json", boundary + timedelta(seconds=3))
    monkeypatch.setattr(bounded, "_load_stage_state", _state_loader(states))

    observed = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)

    assert observed is not None
    assert observed.component == "bounded-publication-lane-complete:us_equity"
    assert observed.metrics["completed_publication_lanes"] == 1
    assert observed.metrics["peak_rss_bytes"] == 222
    assert observed.metrics["bounded_provider_publication"] == 1
    assert observed.progress_token == (
        "request-id:publication-lane:000:us_equity:complete"
    )


def test_touching_same_lane_state_does_not_fabricate_liveness_and_next_lane_advances(
    monkeypatch, tmp_path
) -> None:
    boundary = datetime.now(timezone.utc)
    request_path = _install_request(monkeypatch, tmp_path, boundary=boundary)
    states = {
        "catalog-lane-000": {
            "request_id": "request-id",
            "asset_class": "us_equity",
            "record_count": 10,
        },
        "publication-lane-000": {
            "request_id": "request-id",
            "asset_class": "us_equity",
            "record_count": 10,
            "dynamic": True,
            "scheduled": True,
        },
    }
    _touch(request_path.parent / "catalog-lane-000.json", boundary + timedelta(seconds=2))
    publication_path = request_path.parent / "publication-lane-000.json"
    _touch(publication_path, boundary + timedelta(seconds=3))
    monkeypatch.setattr(bounded, "_load_stage_state", _state_loader(states))

    first = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)
    assert first is not None

    _touch(publication_path, boundary + timedelta(minutes=5))
    touched = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)
    assert touched is not None
    assert touched.updated_at > first.updated_at
    assert touched.marker == first.marker

    states["catalog-lane-001"] = {
        "request_id": "request-id",
        "asset_class": "crypto",
        "record_count": 7,
        "peak_rss_bytes": 333,
    }
    _touch(request_path.parent / "catalog-lane-001.json", boundary + timedelta(minutes=6))
    advanced = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)

    assert advanced is not None
    assert advanced.component == "bounded-catalog-lane-complete:crypto"
    assert advanced.marker != first.marker
    assert advanced.metrics["completed_catalog_lanes"] == 2
    assert advanced.metrics["peak_rss_bytes"] == 333


def test_sparse_screening_order_advances_from_active_to_completion(
    monkeypatch, tmp_path
) -> None:
    boundary = datetime.now(timezone.utc)
    lane_names = ("us_etf", "us_equity", "crypto")
    request_path = _install_request(
        monkeypatch,
        tmp_path,
        boundary=boundary,
        lane_names=lane_names,
    )
    states = {}
    for index, asset_class in enumerate(lane_names):
        states[f"catalog-lane-{index:03d}"] = {
            "request_id": "request-id",
            "asset_class": asset_class,
            "record_count": 10 + index,
        }
        states[f"publication-lane-{index:03d}"] = {
            "request_id": "request-id",
            "asset_class": asset_class,
            "record_count": 10 + index,
            "dynamic": True,
            "scheduled": index > 0,
            "bounded_provider_publication": True,
        }
        _touch(
            request_path.parent / f"catalog-lane-{index:03d}.json",
            boundary + timedelta(seconds=2 + index * 2),
        )
        _touch(
            request_path.parent / f"publication-lane-{index:03d}.json",
            boundary + timedelta(seconds=3 + index * 2),
        )

    states["lane-stage-001"] = {
        "request_id": "request-id",
        "node": {"asset_class": "us_equity", "decision_eligible_count": 81},
        "peak_rss_bytes": 444,
    }
    _touch(request_path.parent / "lane-stage-001.json", boundary + timedelta(seconds=9))
    monkeypatch.setattr(bounded, "_load_stage_state", _state_loader(states))

    active_payload = {
        "schema_version": progress._SCHEMA_VERSION,
        "request_id": "request-id",
        "release": "release-sha",
        "action": "screening-lane",
        "asset_class": "crypto",
        "index": 2,
        "updated_at": (boundary + timedelta(seconds=10)).isoformat(),
        **progress._authority_fields(),
    }
    (request_path.parent / progress._ACTIVE_STATE_NAME).write_text(
        json.dumps(active_payload), encoding="utf-8"
    )

    active = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)
    assert active is not None
    assert active.component == "bounded-spool-screening-lane:crypto"
    assert active.metrics["scheduled_lanes"] == 2
    assert active.metrics["completed_screening_lanes"] == 1

    states["lane-stage-002"] = {
        "request_id": "request-id",
        "node": {"asset_class": "crypto", "decision_eligible_count": 23},
        "peak_rss_bytes": 555,
    }
    _touch(request_path.parent / "lane-stage-002.json", boundary + timedelta(seconds=11))
    completed = progress.lane_local_bounded_discovery_progress({}, boundary=boundary)

    assert completed is not None
    assert completed.component == "bounded-screening-lane-complete:crypto"
    assert completed.marker != active.marker
    assert completed.metrics["completed_screening_lanes"] == 2
    assert completed.metrics["decision_eligible_records"] == 23
    assert completed.metrics["peak_rss_bytes"] == 555


def test_active_marker_writer_is_non_authoritative(monkeypatch, tmp_path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        progress,
        "_load_request_identity",
        lambda _path, _spool: {"request_id": "request-id", "release": "release-sha"},
    )
    monkeypatch.setattr(spool, "_release", lambda _values: "release-sha")
    captured = {}
    monkeypatch.setattr(
        spool,
        "_atomic_json",
        lambda path, body: captured.update(path=path, body=body),
    )

    progress.record_active_lane_watchdog_progress(
        request_path,
        {},
        action="publication-lane",
        asset_class="crypto",
        index=4,
    )

    body = captured["body"]
    assert body["request_id"] == "request-id"
    assert body["action"] == "publication-lane"
    assert body["asset_class"] == "crypto"
    assert body["decision_authority"] is False
    assert body["candidate_authority"] is False
    assert body["execution_authority"] is False
    assert body["paper_only"] is True
    assert body["real_money_authorized"] is False


def test_overlay_uses_lane_local_progress_and_preserves_legacy_fallback(monkeypatch) -> None:
    boundary = datetime.now(timezone.utc)
    legacy = watchdog.PrequalificationProgress(
        "discovery_preparation",
        "legacy",
        boundary,
        "running",
        180.0,
        {},
        progress_token="legacy-token",
    )
    lane = watchdog.PrequalificationProgress(
        "discovery_preparation",
        "lane-local",
        boundary + timedelta(seconds=1),
        "running",
        180.0,
        {},
        progress_token="lane-token",
    )
    monkeypatch.setattr(
        watchdog,
        "_bounded_discovery_progress",
        lambda _values, *, boundary: legacy,
    )
    monkeypatch.setattr(
        progress,
        "lane_local_bounded_discovery_progress",
        lambda _values, *, boundary: lane,
    )

    progress.install_lane_local_watchdog_progress()
    assert watchdog._bounded_discovery_progress({}, boundary=boundary) is lane

    monkeypatch.setattr(
        progress,
        "lane_local_bounded_discovery_progress",
        lambda _values, *, boundary: None,
    )
    assert watchdog._bounded_discovery_progress({}, boundary=boundary) is legacy


def test_coordinator_records_active_marker_before_launch(monkeypatch, tmp_path) -> None:
    events = []
    monkeypatch.setattr(coordinator, "_record_active_lane_stage", lambda action, asset: events.append(("diagnostic", action, asset)))
    monkeypatch.setattr(
        progress,
        "record_active_lane_watchdog_progress",
        lambda path, values, *, action, asset_class, index: events.append(
            ("watchdog", action, asset_class, index)
        ),
    )
    monkeypatch.setattr(
        coordinator._worker,
        "run_stage",
        lambda action, path, values, *, asset_class, index: events.append(
            ("worker", action, asset_class, index)
        ),
    )

    coordinator._run_stage(
        "catalog-lane",
        tmp_path / "request.json",
        {},
        asset_class="us_equity",
        index=0,
    )

    assert [event[0] for event in events] == ["diagnostic", "watchdog", "worker"]


def test_render_workspace_installs_lane_projection_before_parent_watchdog() -> None:
    source = Path("run_render_service_workspace.py").read_text(encoding="utf-8")
    assert source.index("install_lane_local_watchdog_progress()") < source.index(
        "install_release_prequalification_parent_watchdog(memory_safe)"
    )
