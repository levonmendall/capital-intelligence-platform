"""Regressions for telemetry #709 comprehensive-discovery memory attribution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from operations import comprehensive_discovery_memory_attribution as attribution
from operations import lane_local_watchdog_progress
from operations import stage_isolated_evidence_pipeline
import run_bounded_continuous_evidence_plane as continuous
import run_bounded_manual_cio_diagnostic as memory_watchdog


def _progress(component: str, *, metrics=None):
    return SimpleNamespace(
        component=component,
        recorded_at=datetime(2026, 8, 21, 22, 35, tzinfo=timezone.utc),
        metrics={} if metrics is None else metrics,
    )


def _state(stage: str = "comprehensive_discovery"):
    started = datetime(2026, 8, 21, 22, 28, tzinfo=timezone.utc)
    return SimpleNamespace(
        current_stage=stage,
        next_stage=None,
        pipeline_id="pipeline-709",
        stage_started_at=started,
        evidence_as_of=started,
    )


def test_lane_local_memory_context_identifies_active_screening_lane(monkeypatch) -> None:
    observed = _progress(
        "bounded-spool-screening-lane:crypto",
        metrics={
            "scheduled_lanes": 5,
            "completed_screening_lanes": 3,
            "active_lane_index": 7,
            "ignored_metric": 999,
        },
    )
    monkeypatch.setattr(
        lane_local_watchdog_progress,
        "lane_local_bounded_discovery_progress",
        lambda _values, *, boundary: observed,
    )
    # This regression isolates the legacy lane-projection contract. Live cgroup/store
    # enrichment is covered separately by the terminal-attribution snapshot tests.
    monkeypatch.setattr(
        attribution,
        "capture_memory_attribution",
        lambda *args, **kwargs: {},
    )

    context = attribution.lane_local_memory_failure_context(
        {},
        boundary=datetime(2026, 8, 21, 22, 28, tzinfo=timezone.utc),
    )

    assert context is not None
    assert context["component"] == "bounded-spool-screening-lane:crypto"
    assert context["substage"] == "screening-lane"
    assert context["asset_class"] == "crypto"
    assert context["progress_kind"] == "active"
    assert context["active_lane_index"] == 7
    assert context["metrics"] == {
        "active_lane_index": 7,
        "completed_screening_lanes": 3,
        "scheduled_lanes": 5,
    }
    assert context["decision_authority"] is False
    assert context["candidate_authority"] is False
    assert context["execution_authority"] is False
    assert context["paper_only"] is True
    assert context["real_money_authorized"] is False


def test_lane_local_memory_context_labels_completed_progress_as_non_exact(monkeypatch) -> None:
    observed = _progress(
        "bounded-publication-lane-complete:future",
        metrics={
            "completed_publication_lanes": 10,
            "catalog_records": 845,
            "peak_rss_bytes": 700_000_000,
        },
    )
    monkeypatch.setattr(
        lane_local_watchdog_progress,
        "lane_local_bounded_discovery_progress",
        lambda _values, *, boundary: observed,
    )
    monkeypatch.setattr(
        attribution,
        "capture_memory_attribution",
        lambda *args, **kwargs: {},
    )

    context = attribution.lane_local_memory_failure_context(
        {},
        boundary=datetime(2026, 8, 21, 22, 28, tzinfo=timezone.utc),
    )

    assert context is not None
    assert context["substage"] == "publication-lane"
    assert context["asset_class"] == "future"
    assert context["progress_kind"] == "completed"
    assert context["active_lane_index"] is None


def test_resource_boundary_emits_exact_active_lane(monkeypatch, capsys) -> None:
    state = _state()
    monkeypatch.setattr(
        stage_isolated_evidence_pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: state,
    )
    monkeypatch.setattr(
        attribution,
        "lane_local_memory_failure_context",
        lambda _values, *, boundary: {
            "component": "bounded-spool-publication-lane:us_equity",
            "substage": "publication-lane",
            "asset_class": "us_equity",
            "progress_kind": "active",
            "active_lane_index": 0,
            "recorded_at": "2026-08-21T22:35:00+00:00",
            "metrics": {"active_lane_index": 0, "candidate_lanes": 13},
        },
    )
    monkeypatch.setattr(
        memory_watchdog,
        "_last_reclaimable_memory_report",
        {
            "trigger_reason": "working_set",
            "container_peak_working_set_kib": 1_442_000,
            "container_peak_memory_kib": 1_700_000,
            "container_peak_inactive_file_kib": 210_000,
            "container_peak_anon_kib": 1_380_000,
            "container_peak_file_kib": 250_000,
            "container_peak_kernel_kib": 70_000,
            "memory_accounting_source": "cgroup_v2_configured_ceiling",
        },
        raising=False,
    )

    continuous._memory_failure_context({})

    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["error_type"] == "ResourceBoundaryExceeded"
    assert payload["failure_stage"] == (
        "stage_isolated_evidence:comprehensive_discovery:publication-lane:us_equity"
    )
    assert payload["failure_progress_kind"] == "active"
    assert payload["failure_substage"] == "publication-lane"
    assert payload["failure_asset_class"] == "us_equity"
    assert payload["failure_lane_index"] == 0
    assert payload["lane_progress_metrics"]["candidate_lanes"] == 13
    assert payload["memory_trigger_reason"] == "working_set"
    assert payload["memory_working_set_peak_kib"] == 1_442_000
    assert "lane_asset_class=us_equity" in payload["error_detail"]
    assert "lane_substage=publication-lane" in payload["error_detail"]
    assert payload["decision_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_completed_lane_is_last_durable_progress_not_false_failure_source(
    monkeypatch, capsys
) -> None:
    state = _state()
    monkeypatch.setattr(
        stage_isolated_evidence_pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: state,
    )
    monkeypatch.setattr(
        attribution,
        "lane_local_memory_failure_context",
        lambda _values, *, boundary: {
            "component": "bounded-screening-lane-complete:future",
            "substage": "screening-lane",
            "asset_class": "future",
            "progress_kind": "completed",
            "active_lane_index": None,
            "recorded_at": "2026-08-21T22:35:00+00:00",
            "metrics": {"completed_screening_lanes": 4},
        },
    )
    monkeypatch.setattr(
        memory_watchdog,
        "_last_reclaimable_memory_report",
        {"trigger_reason": "raw_hard_ceiling"},
        raising=False,
    )

    continuous._memory_failure_context({})

    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["failure_stage"] == "stage_isolated_evidence:comprehensive_discovery"
    assert payload["failure_progress_kind"] == "completed"
    assert payload["last_durable_progress_component"] == (
        "bounded-screening-lane-complete:future"
    )
    assert "last_durable_component=bounded-screening-lane-complete:future" in payload[
        "error_detail"
    ]


def test_missing_lane_projection_preserves_coarse_fail_closed_memory_event(
    monkeypatch, capsys
) -> None:
    state = _state()
    monkeypatch.setattr(
        stage_isolated_evidence_pipeline,
        "load_stage_isolated_evidence_state",
        lambda _values: state,
    )
    monkeypatch.setattr(
        attribution,
        "lane_local_memory_failure_context",
        lambda _values, *, boundary: None,
    )
    monkeypatch.setattr(
        memory_watchdog,
        "_last_reclaimable_memory_report",
        {"trigger_reason": "working_set"},
        raising=False,
    )

    continuous._memory_failure_context({})

    payload = json.loads(capsys.readouterr().err.strip())
    assert payload["failure_stage"] == "stage_isolated_evidence:comprehensive_discovery"
    assert payload["error_type"] == "ResourceBoundaryExceeded"
    assert "failure_asset_class" not in payload
    assert payload["memory_trigger_reason"] == "working_set"
