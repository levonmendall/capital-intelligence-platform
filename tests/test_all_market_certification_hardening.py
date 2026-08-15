from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import api.routes.cio_diagnostic as cio_audit
import run_manual_cio_diagnostic as manual_runner
from operations import manual_cio_diagnostic as coordination
from operations.all_market_certification_audit import public_all_market_certification


def _digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def test_owner_lease_blocks_live_duplicate_and_releases(tmp_path: Path) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    request_id = "request-live-owner"

    assert manual_runner._acquire_owner_lease(request_id, values) is True
    assert manual_runner._active_owner_exists(request_id, values) is True
    assert manual_runner._acquire_owner_lease(request_id, values) is False

    manual_runner._release_owner_lease(request_id, values)
    assert manual_runner._active_owner_exists(request_id, values) is False


def test_owner_lease_reclaims_dead_process(tmp_path: Path) -> None:
    values = {"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)}
    lease = tmp_path / "manual-cio-diagnostic-owner.json"
    lease.write_text(
        json.dumps(
            {
                "request_id": "dead-request",
                "pid": 999_999_999,
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    assert manual_runner._acquire_owner_lease("replacement-request", values) is True
    assert manual_runner._active_owner_exists("replacement-request", values) is True
    manual_runner._release_owner_lease("replacement-request", values)


def test_governed_no_action_requires_explicit_complete_briefing() -> None:
    assert manual_runner._governed_no_action(
        {
            "identifier": "briefing:1",
            "as_of": "2026-08-14T20:00:00+00:00",
            "portfolio_decision": "Remain in cash.",
            "status": "no_superior_opportunity",
        }
    )
    assert not manual_runner._governed_no_action(
        {
            "identifier": "briefing:2",
            "as_of": "2026-08-14T20:00:00+00:00",
            "portfolio_decision": "Execution blocked.",
            "status": "implementation_blocked",
        }
    )


def test_recovery_progress_metrics_are_accepted_by_release_runtime() -> None:
    # Importing the release wrapper installs the metric contract before any provider
    # recovery can emit these counters.
    import run_bounded_manual_cio_diagnostic  # noqa: F401

    normalized = coordination._normalize_progress_metrics(
        {"recovery_exchanges": 2, "recovered_exchanges": 1}
    )
    assert dict(normalized) == {
        "recovered_exchanges": 1,
        "recovery_exchanges": 2,
    }


def test_public_all_market_certificate_requires_exact_hash_and_release(
    tmp_path: Path,
) -> None:
    release = "abc123"
    certification_id = "cert-1"
    epoch = "2026-08-14T20:00:00+00:00"
    discovery_fingerprint = "discovery-manifest-abc"
    body = {
        "schema_version": "all-market-lane-certification.v1",
        "certification_id": certification_id,
        "release_sha": release,
        "decision_epoch": epoch,
        "required_lanes": ["crypto"],
        "lane_artifact_sha256": {"crypto": "lane-hash"},
        "discovery_manifest_fingerprint": discovery_fingerprint,
        "all_market_runtime_certified": True,
        "blocking_reasons": [],
        "candidate_count_limit_applied": False,
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }
    aggregate_sha = _digest(body)
    root = tmp_path / "all-market-certification"
    certification_dir = root / "certifications" / certification_id
    certification_dir.mkdir(parents=True)
    (certification_dir / "aggregate.json").write_text(
        json.dumps({**body, "sha256": aggregate_sha}),
        encoding="utf-8",
    )
    (root / "latest.json").write_text(
        json.dumps(
            {
                "certification_id": certification_id,
                "release_sha": release,
                "decision_epoch": epoch,
                "all_market_runtime_certified": True,
                "aggregate_sha256": aggregate_sha,
            }
        ),
        encoding="utf-8",
    )
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
    }

    proof = public_all_market_certification(values)
    assert proof["all_market_runtime_certified"] is True
    assert proof["all_market_certification_integrity_valid"] is True
    assert proof["all_market_certification_release_matches"] is True
    assert (
        proof["all_market_certification_discovery_manifest_fingerprint"]
        == discovery_fingerprint
    )

    (certification_dir / "aggregate.json").write_text(
        json.dumps({**body, "blocking_reasons": ["tampered"], "sha256": aggregate_sha}),
        encoding="utf-8",
    )
    tampered = public_all_market_certification(values)
    assert tampered["all_market_runtime_certified"] is False
    assert tampered["all_market_certification_integrity_valid"] is False


def test_certificate_context_binding_uses_evidence_epoch_not_later_cio_clock(
    monkeypatch,
) -> None:
    evidence_as_of = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)
    decision_as_of = datetime(2026, 8, 14, 20, 3, tzinfo=timezone.utc)
    certification = {
        "all_market_certification_epoch": evidence_as_of.isoformat(),
        "certification_v2_cutoff": decision_as_of.isoformat(),
    }
    monkeypatch.setattr(
        cio_audit,
        "_v2_evidence_as_of",
        lambda _certification, *, values: evidence_as_of,
    )

    legacy_matches, v2_matches = cio_audit._certification_context_matches(
        certification,
        values={},
        context_decision_as_of=decision_as_of,
    )
    assert legacy_matches is True
    assert v2_matches is True

    future_certificate = dict(certification)
    future_certificate["all_market_certification_epoch"] = (
        "2026-08-14T20:04:00+00:00"
    )
    legacy_matches, v2_matches = cio_audit._certification_context_matches(
        future_certificate,
        values={},
        context_decision_as_of=decision_as_of,
    )
    assert legacy_matches is False
    assert v2_matches is True

    wrong_cutoff = dict(certification)
    wrong_cutoff["certification_v2_cutoff"] = "2026-08-14T20:04:00+00:00"
    legacy_matches, v2_matches = cio_audit._certification_context_matches(
        wrong_cutoff,
        values={},
        context_decision_as_of=decision_as_of,
    )
    assert legacy_matches is True
    assert v2_matches is False


def _successful_public_audit() -> dict[str, object]:
    return {
        "active_release": "release-1",
        "release_matches": True,
        "state": "completed",
        "completed_at": "2026-08-14T20:00:00+00:00",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "ready": True,
        "context_cycle_matches": True,
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": True,
        "market_lanes": [
            {
                "asset_class": "crypto",
                "scheduled": True,
                "represented": True,
            }
        ],
        "all_market_runtime_certified": True,
        "all_market_certification_integrity_valid": True,
        "all_market_certification_release_matches": True,
        "all_market_certification_context_matches": True,
        "all_market_certification_id": "cert-1",
        "all_market_certification_epoch": "2026-08-14T19:55:00+00:00",
        "all_market_certification_aggregate_sha256": "a" * 64,
        "all_market_certification_discovery_manifest_fingerprint": "discovery-manifest-abc",
        "all_market_certification_v2_available": True,
        "all_market_certification_v2_input_integrity_valid": True,
        "all_market_certification_v2_state_integrity_valid": True,
        "all_market_certification_v2_release_matches": True,
        "all_market_certification_v2_context_matches": True,
        "all_market_certification_v2_id": "cert-v2-1",
        "all_market_evidence_generation_id": "generation-1",
        "all_market_point_in_time_snapshot_id": "pit-1",
        "all_market_global_discovery_snapshot_id": "global-1",
        "all_market_us_equity_discovery_snapshot_id": "equity-1",
        "all_market_paper_evidence_snapshot_id": "paper-1",
        "all_market_policy_compatibility_hash": "b" * 64,
        "all_market_certification_v2_state": "CONSTRUCTION_COMPLETE",
        "all_market_evidence_certified": True,
        "all_market_screening_certified": True,
        "all_market_committee_certified": True,
        "all_market_cio_certified": True,
        "all_market_construction_certified": True,
        "all_market_paper_implementation_certified": False,
        "all_market_no_action_certified": False,
        "all_market_operational_certified": False,
        "paper_implementation_complete": False,
        "schema_version": "public-cio-diagnostic-audit.v2-end-to-end",
    }


def test_verifier_requires_analytical_end_to_end_proof() -> None:
    import verify_render_cio_diagnostic as verifier

    # A complete analytical path through construction is valid even while paper
    # implementation is independently pending.
    verifier.verify_complete_all_market_evaluation(
        _successful_public_audit(),
        expected_release="release-1",
    )

    incomplete = _successful_public_audit()
    incomplete["all_market_cio_certified"] = False
    incomplete["all_market_construction_certified"] = False
    incomplete["all_market_certification_v2_state"] = "COMMITTEE_COMPLETE"
    with pytest.raises(verifier.RenderAuditVerificationError):
        verifier.verify_complete_all_market_evaluation(
            incomplete,
            expected_release="release-1",
        )

    stale_context = _successful_public_audit()
    stale_context["all_market_certification_context_matches"] = False
    with pytest.raises(verifier.RenderAuditVerificationError):
        verifier.verify_complete_all_market_evaluation(
            stale_context,
            expected_release="release-1",
        )
