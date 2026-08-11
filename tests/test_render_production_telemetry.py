from datetime import UTC, datetime

import pytest

from scripts import capture_render_production_telemetry as telemetry


EXPECTED_RELEASE = "release-33"
CAPTURED_AT = datetime(2026, 8, 11, 4, 47, 12, tzinfo=UTC)


def _payload(
    *,
    state: str,
    active_release: str = EXPECTED_RELEASE,
    release_matches: bool = True,
    detail: str = "",
    market_lanes: list[dict[str, object]] | None = None,
    all_market_evaluation_complete: bool = False,
) -> dict[str, object]:
    return {
        "state": state,
        "active_release": active_release,
        "release_matches": release_matches,
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "detail": detail,
        "market_lanes": market_lanes or [],
        "all_market_evaluation_complete": all_market_evaluation_complete,
    }


def _annotated(
    payload: dict[str, object], *, timed_out: bool = False
) -> dict[str, object]:
    snapshot = telemetry.build_snapshot(
        payload,
        expected_release=EXPECTED_RELEASE,
        captured_at=CAPTURED_AT,
    )
    return telemetry._annotate_observation(
        snapshot,
        observation_count=3,
        observed_duration_seconds=12.5,
        timed_out=timed_out,
    )


def test_failed_exact_release_without_progress_fails_closed_as_startup_failure():
    snapshot = _annotated(_payload(state="failed"))
    assert snapshot["progress_started"] is False
    assert snapshot["failure_class"] == "startup_failure"
    assert telemetry._exit_code(snapshot, unsafe=False) != 0


def test_failed_exact_release_after_progress_is_terminal_failure():
    snapshot = _annotated(
        _payload(
            state="failed",
            detail="governed_progress=terminal_screening; lanes=1",
        )
    )
    assert snapshot["progress_started"] is True
    assert snapshot["failure_class"] == "terminal_failure"
    assert telemetry._exit_code(snapshot, unsafe=False) != 0


def test_direct_stage_survives_terminal_detail_and_marks_progress():
    payload = _payload(state="failed", detail="bounded child terminated fail-closed")
    payload.update(
        {
            "diagnostic_id": "abc123",
            "stage": "deep_market_evidence:international_equity",
            "diagnostic_age_seconds": 1500.0,
            "terminal_age_seconds": 7200.0,
            "context_attempt_state": "ready",
        }
    )
    snapshot = _annotated(payload)
    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["diagnostic_id"] == "abc123"
    assert diagnostic["stage"] == "deep_market_evidence:international_equity"
    assert diagnostic["terminal_age_seconds"] == 7200.0
    assert diagnostic["context_attempt_state"] == "ready"
    assert snapshot["progress_started"] is True
    assert snapshot["failure_class"] == "terminal_failure"


def test_pending_diagnostic_at_watch_exhaustion_is_timeout_and_fails_closed():
    snapshot = _annotated(_payload(state="pending"), timed_out=True)
    assert snapshot["failure_class"] == "timeout"
    assert telemetry._exit_code(snapshot, unsafe=False) != 0


def test_exact_release_completed_all_market_diagnostic_succeeds():
    snapshot = _annotated(
        _payload(state="completed", all_market_evaluation_complete=True)
    )
    assert snapshot["failure_class"] == "none"
    assert telemetry._exit_code(snapshot, unsafe=False) == 0


def test_release_mismatch_is_explicit_and_fails_closed():
    snapshot = _annotated(
        _payload(
            state="completed",
            active_release="older-release",
            release_matches=False,
            all_market_evaluation_complete=True,
        )
    )
    assert snapshot["failure_class"] == "release_mismatch"
    assert telemetry._exit_code(snapshot, unsafe=False) != 0


def test_observation_metadata_is_bounded_and_safe():
    snapshot = _annotated(_payload(state="failed"))
    assert snapshot["observation_count"] == 3
    assert snapshot["observed_duration_seconds"] == 12.5
    assert snapshot["failure_class"] in {
        "none",
        "startup_failure",
        "terminal_failure",
        "timeout",
        "release_mismatch",
    }
    assert "holdings" not in snapshot
    assert "positions" not in snapshot


def test_forbidden_source_fields_remain_rejected():
    payload = _payload(state="failed")
    payload["holdings"] = ["sensitive"]
    with pytest.raises(telemetry.UnsafeTelemetryPayload):
        telemetry.build_snapshot(
            payload,
            expected_release=EXPECTED_RELEASE,
            captured_at=CAPTURED_AT,
        )
