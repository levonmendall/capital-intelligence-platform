from __future__ import annotations

from scripts import enrich_comprehensive_discovery_telemetry as subject


_RELEASE = "8c0298a5202485fe885373a308961fcc6580d136"


def _public(detail: str) -> dict[str, object]:
    return {
        "active_release": _RELEASE,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "detail": detail,
    }


def test_lane_timeout_promotes_exact_actionable_attribution() -> None:
    snapshot = {
        "diagnostic": {
            "state": "failed",
            "prequalification_failure_reason": "internal_error",
            "prequalification_failure_error_type": "ContinuousEvidencePlaneError",
        }
    }
    public = _public(
        "comprehensive discovery lane acquisition failed; "
        "node=deep-market-evidence:international_equity; "
        "asset_class=international_equity; "
        "failure_type=SupervisedComponentTimeout; "
        "decision_eligible_count=844; completed_nodes=3; required_nodes=8; reused_nodes=1"
    )

    enriched = subject.enrich_snapshot(snapshot, public, expected_release=_RELEASE)
    diagnostic = enriched["diagnostic"]

    assert diagnostic["prequalification_failure_reason"] == "deadline_exceeded"
    assert diagnostic["prequalification_failure_unit"] == (
        "deep-market-evidence:international_equity"
    )
    assert diagnostic["prequalification_failure_asset_class"] == "international_equity"
    assert diagnostic["prequalification_failure_type"] == "SupervisedComponentTimeout"
    assert diagnostic["comprehensive_discovery_progress"] == {
        "state": "failed",
        "blocking_unit": "deep-market-evidence:international_equity",
        "asset_class": "international_equity",
        "failure_type": "SupervisedComponentTimeout",
        "decision_eligible_count": 844,
        "completed_nodes": 3,
        "required_nodes": 8,
        "reused_nodes": 1,
        "retry_after": None,
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def test_non_timeout_lane_failure_stays_lane_failure() -> None:
    snapshot = {"diagnostic": {"prequalification_failure_reason": "internal_error"}}
    public = _public(
        "comprehensive discovery lane acquisition failed; "
        "node=deep-market-evidence:crypto; asset_class=crypto; "
        "failure_type=ProviderEvidenceError"
    )

    enriched = subject.enrich_snapshot(snapshot, public, expected_release=_RELEASE)

    assert enriched["diagnostic"]["prequalification_failure_reason"] == (
        "discovery_lane_failure"
    )
    assert enriched["diagnostic"]["prequalification_failure_type"] == (
        "ProviderEvidenceError"
    )


def test_enricher_rejects_other_release_and_does_not_invent_failure() -> None:
    snapshot = {"diagnostic": {"prequalification_failure_reason": "internal_error"}}
    public = _public(
        "comprehensive discovery lane acquisition failed; "
        "node=deep-market-evidence:fx; asset_class=fx; "
        "failure_type=SupervisedComponentTimeout"
    )
    public["active_release"] = "other-release"

    assert subject.enrich_snapshot(snapshot, public, expected_release=_RELEASE) == snapshot
