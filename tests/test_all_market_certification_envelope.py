from __future__ import annotations

from cio.models import CandidateAssetClass
from operations.all_market_certification_envelope import (
    build_all_market_certification_envelope,
)


def _lane(asset_class: str, *, fresh: bool = True) -> dict[str, object]:
    return {
        "asset_class": asset_class,
        "freshness_valid": fresh,
        "point_in_time_valid": True,
        "terminal_accounting_complete": True,
    }


def _audit(*, lane_count: int = 13, stale_index: int | None = None) -> dict[str, object]:
    names = [
        item.value for item in CandidateAssetClass if item is not CandidateAssetClass.OTHER
    ]
    lanes = [
        _lane(name, fresh=index != stale_index)
        for index, name in enumerate(names[:lane_count])
    ]
    return {
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_id": "certification-identity-123456",
        "all_market_certification_v2_state": "CERTIFIED",
        "all_market_operational_certified": True,
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certified_lanes": lanes,
        "certification_v2_cutoff": "2026-08-30T21:30:00+00:00",
        "all_market_evidence_generation_id": "generation-123",
        "all_market_point_in_time_snapshot_id": "pit-123",
        "all_market_global_discovery_snapshot_id": "global-123",
        "all_market_us_equity_discovery_snapshot_id": "equity-123",
        "all_market_paper_evidence_snapshot_id": "paper-123",
        "all_market_policy_compatibility_hash": "policy-123",
        "all_market_certification_aggregate_sha256": "aggregate-123",
        "all_market_certification_discovery_manifest_fingerprint": "manifest-123",
    }


def _values() -> dict[str, str]:
    return {"CAPITAL_INTELLIGENCE_RELEASE": "abcdef1234567890"}


def test_certified_envelope_preserves_exact_release_and_evidence_identity() -> None:
    envelope = build_all_market_certification_envelope(
        _audit(),
        values=_values(),
        verifier_source_id="certification-finalizer",
    )

    assert envelope["schema_version"] == "all-market-certification-envelope.v1"
    assert envelope["certified"] is True
    assert envelope["blocker"] is None
    assert envelope["release_sha"] == "abcdef1234567890"
    assert envelope["certification_id"] == "certification-identity-123456"
    assert envelope["certification_state"] == "CERTIFIED"
    assert envelope["evidence_cutoff"] == "2026-08-30T21:30:00+00:00"
    assert envelope["verifier_source_id"] == "certification-finalizer"
    assert envelope["coverage"] == {
        "certified_count": 13,
        "represented_count": 13,
        "required_count": 13,
        "complete": True,
    }
    assert envelope["freshness_valid"] is True
    assert envelope["point_in_time_valid"] is True
    assert envelope["terminal_accounting_valid"] is True
    assert envelope["evidence_identity"]["evidence_generation_id"] == "generation-123"
    assert envelope["evidence_identity"]["global_discovery_snapshot_id"] == "global-123"
    assert envelope["paper_only"] is True
    assert envelope["real_money_authorized"] is False


def test_partial_market_coverage_cannot_present_as_all_market_certified() -> None:
    envelope = build_all_market_certification_envelope(
        _audit(lane_count=12),
        values=_values(),
    )

    assert envelope["certified"] is False
    assert envelope["blocker"] == "market_coverage:12/13"
    assert envelope["coverage"]["represented_count"] == 12
    assert envelope["coverage"]["required_count"] == 13
    assert envelope["coverage"]["certified_count"] == 0


def test_stale_lane_cannot_present_as_all_market_certified() -> None:
    envelope = build_all_market_certification_envelope(
        _audit(stale_index=4),
        values=_values(),
    )

    assert envelope["certified"] is False
    assert envelope["blocker"] == "freshness_invalid"
    assert envelope["freshness_valid"] is False
    assert envelope["coverage"]["represented_count"] == 13


def test_missing_certification_fails_closed_with_release_context() -> None:
    envelope = build_all_market_certification_envelope({}, values=_values())

    assert envelope["certified"] is False
    assert envelope["blocker"] == "certification_v2_unavailable"
    assert envelope["release_sha"] == "abcdef1234567890"
    assert envelope["certification_id"] is None
    assert envelope["coverage"]["represented_count"] == 0
    assert envelope["paper_only"] is True
    assert envelope["real_money_authorized"] is False
