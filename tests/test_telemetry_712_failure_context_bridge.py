from operations.telemetry_712_failure_context_bridge import (
    build_continuous_evidence_plane_failure_context,
)


def test_terminal_failure_bridge_preserves_only_safe_memory_attribution() -> None:
    bridge = build_continuous_evidence_plane_failure_context(
        active_context={
            "failure_reason": "resource_exhausted",
            "memory_raw_peak_kib": 1_900_000,
        },
        persisted_context={
            "failure_stage": "comprehensive_discovery",
            "memory_cgroup_file_kib": 700_000,
            "memory_cgroup_inactive_file_kib": 650_000,
            "memory_store_discovery_spool_kib": 128_000,
            "memory_store_scan_truncated": True,
            "provider_api_key": "must-not-survive",
        },
        lane_context={
            "lane": "international_equity",
            "memory_raw_peak_kib": 1_900_000,
            "memory_cgroup_file_kib": 700_000,
            "provider_api_key": "must-not-survive",
        },
    )

    assert bridge["memory_cgroup_file_kib"] == 700_000
    assert bridge["memory_cgroup_inactive_file_kib"] == 650_000
    assert bridge["memory_store_discovery_spool_kib"] == 128_000
    assert "lane_memory_cgroup_file_kib" not in bridge
    assert bridge["lane_memory_raw_peak_kib"] == 1_900_000
    assert bridge["lane_lane"] == "international_equity"
    assert "memory_store_scan_truncated" not in bridge
    assert "provider_api_key" not in bridge
    assert "lane_provider_api_key" not in bridge
