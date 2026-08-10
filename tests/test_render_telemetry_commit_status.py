from __future__ import annotations

from scripts import render_telemetry_commit_status as status


def _snapshot() -> dict[str, object]:
    return {
        "schema_version": "render-production-telemetry.v1",
        "capture_state": "ok",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "diagnostic": {
            "state": "in_progress",
            "stage": "deep_evidence",
            "elapsed_seconds": 612.4,
            "release_matches_expected": True,
            "all_market_evaluation_complete": False,
        },
    }


def test_in_progress_status_exposes_live_stage() -> None:
    state_name, description = status.status_for_snapshot(_snapshot())

    assert state_name == "pending"
    assert description == (
        "stage=deep_evidence state=in_progress elapsed=612s release_match=yes"
    )


def test_completed_exact_release_is_success() -> None:
    snapshot = _snapshot()
    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    diagnostic.update(
        {
            "state": "completed",
            "stage": None,
            "elapsed_seconds": 355.6,
            "all_market_evaluation_complete": True,
        }
    )

    state_name, description = status.status_for_snapshot(snapshot)

    assert state_name == "success"
    assert "state=completed" in description
    assert "elapsed=356s" in description


def test_failed_diagnostic_is_error() -> None:
    snapshot = _snapshot()
    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    diagnostic["state"] = "timed_out"

    state_name, description = status.status_for_snapshot(snapshot)

    assert state_name == "error"
    assert "state=timed_out" in description


def test_unavailable_capture_stays_pending_without_error_detail() -> None:
    snapshot = {
        "schema_version": "render-production-telemetry.v1",
        "capture_state": "unavailable",
        "error_type": "PrivateBackendCredentialLikeFailure",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    state_name, description = status.status_for_snapshot(snapshot)

    assert state_name == "pending"
    assert description == (
        "telemetry=unavailable stage=unavailable state=unknown elapsed=unknown"
    )
    assert "PrivateBackend" not in description


def test_unknown_fields_cannot_leak_into_status_description() -> None:
    snapshot = _snapshot()
    snapshot["ignored_private_value"] = "SHOULD_NEVER_APPEAR"
    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    diagnostic["another_private_value"] = "ALSO_NEVER_APPEAR"

    _state_name, description = status.status_for_snapshot(snapshot)

    assert "SHOULD_NEVER_APPEAR" not in description
    assert "ALSO_NEVER_APPEAR" not in description
    assert len(description) <= 140


def test_invalid_safety_contract_is_rejected() -> None:
    snapshot = _snapshot()
    snapshot["credential_safe"] = False

    try:
        status.status_for_snapshot(snapshot)
    except status.InvalidTelemetrySnapshot:
        pass
    else:
        raise AssertionError("unsafe telemetry snapshot should be rejected")
