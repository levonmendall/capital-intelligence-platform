"""Regressions for telemetry #712 resource-context transport."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from operations import release_evidence_prequalification as release_state
from operations import telemetry_712_failure_context_bridge as bridge


def _values(tmp_path) -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-712",
    }


def _memory_event(
    *,
    progress_kind: str = "active",
    failure_stage: str = (
        "stage_isolated_evidence:comprehensive_discovery:publication-lane:crypto"
    ),
    last_durable: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "event": "continuous_evidence_plane_failure_context",
        "error_type": "ResourceBoundaryExceeded",
        "failure_stage": failure_stage,
        "error_detail": (
            "stage_isolated_evidence_resource_boundary; stage=comprehensive_discovery; "
            "trigger_reason=working_set; working_set_peak_kib=1450000; "
            "raw_peak_kib=1710000"
        ),
        "failure_progress_kind": progress_kind,
        "failure_substage": "publication-lane",
        "failure_asset_class": "crypto",
        "failure_component": "bounded-spool-publication-lane:crypto",
        "failure_lane_index": 7 if progress_kind == "active" else None,
        "lane_progress_metrics": {
            "active_lane_index": 7,
            "candidate_lanes": 13,
            "completed_publication_lanes": 7,
            "secret_metric": 999,
        },
        "memory_trigger_reason": "working_set",
        "memory_process_peak_rss_kib": 930000,
        "memory_working_set_peak_kib": 1450000,
        "memory_raw_peak_kib": 1710000,
        "memory_inactive_file_peak_kib": 210000,
        "memory_anon_peak_kib": 1390000,
        "memory_file_peak_kib": 250000,
        "memory_kernel_peak_kib": 70000,
        "memory_working_set_boundary_kib": 1441792,
        "memory_raw_hard_boundary_kib": 1887436,
        "memory_accounting_source": "cgroup_v2_configured_ceiling",
        "memory_reclaim_attempted": True,
        "memory_reclaim_supported": False,
        "memory_reclaim_requested_kib": 108376,
        "memory_reclaim_raw_before_kib": 1963044,
        "memory_reclaim_raw_after_kib": 1963044,
        "memory_reclaim_working_set_before_kib": 646572,
        "memory_reclaim_working_set_after_kib": 646572,
        "memory_reclaim_delta_kib": 0,
        "memory_reclaim_reclaimed_kib": 0,
        "memory_reclaim_effective": False,
        "memory_reclaim_ever_effective": False,
        "memory_reclaim_error_type": "UnsupportedCgroupReclaim",
        "memory_reclaim_attempt_count": 1,
        "memory_reclaim_success_count": 0,
        "memory_reclaim_max_attempts": 3,
        "credential_safe": True,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "credential": "must-not-survive",
    }
    if last_durable is not None:
        payload["last_durable_progress_component"] = last_durable
    return payload


def _install_fake() -> SimpleNamespace:
    bridge._latest_context = None
    fake = SimpleNamespace(
        _qualifier_failure_context=lambda _stderr: None,
        write_release_evidence_prequalification=(
            release_state.write_release_evidence_prequalification
        ),
    )
    bridge.install(fake)
    return fake


def test_active_lane_and_memory_metrics_survive_signed_prequalification(tmp_path) -> None:
    fake = _install_fake()
    event = _memory_event()
    stderr = "provider noise\n" + json.dumps(event) + "\n"

    context = fake._qualifier_failure_context(stderr)
    assert context is not None
    assert context["failure_asset_class"] == "crypto"
    assert context["failure_lane_index"] == 7
    assert "credential" not in context
    assert context["decision_authority"] is False
    assert context["execution_authority"] is False

    detail = (
        "bounded evidence qualification returned code 125; "
        f"child_stage={context['failure_stage']}; "
        f"child_error_type={context['error_type']}; "
        f"child_detail={context['error_detail']}"
    )
    fake.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail=detail,
        metrics={"qualifier_return_code": 125},
    )

    stored = release_state.load_release_evidence_prequalification(_values(tmp_path))
    assert stored is not None
    failure = stored["failure_context"]
    assert failure["failure_stage"] == event["failure_stage"]
    assert failure["failure_progress_kind"] == "active"
    assert failure["failure_substage"] == "publication-lane"
    assert failure["failure_asset_class"] == "crypto"
    assert failure["failure_lane_index"] == 7
    assert failure["memory_trigger_reason"] == "working_set"
    assert failure["memory_accounting_source"] == "cgroup_v2_configured_ceiling"
    assert failure["memory_reclaim_attempted"] is True
    assert failure["memory_reclaim_supported"] is False
    assert failure["memory_reclaim_requested_kib"] == 108376
    assert failure["memory_reclaim_raw_before_kib"] == 1963044
    assert failure["memory_reclaim_raw_after_kib"] == 1963044
    assert failure["memory_reclaim_working_set_before_kib"] == 646572
    assert failure["memory_reclaim_working_set_after_kib"] == 646572
    assert failure["memory_reclaim_reclaimed_kib"] == 0
    assert failure["memory_reclaim_effective"] is False
    assert failure["memory_reclaim_ever_effective"] is False
    assert failure["memory_reclaim_error_type"] == "UnsupportedCgroupReclaim"
    assert failure["memory_reclaim_attempt_count"] == 1
    assert failure["memory_reclaim_success_count"] == 0
    assert failure["memory_reclaim_max_attempts"] == 3
    assert failure["lane_progress_metrics"] == {
        "active_lane_index": 7,
        "candidate_lanes": 13,
        "completed_publication_lanes": 7,
    }
    assert "credential" not in failure
    assert failure["decision_authority"] is False
    assert failure["execution_authority"] is False
    assert failure["paper_only"] is True
    assert failure["real_money_authorized"] is False

    metrics = stored["metrics"]
    assert metrics["failure_lane_index"] == 7
    assert metrics["memory_process_peak_rss_kib"] == 930000
    assert metrics["memory_working_set_peak_kib"] == 1450000
    assert metrics["memory_raw_peak_kib"] == 1710000
    assert metrics["memory_working_set_boundary_kib"] == 1441792
    assert metrics["memory_raw_hard_boundary_kib"] == 1887436
    assert metrics["memory_trigger_working_set"] == 1
    assert metrics["failure_progress_active"] == 1
    assert metrics["lane_candidate_lanes"] == 13
    assert metrics["lane_completed_publication_lanes"] == 7
    assert "lane_secret_metric" not in metrics


def test_completed_lane_is_labeled_last_durable_not_exact_failure_source(tmp_path) -> None:
    fake = _install_fake()
    coarse = "stage_isolated_evidence:comprehensive_discovery"
    event = _memory_event(
        progress_kind="completed",
        failure_stage=coarse,
        last_durable="bounded-publication-lane-complete:future",
    )
    event["memory_trigger_reason"] = "raw_hard_ceiling"
    event["failure_lane_index"] = None
    context = fake._qualifier_failure_context(json.dumps(event))
    assert context is not None

    detail = (
        "bounded evidence qualification returned code 125; "
        f"child_stage={coarse}; child_error_type=ResourceBoundaryExceeded; "
        f"child_detail={context['error_detail']}"
    )
    fake.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail=detail,
        metrics={"qualifier_return_code": 125},
    )

    stored = release_state.load_release_evidence_prequalification(_values(tmp_path))
    assert stored is not None
    failure = stored["failure_context"]
    assert failure["failure_progress_kind"] == "completed"
    assert failure["last_durable_progress_component"] == (
        "bounded-publication-lane-complete:future"
    )
    assert failure["failure_stage"] == (
        coarse + ":last_durable:bounded-publication-lane-complete:future"
    )
    assert stored["metrics"]["failure_progress_completed"] == 1
    assert stored["metrics"]["memory_trigger_raw_hard_ceiling"] == 1
    assert "failure_lane_index" not in stored["metrics"]


def test_context_from_prior_attempt_cannot_contaminate_unrelated_terminal_failure(
    tmp_path,
) -> None:
    fake = _install_fake()
    event = _memory_event()
    context = fake._qualifier_failure_context(json.dumps(event))
    assert context is not None

    fake.write_release_evidence_prequalification(
        _values(tmp_path),
        state="failed",
        stage="evidence_prequalification_failed",
        detail="evidence qualifier could not start: OSError",
        metrics={"qualifier_start_failed": 1},
    )

    stored = release_state.load_release_evidence_prequalification(_values(tmp_path))
    assert stored is not None
    failure = stored["failure_context"]
    assert "failure_asset_class" not in failure
    assert "memory_trigger_reason" not in failure
    assert "failure_lane_index" not in stored["metrics"]


def test_unsafe_child_context_is_rejected() -> None:
    event = _memory_event()
    event["execution_authority"] = True
    assert bridge.extract_failure_context(json.dumps(event)) is None


def test_render_workspace_installs_bridge_before_runtime_wrappers() -> None:
    source = Path("run_render_service_workspace.py").read_text(encoding="utf-8")
    bridge_call = "install_telemetry_712_failure_context_bridge(memory_safe)"
    assert source.index(bridge_call) < source.index(
        "install_stage_isolated_audit_runtime(render_bootstrap)"
    )
    assert source.index(bridge_call) < source.index(
        "install_release_prequalification_parent_watchdog(memory_safe)"
    )
