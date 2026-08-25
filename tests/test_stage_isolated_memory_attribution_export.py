from __future__ import annotations

from operations import comprehensive_discovery_memory_attribution as attribution
from scripts import enrich_stage_isolated_prequalification_telemetry as telemetry


def test_all_persisted_attribution_metrics_are_exported_by_stage_enricher() -> None:
    produced = {
        name: index + 1
        for index, name in enumerate(sorted(attribution._ATTRIBUTION_METRICS))
    }

    exported = telemetry._safe_resource_metrics(produced)

    assert exported == produced
    assert attribution._ATTRIBUTION_METRICS <= set(telemetry._RESOURCE_METRIC_KEYS)


def test_resource_metric_export_remains_numeric_and_allowlist_only() -> None:
    exported = telemetry._safe_resource_metrics(
        {
            "memory_cgroup_file_kib": 901_000,
            "memory_store_discovery_spool_kib": 321_000,
            "memory_store_reference_kib": True,
            "memory_store_historical_kib": -1,
            "memory_store_continuous_evidence_kib": "not-a-number",
            "memory_private_path": 777,
        }
    )

    assert exported == {
        "memory_cgroup_file_kib": 901_000,
        "memory_store_discovery_spool_kib": 321_000,
    }


def test_terminal_enrichment_promotes_attribution_without_unknown_fields() -> None:
    snapshot = {
        "diagnostic": {
            "release_matches_expected": True,
            "progress_metrics": {"memory_raw_peak_kib": 1_900_000},
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    public_payload = {
        "active_release": "release-current",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "progress_metrics": {
            "memory_cgroup_file_kib": 1_250_000,
            "memory_cgroup_inactive_file_kib": 1_100_000,
            "memory_store_discovery_spool_kib": 480_000,
            "memory_store_historical_kib": 220_000,
            "arbitrary_metric": 999,
        },
    }

    enriched = telemetry.enrich_snapshot(
        snapshot,
        public_payload,
        expected_release="release-current",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    metrics = diagnostic["progress_metrics"]
    assert isinstance(metrics, dict)
    assert metrics["memory_raw_peak_kib"] == 1_900_000
    assert metrics["memory_cgroup_file_kib"] == 1_250_000
    assert metrics["memory_cgroup_inactive_file_kib"] == 1_100_000
    assert metrics["memory_store_discovery_spool_kib"] == 480_000
    assert metrics["memory_store_historical_kib"] == 220_000
    assert "arbitrary_metric" not in metrics
    assert enriched["enriched_from_resource_failure_context"] is True
