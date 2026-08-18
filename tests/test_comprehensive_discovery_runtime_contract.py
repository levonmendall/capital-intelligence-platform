from __future__ import annotations

from operations import manual_cio_diagnostic as manual
from operations.comprehensive_discovery_runtime_contract import (
    _EXACT_PROGRESS_STAGES,
    _LANE_PROGRESS_STAGES,
    _PROGRESS_METRICS,
    _register_manual_diagnostic_contract,
)
from scripts.enrich_comprehensive_discovery_telemetry import enrich_snapshot


def test_authoritative_discovery_progress_contract_is_registered() -> None:
    _register_manual_diagnostic_contract()

    assert _EXACT_PROGRESS_STAGES <= manual._PROGRESS_STAGES
    assert _LANE_PROGRESS_STAGES <= manual._PROGRESS_LANE_STAGES
    assert _PROGRESS_METRICS <= manual._PROGRESS_METRICS
    normalized = dict(
        manual._normalize_progress_metrics(
            {
                "provider_budget_count": 3,
                "required_nodes": 9,
                "completed_nodes": 7,
                "reused_nodes": 4,
                "compatibility_rebound_nodes": 2,
                "rebound_nodes": 2,
            }
        )
    )
    assert normalized["required_nodes"] == 9
    assert normalized["completed_nodes"] == 7


def _public(detail: str, *, release: str = "a" * 40) -> dict[str, object]:
    return {
        "active_release": release,
        "detail": detail,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _snapshot(release: str = "a" * 40) -> dict[str, object]:
    return {
        "diagnostic": {
            "active_release": release,
            "prequalification_failure_reason": "internal_error",
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_discovery_lane_failure_is_promoted_without_symbols_or_payloads() -> None:
    release = "a" * 40
    detail = (
        "child_stage=component_qualified_evidence_maintenance; "
        "child_error_type=ContinuousEvidencePlaneError; "
        "child_detail=persistent certification DAG is not ready: "
        "comprehensive discovery lane acquisition failed; "
        "node=deep-market-evidence:crypto; asset_class=crypto; "
        "failure_type=TimeoutError; decision_eligible_count=31; "
        "completed_nodes=7; required_nodes=9; reused_nodes=5; retry_after=none"
    )

    enriched = enrich_snapshot(_snapshot(release), _public(detail, release=release), expected_release=release)
    diagnostic = enriched["diagnostic"]
    assert diagnostic["prequalification_failure_unit"] == "deep-market-evidence:crypto"
    assert diagnostic["prequalification_failure_reason"] == "discovery_lane_failure"
    progress = diagnostic["comprehensive_discovery_progress"]
    assert progress["asset_class"] == "crypto"
    assert progress["failure_type"] == "TimeoutError"
    assert progress["completed_nodes"] == 7
    assert progress["required_nodes"] == 9
    assert progress["reused_nodes"] == 5
    assert "candidate_symbols" not in progress
    assert "provider_payloads" not in progress


def test_provider_free_finalizer_failure_is_promoted() -> None:
    release = "b" * 40
    detail = (
        "child_stage=component_qualified_evidence_maintenance; "
        "child_error_type=ContinuousEvidencePlaneError; "
        "child_detail=provider-free-finalizer; failure_type=ComprehensiveMarketDiscoveryError"
    )

    enriched = enrich_snapshot(_snapshot(release), _public(detail, release=release), expected_release=release)
    diagnostic = enriched["diagnostic"]
    assert diagnostic["prequalification_failure_unit"] == "provider-free-finalizer"
    assert diagnostic["prequalification_failure_reason"] == "finalizer_failure"
    assert diagnostic["comprehensive_discovery_progress"]["failure_type"] == "ComprehensiveMarketDiscoveryError"
