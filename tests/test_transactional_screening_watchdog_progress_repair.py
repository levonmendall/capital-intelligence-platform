"""Regressions for the transactional comprehensive-lane false-stall repair."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import bounded_comprehensive_discovery_spool as bounded
from operations import cached_transactional_comprehensive_discovery_lane as cached
from operations import comprehensive_discovery_input_spool as spool
from operations import continuous_evidence_plane
from operations import lane_local_comprehensive_discovery_spool as lane_local
from operations import lane_local_watchdog_progress as lane_progress
from operations import release_prequalification_parent_watchdog as watchdog
from operations import transactional_screening_watchdog_progress as repair


def _touch(path: Path, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def test_cached_transaction_marks_publication_then_screening(monkeypatch, tmp_path) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        lane_progress,
        "record_active_lane_watchdog_progress",
        lambda path, values, *, action, asset_class, index: events.append(action),
    )
    monkeypatch.setattr(
        cached,
        "_ORIGINAL_MERGE_CERTIFIED_LANE",
        lambda core, raw, *, asset_class, timestamp: tuple(raw),
    )
    monkeypatch.setattr(cached._structural, "publish_structural_catalog", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cached,
        "_ORIGINAL_BUILD_DEEP_LANE",
        lambda *args, **kwargs: events.append("deep-work") or ({}, False, 0),
    )
    cached._ACTIVE_REQUEST_PATH = tmp_path / "request.json"
    cached._ACTIVE_VALUES = {}
    cached._ACTIVE_ASSET_CLASS = "fixed_income"
    cached._ACTIVE_INDEX = 3
    cached._ACTIVE_POLICY_VERSION = "policy"

    merged = cached._merge_certified_lane(
        SimpleNamespace(),
        (SimpleNamespace(symbol="A"),),
        asset_class=CandidateAssetClass.FIXED_INCOME,
        timestamp=datetime.now(timezone.utc),
    )
    assert len(merged) == 1
    cached._build_deep_lane()

    assert events == ["publication-lane", "screening-lane", "deep-work"]


def test_watchdog_phase_marker_failure_is_fail_soft(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        lane_progress,
        "record_active_lane_watchdog_progress",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("advisory write failed")),
    )
    cached._ACTIVE_REQUEST_PATH = tmp_path / "request.json"
    cached._ACTIVE_VALUES = {}
    cached._ACTIVE_ASSET_CLASS = "fixed_income"
    cached._ACTIVE_INDEX = 3

    cached._record_watchdog_phase("screening-lane")


def _install_screening_fixture(monkeypatch, tmp_path, *, publication_scheduled: bool = True):
    boundary = datetime.now(timezone.utc)
    request_path = tmp_path / "epoch" / "request-id" / "request.json"
    _touch(request_path, boundary + timedelta(seconds=1))
    monkeypatch.setattr(spool, "_root", lambda _values: tmp_path)
    monkeypatch.setattr(spool, "_release", lambda _values: "release-sha")
    monkeypatch.setattr(
        lane_local,
        "_candidate_lanes",
        lambda: (
            SimpleNamespace(value="us_equity"),
            SimpleNamespace(value="fixed_income"),
            SimpleNamespace(value="crypto"),
        ),
    )
    monkeypatch.setattr(
        lane_local,
        "_lane_state_name",
        lambda prefix, index: f"{prefix}-{index:03d}",
    )
    monkeypatch.setattr(
        lane_progress,
        "_load_request_identity",
        lambda _path, _spool: {
            "request_id": "request-id",
            "release": "release-sha",
        },
    )
    active_at = boundary + timedelta(seconds=5)
    monkeypatch.setattr(
        lane_progress,
        "_load_active_state",
        lambda *args, **kwargs: ("screening-lane", "fixed_income", 1, active_at),
    )
    publication = {
        "request_id": "request-id",
        "asset_class": "fixed_income",
        "record_count": 44,
        "scheduled": publication_scheduled,
        "peak_rss_bytes": 321,
        "bounded_provider_publication": True,
    }
    monkeypatch.setattr(
        lane_progress,
        "_load_stage",
        lambda _bounded, _path, name: publication if name == "publication-lane-001" else None,
    )
    return boundary, active_at


def test_parent_projects_inflight_screening_before_later_publications_complete(
    monkeypatch, tmp_path
) -> None:
    boundary, active_at = _install_screening_fixture(monkeypatch, tmp_path)

    observed = repair._screening_progress({}, boundary=boundary)

    assert observed is not None
    assert observed.component == "bounded-spool-screening-lane:fixed_income"
    assert observed.updated_at == active_at
    assert observed.metrics["active_lane_index"] == 1
    assert observed.metrics["catalog_records"] == 44
    assert observed.metrics["bounded_provider_publication"] == 1
    assert observed.progress_token == (
        "request-id:active:screening-lane:001:fixed_income"
    )


def test_parent_rejects_screening_without_durable_scheduled_publication(
    monkeypatch, tmp_path
) -> None:
    boundary, _active_at = _install_screening_fixture(
        monkeypatch, tmp_path, publication_scheduled=False
    )

    assert repair._screening_progress({}, boundary=boundary) is None


def test_overlay_does_not_overwrite_newer_terminal_or_manifest_progress(
    monkeypatch, tmp_path
) -> None:
    boundary, active_at = _install_screening_fixture(monkeypatch, tmp_path)
    newer = watchdog.PrequalificationProgress(
        "discovery_preparation",
        "bounded-discovery-manifest-complete",
        active_at + timedelta(seconds=1),
        "running",
        180.0,
        {},
        progress_token="manifest-complete",
    )
    monkeypatch.setattr(
        watchdog,
        "_bounded_discovery_progress",
        lambda _values, *, boundary: newer,
    )

    repair.install_transactional_screening_watchdog_progress()

    assert watchdog._bounded_discovery_progress({}, boundary=boundary) is newer


def test_render_installs_screening_projection_before_parent_watchdog() -> None:
    source = Path("run_render_service_workspace.py").read_text(encoding="utf-8")
    assert source.index("install_lane_local_watchdog_progress()") < source.index(
        "install_transactional_screening_watchdog_progress()"
    ) < source.index("install_release_prequalification_parent_watchdog(memory_safe)")


def test_repair_does_not_extend_watchdog_or_evidence_freshness_contracts() -> None:
    assert watchdog._DEFAULT_DAG_TIMEOUT_SECONDS == 540.0
    assert watchdog._DAG_MARGIN_SECONDS == 120.0
    assert continuous_evidence_plane._DEFAULT_MAX_AGE_SECONDS == 900.0
