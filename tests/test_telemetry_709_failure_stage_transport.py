"""Verify telemetry #709 exact lane stage survives release attribution."""

from operations.evidence_prequalification_attribution import (
    EvidencePrequalificationReason,
    failed_prequalification_attribution,
)


def test_exact_lane_memory_stage_survives_release_attribution() -> None:
    exact_stage = (
        "stage_isolated_evidence:comprehensive_discovery:publication-lane:us_equity"
    )
    detail = (
        f"child_stage={exact_stage}; "
        "child_error_type=ResourceBoundaryExceeded; "
        "child_detail=stage_isolated_evidence_resource_boundary; "
        "stage=comprehensive_discovery; trigger_reason=working_set; "
        "lane_progress_kind=active; lane_substage=publication-lane; "
        "lane_asset_class=us_equity; active_lane_index=0; "
        "lane_component=bounded-spool-publication-lane:us_equity"
    )

    result = failed_prequalification_attribution(
        detail=detail,
        metrics={"qualifier_return_code": 125},
    )

    assert result.reason is EvidencePrequalificationReason.RESOURCE_EXHAUSTED
    assert result.capability == "comprehensive_discovery"
    assert result.failure_stage == exact_stage
    assert result.error_type == "ResourceBoundaryExceeded"
    assert "lane_asset_class=us_equity" in result.detail
