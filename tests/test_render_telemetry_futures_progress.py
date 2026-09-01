from __future__ import annotations

from scripts.enrich_render_production_telemetry import enrich_snapshot


def test_render_telemetry_preserves_granular_futures_certification_dag() -> None:
    snapshot = {
        "diagnostic": {
            "diagnostic_id": "prequal-futures",
            "progress_metrics": {},
        }
    }
    futures_progress = {
        "state": "incomplete",
        "updated_at": "2026-08-18T02:24:45+00:00",
        "cutoff": "2026-08-18T02:22:00+00:00",
        "required_root_count": 2,
        "qualified_root_count": 1,
        "unresolved_root_count": 1,
        "required_roots": ["ES", "CL"],
        "qualified_roots": ["ES"],
        "unresolved_roots": ["CL"],
        "active_unit": None,
        "active_units": ["massive-root-CL"],
        "fallback_max_workers": 3,
        "unit_timeout_seconds": 45.0,
        "blocking_unit": "massive-root-CL",
        "blocking_provider": "massive",
        "blocking_venue": "NYMEX",
        "blocking_root": "CL",
        "blocking_failure_type": "timeout",
        "nodes": [
            {
                "root": "ES",
                "state": "qualified",
                "unit": "cme-venue-cme",
                "provider": "cme_fprf",
                "venue": "CME",
                "failure_type": None,
                "duration_ms": 1200,
                "fallback": False,
            },
            {
                "root": "CL",
                "state": "timed-out",
                "unit": "massive-root-CL",
                "provider": "massive",
                "venue": "NYMEX",
                "failure_type": "timeout",
                "duration_ms": 45000,
                "fallback": True,
                "provider_error_type": "MassiveMultiAssetError",
                "http_status": 429,
                "retryable": True,
            },
        ],
        "units": [
            {
                "unit": "massive-root-CL",
                "provider": "massive",
                "state": "timed-out",
                "venue": "NYMEX",
                "root": "CL",
                "roots": ["CL"],
                "duration_ms": 45000,
                "failure_type": "timeout",
                "fallback": True,
                "provider_error_type": "MassiveMultiAssetError",
                "http_status": 429,
                "retryable": True,
            }
        ],
        "credential_safe": True,
        "decision_evidence_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    public_payload = {
        "active_release": "release-futures",
        "request_id": "prequal-futures",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
        "progress_metrics": {},
        "futures_reference_progress": futures_progress,
        "prequalification_progress": {
            "active_phase": "reference",
            "futures_reference": futures_progress,
        },
        "prequalification_failure_unit": "massive-root-CL",
        "prequalification_failure_venue": "NYMEX",
        "prequalification_failure_root": "CL",
        "prequalification_unresolved_futures_roots": ["CL"],
    }

    enriched = enrich_snapshot(
        snapshot,
        public_payload,
        expected_release="release-futures",
    )

    diagnostic = enriched["diagnostic"]
    assert isinstance(diagnostic, dict)
    progress = diagnostic["futures_reference_progress"]
    assert isinstance(progress, dict)
    assert progress["qualified_root_count"] == 1
    assert progress["unresolved_root_count"] == 1
    assert progress["blocking_unit"] == "massive-root-CL"
    assert progress["blocking_provider"] == "massive"
    assert progress["blocking_venue"] == "NYMEX"
    assert progress["blocking_root"] == "CL"
    assert progress["blocking_failure_type"] == "timeout"
    assert progress["active_units"] == ["massive-root-CL"]
    assert progress["fallback_max_workers"] == 3
    assert progress["nodes"][1]["provider_error_type"] == "MassiveMultiAssetError"
    assert progress["nodes"][1]["http_status"] == 429
    assert progress["nodes"][1]["retryable"] is True
    assert progress["nodes"][1]["state"] == "timed-out"
    assert diagnostic["prequalification_failure_unit"] == "massive-root-CL"
    assert diagnostic["prequalification_failure_venue"] == "NYMEX"
    assert diagnostic["prequalification_failure_root"] == "CL"
    assert diagnostic["prequalification_unresolved_futures_roots"] == ["CL"]
    prequalification = diagnostic["prequalification_progress"]
    assert isinstance(prequalification, dict)
    assert prequalification["futures_reference"]["blocking_root"] == "CL"
    assert enriched["enriched_from_public_diagnostic"] is True
