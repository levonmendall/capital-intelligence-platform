import json

from operations import telemetry_712_failure_context_bridge as bridge_module


def test_terminal_failure_bridge_preserves_only_safe_memory_attribution() -> None:
    stderr = json.dumps(
        {
            "event": "continuous_evidence_plane_failure_context",
            "credential_safe": True,
            "decision_authority": False,
            "candidate_authority": False,
            "sizing_authority": False,
            "construction_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
            "error_type": "ResourceBoundaryExceeded",
            "failure_stage": "comprehensive_discovery",
            "error_detail": "raw hard ceiling reached",
            "lane_progress_metrics": {
                "active_lane_index": 4,
                "memory_cgroup_file_kib": 700_000,
                "memory_cgroup_inactive_file_kib": 650_000,
                "memory_store_discovery_spool_kib": 128_000,
                "memory_store_scan_truncated": True,
                "provider_api_key": "must-not-survive",
            },
        }
    )

    context = bridge_module.extract_failure_context(stderr)
    assert context is not None
    progress = context["lane_progress_metrics"]
    assert progress["memory_cgroup_file_kib"] == 700_000
    assert progress["memory_cgroup_inactive_file_kib"] == 650_000
    assert progress["memory_store_discovery_spool_kib"] == 128_000
    assert "memory_store_scan_truncated" not in progress
    assert "provider_api_key" not in progress

    metrics = bridge_module._metric_projection(context)
    assert metrics["memory_cgroup_file_kib"] == 700_000
    assert metrics["memory_cgroup_inactive_file_kib"] == 650_000
    assert metrics["memory_store_discovery_spool_kib"] == 128_000
    assert "lane_memory_cgroup_file_kib" not in metrics
    assert metrics["lane_active_lane_index"] == 4
    assert "provider_api_key" not in metrics
    assert "lane_provider_api_key" not in metrics
