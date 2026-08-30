from __future__ import annotations

import pytest

from verify_render_cio_diagnostic import (
    RenderAuditVerificationError,
    verify_complete_all_market_evaluation,
)


def _complete_payload(release: str) -> dict[str, object]:
    return {
        "schema_version": "public-cio-diagnostic-audit.v2-end-to-end",
        "credential_safe": True,
        "active_release": release,
        "release_matches": True,
        "state": "completed",
        "completed_at": "2026-08-30T21:44:16+00:00",
        "ready": True,
        "context_cycle_matches": True,
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": True,
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_context_matches": True,
        "all_market_certification_id": "certification-v2-release-current",
        "all_market_certification_epoch": "2026-08-30T21:40:00+00:00",
        "all_market_certification_aggregate_sha256": None,
        "all_market_certification_discovery_manifest_fingerprint": "global-current",
        "all_market_lane_certification_source": "certification_v2_input_summary",
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_id": "certification-v2-release-current",
        "all_market_evidence_generation_id": "generation-current",
        "all_market_point_in_time_snapshot_id": "pit-current",
        "all_market_global_discovery_snapshot_id": "global-current",
        "all_market_us_equity_discovery_snapshot_id": "equity-current",
        "all_market_paper_evidence_snapshot_id": "paper-current",
        "all_market_policy_compatibility_hash": "b" * 64,
        "all_market_certification_v2_state": "CERTIFIED",
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
        "all_market_committee_certified": True,
        "all_market_cio_certified": True,
        "all_market_construction_certified": True,
        "all_market_paper_implementation_certified": True,
        "all_market_no_action_certified": False,
        "all_market_operational_certified": True,
        "paper_implementation_complete": True,
        "market_lanes": [
            {
                "asset_class": "crypto",
                "scheduled": True,
                "represented": True,
                "catalog_count": 5,
                "deep_analyzed_count": 5,
                "selected_count": 2,
            },
            {
                "asset_class": "fixed_income",
                "scheduled": True,
                "represented": True,
                "catalog_count": 7,
                "deep_analyzed_count": 7,
                "selected_count": 3,
            },
        ],
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_v2_lane_summary_does_not_require_legacy_aggregate_sha() -> None:
    verify_complete_all_market_evaluation(
        _complete_payload("release-current"),
        expected_release="release-current",
    )


def test_legacy_lane_source_still_requires_aggregate_sha() -> None:
    payload = {
        **_complete_payload("release-current"),
        "all_market_lane_certification_source": "legacy_compositional_certificate",
        "all_market_certification_aggregate_sha256": None,
    }

    with pytest.raises(
        RenderAuditVerificationError,
        match="all_market_certification_aggregate_sha256",
    ):
        verify_complete_all_market_evaluation(
            payload,
            expected_release="release-current",
        )


def test_unknown_lane_source_fails_closed() -> None:
    payload = {
        **_complete_payload("release-current"),
        "all_market_lane_certification_source": "unknown-proof",
    }

    with pytest.raises(
        RenderAuditVerificationError,
        match="all_market_lane_certification_source",
    ):
        verify_complete_all_market_evaluation(
            payload,
            expected_release="release-current",
        )
