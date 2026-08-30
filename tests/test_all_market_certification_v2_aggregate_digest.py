from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import operations.all_market_certification_readonly as readonly


def test_v2_lane_projection_publishes_integrity_bound_aggregate_digest(tmp_path: Path) -> None:
    release = "release-aggregate"
    evidence_as_of = datetime(2026, 8, 30, 21, 0, tzinfo=timezone.utc)
    lane = {
        "asset_class": "us_equity",
        "scheduled": True,
        "catalog_count": 1,
        "deep_analyzed_count": 1,
        "selected_count": 1,
        "excluded_count": 0,
        "terminal_count": 1,
        "terminal_accounting_complete": True,
        "point_in_time_valid": True,
        "freshness_valid": True,
    }
    body: dict[str, object] = {
        "schema_version": "all-market-certification-input.v2",
        "release": release,
        "evidence_as_of": evidence_as_of.isoformat(),
        "scheduled_lanes": ["us_equity"],
        "global_discovery_snapshot_id": "global-aggregate",
        "global_discovery_lane_summary": [lane],
    }
    certification_id = readonly._digest(body)
    path = (
        tmp_path
        / "all-market-certification-v2"
        / "inputs"
        / release
        / f"{certification_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({**body, "record_id": certification_id}),
        encoding="utf-8",
    )

    result = readonly._v2_lane_audit(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
            "CAPITAL_INTELLIGENCE_RELEASE": release,
        },
        {
            "all_market_certification_v2_available": True,
            "all_market_certification_v2_input_integrity_valid": True,
            "all_market_certification_v2_state_integrity_valid": True,
            "all_market_certification_v2_release_matches": True,
            "all_market_certification_v2_id": certification_id,
            "all_market_global_discovery_snapshot_id": "global-aggregate",
            "all_market_evidence_certified": True,
            "all_market_screening_certified": True,
        },
    )

    assert result["all_market_runtime_certified"] is True
    assert result["all_market_certification_integrity_valid"] is True
    assert result["all_market_certification_id"] == certification_id
    assert result["all_market_certification_aggregate_sha256"] == certification_id


def test_unavailable_v2_lane_projection_never_invents_aggregate_digest() -> None:
    result = readonly._unavailable_v2_lane_audit()

    assert result["all_market_runtime_certified"] is False
    assert result["all_market_certification_aggregate_sha256"] is None
