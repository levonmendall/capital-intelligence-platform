from __future__ import annotations

import json

from scripts import capture_render_production_telemetry as telemetry


def _terminal_payload(limitations: list[object]) -> dict[str, object]:
    return {
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "active_release": "release-current",
        "release_matches": True,
        "state": "failed",
        "ready": False,
        "requested_at": "2026-08-29T17:00:00+00:00",
        "completed_at": "2026-08-29T17:20:00+00:00",
        "comprehensive_discovery_required": True,
        "comprehensive_discovery_complete": True,
        "scheduled_market_coverage_complete": True,
        "terminal_screening_complete": True,
        "all_market_evaluation_complete": False,
        "comprehensive_discovery_limitations": limitations,
    }


def test_terminal_attempt_exposes_only_stable_limitation_types() -> None:
    snapshot = telemetry.build_snapshot(
        _terminal_payload(
            [
                {"type": "provider_failure", "detail": "private provider response"},
                {"type": "coverage_failure", "detail": "private coverage detail"},
                {"type": "provider_failure", "detail": "duplicate private detail"},
            ]
        ),
        expected_release="release-current",
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["limitation_count"] == 3
    assert diagnostic["limitation_scope"] == "current_terminal_attempt"
    assert diagnostic["limitation_types"] == ["coverage_failure", "provider_failure"]
    encoded = json.dumps(snapshot)
    assert "private provider response" not in encoded
    assert "private coverage detail" not in encoded
    assert "duplicate private detail" not in encoded


def test_free_form_or_invalid_limitation_identity_is_never_forwarded() -> None:
    raw_secret = "provider failed authorization=Bearer-should-never-leak"
    snapshot = telemetry.build_snapshot(
        _terminal_payload(
            [
                raw_secret,
                {"type": raw_secret, "message": "another private message"},
                {"message": "missing stable type"},
            ]
        ),
        expected_release="release-current",
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["limitation_count"] == 3
    assert diagnostic["limitation_types"] == ["unclassified_limitation"]
    encoded = json.dumps(snapshot)
    assert raw_secret not in encoded
    assert "another private message" not in encoded
    assert "missing stable type" not in encoded


def test_active_attempt_suppresses_limitation_identity_with_count() -> None:
    payload = _terminal_payload([{"type": "historical_failure"}])
    payload["state"] = "in_progress"
    payload["completed_at"] = None

    snapshot = telemetry.build_snapshot(payload, expected_release="release-current")

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["limitation_count"] == 0
    assert diagnostic["limitation_scope"] == "suppressed_while_active"
    assert diagnostic["limitation_types"] == []
    assert "historical_failure" not in json.dumps(snapshot)


def test_limitation_type_output_is_bounded_without_changing_exact_count() -> None:
    limitations = [{"type": f"limitation_{index:02d}"} for index in range(40)]

    snapshot = telemetry.build_snapshot(
        _terminal_payload(limitations),
        expected_release="release-current",
    )

    diagnostic = snapshot["diagnostic"]
    assert isinstance(diagnostic, dict)
    assert diagnostic["limitation_count"] == 40
    assert len(diagnostic["limitation_types"]) == telemetry._MAX_LIMITATION_TYPES
    assert diagnostic["limitation_types"] == sorted(diagnostic["limitation_types"])
