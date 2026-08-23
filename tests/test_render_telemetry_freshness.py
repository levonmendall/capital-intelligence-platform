from __future__ import annotations

from scripts.validate_render_telemetry_freshness import verify_snapshot_freshness


def test_timestamp_derived_age_rejects_stale_snapshot_with_fresh_source_age() -> None:
    snapshot = {
        "captured_at": "2026-08-23T19:35:27+00:00",
        "diagnostic": {
            "requested_at": "2026-08-23T16:31:27+00:00",
            "completed_at": "2026-08-23T16:36:07+00:00",
            "diagnostic_age_seconds": 313.65,
            "terminal_age_seconds": 3.13,
        },
    }
    annotated, valid = verify_snapshot_freshness(snapshot)
    assert valid is False
    assert annotated["freshness_integrity_valid"] is False
    assert annotated["failure_class"] == "telemetry_freshness_invalid"
    diagnostic = annotated["diagnostic"]
    assert diagnostic["captured_at_derived_diagnostic_age_seconds"] > 10_000
    assert diagnostic["captured_at_derived_terminal_age_seconds"] > 10_000


def test_timestamp_derived_age_accepts_consistent_snapshot() -> None:
    snapshot = {
        "captured_at": "2026-08-23T19:35:27+00:00",
        "diagnostic": {
            "requested_at": "2026-08-23T19:30:27+00:00",
            "completed_at": "2026-08-23T19:35:24+00:00",
            "diagnostic_age_seconds": 300.0,
            "terminal_age_seconds": 3.0,
        },
    }
    annotated, valid = verify_snapshot_freshness(snapshot)
    assert valid is True
    assert annotated["freshness_integrity_valid"] is True
    assert annotated["freshness_integrity_reason"] is None
