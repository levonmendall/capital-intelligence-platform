from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from operations import stage_isolated_evidence_pipeline as pipeline
from operations import stage_isolated_prequalification_projection as projection
from scripts import capture_render_production_telemetry_resilient as resilient
from scripts import enrich_stage_isolated_prequalification_telemetry as stage_enrichment


_RELEASE = "a" * 40
_NOW = datetime(2026, 8, 21, 19, 30, tzinfo=timezone.utc)


def _state(tmp_path: Path, *, stage: str = "comprehensive_discovery"):
    return pipeline.StageIsolatedEvidenceState(
        pipeline_id="pipeline-1",
        release=_RELEASE,
        state="running",
        requested_at=_NOW,
        evidence_as_of=_NOW,
        updated_at=_NOW,
        completed_stages=("reference", "comprehensive_structure", "public_live", "us_equity_discovery"),
        current_stage=stage,
        stage_started_at=_NOW,
        reference_manifest_id="reference-1",
        reference_manifest_path=str(tmp_path / "reference.json"),
        generation_id=None,
        error_type=None,
        error_detail=None,
        path=tmp_path / "stage-isolated-evidence-latest.json",
    )


def test_projection_uses_exact_stage_instead_of_legacy_public_live(monkeypatch, tmp_path):
    state = _state(tmp_path)
    monkeypatch.setattr(projection._pipeline, "load_stage_isolated_evidence_state", lambda _values: state)
    monkeypatch.setattr(projection, "_latest_failed_attempt", lambda _values, _current: None)

    result = projection.project_stage_isolated_prequalification(
        {
            "request_kind": "evidence_prequalification",
            "active_release": _RELEASE,
            "prequalification_progress": {"active_phase": "public_live"},
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
        },
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE},
    )

    assert result["prequalification_progress"]["active_phase"] == "comprehensive_discovery"
    assert result["stage_isolated_evidence_progress"]["completed_stage_count"] == 4
    assert result["stage_isolated_evidence_progress"]["required_stage_count"] == 7


def test_projection_retains_previous_retry_failure(monkeypatch, tmp_path):
    state = _state(tmp_path, stage="reference")
    monkeypatch.setattr(projection._pipeline, "load_stage_isolated_evidence_state", lambda _values: state)
    monkeypatch.setattr(
        projection,
        "_latest_failed_attempt",
        lambda _values, _current: {
            "pipeline_id": "pipeline-0",
            "failed_stage": "comprehensive_discovery",
            "error_type": "ResourceBoundaryExceeded",
            "error_detail": "bounded child exceeded governed resource boundary",
            "evidence_as_of": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "completed_stages": ["reference", "comprehensive_structure", "public_live", "us_equity_discovery"],
            "completed_stage_count": 4,
            "credential_safe": True,
            "decision_evidence_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        },
    )

    result = projection.project_stage_isolated_prequalification(
        {
            "request_kind": "evidence_prequalification",
            "active_release": _RELEASE,
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
        },
        values={"CAPITAL_INTELLIGENCE_RELEASE": _RELEASE},
    )

    assert result["prequalification_last_retry_failure_stage"] == "comprehensive_discovery"
    assert result["prequalification_last_retry_failure_error_type"] == "ResourceBoundaryExceeded"


def test_resilient_capture_does_not_fail_active_prequalification(monkeypatch, tmp_path):
    output = tmp_path / "telemetry.json"
    timeline = tmp_path / "timeline.json"
    snapshot = {
        "capture_state": "ok",
        "diagnostic": {
            "release_matches_expected": True,
            "state": "prequalifying",
        },
        "failure_class": "timeout",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    def base_main(_argv):
        output.write_text(json.dumps(snapshot), encoding="utf-8")
        timeline.write_text(json.dumps([snapshot]), encoding="utf-8")
        return resilient._base._EXIT_TIMEOUT

    monkeypatch.setattr(resilient._base, "main", base_main)
    result = resilient.main(
        (
            "--url",
            "https://example.invalid/telemetry",
            "--expected-release",
            _RELEASE,
            "--output",
            str(output),
            "--timeline-output",
            str(timeline),
            "--watch-seconds",
            "2100",
        )
    )

    assert result == 0
    rewritten = json.loads(output.read_text(encoding="utf-8"))
    assert rewritten["failure_class"] == "watch_window_elapsed"
    assert rewritten["watch_window_elapsed"] is True


def test_resilient_capture_preserves_terminal_failure(monkeypatch, tmp_path):
    output = tmp_path / "telemetry.json"
    snapshot = {
        "capture_state": "ok",
        "diagnostic": {
            "release_matches_expected": True,
            "state": "failed",
        },
        "failure_class": "terminal_failure",
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    def base_main(_argv):
        output.write_text(json.dumps(snapshot), encoding="utf-8")
        return resilient._base._EXIT_DIAGNOSTIC_FAILED

    monkeypatch.setattr(resilient._base, "main", base_main)
    result = resilient.main(
        (
            "--url",
            "https://example.invalid/telemetry",
            "--expected-release",
            _RELEASE,
            "--output",
            str(output),
        )
    )
    assert result == resilient._base._EXIT_DIAGNOSTIC_FAILED


def test_stage_enrichment_overrides_false_public_live_phase():
    snapshot = {
        "capture_state": "ok",
        "diagnostic": {
            "release_matches_expected": True,
            "prequalification_progress": {"active_phase": "public_live"},
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }
    public = {
        "active_release": _RELEASE,
        "stage_isolated_evidence_progress": {
            "pipeline_id": "pipeline-1",
            "state": "running",
            "evidence_as_of": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "current_stage": "comprehensive_discovery",
            "next_stage": "comprehensive_discovery",
            "active_stage": "comprehensive_discovery",
            "stage_started_at": _NOW.isoformat(),
            "completed_stages": ["reference", "comprehensive_structure", "public_live", "us_equity_discovery"],
            "completed_stage_count": 4,
            "required_stage_count": 7,
            "error_type": None,
        },
        "prequalification_last_retry_failure": {
            "pipeline_id": "pipeline-0",
            "failed_stage": "us_equity_discovery",
            "error_type": "TimeoutError",
            "evidence_as_of": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
            "completed_stages": ["reference", "comprehensive_structure", "public_live"],
            "completed_stage_count": 3,
        },
        "credential_safe": True,
        "paper_only": True,
        "real_money_authorized": False,
    }

    result = stage_enrichment.enrich_snapshot(snapshot, public, expected_release=_RELEASE)
    diagnostic = result["diagnostic"]
    assert diagnostic["prequalification_progress"]["active_phase"] == "comprehensive_discovery"
    assert diagnostic["prequalification_last_retry_failure_stage"] == "us_equity_discovery"
    assert diagnostic["prequalification_last_retry_failure_error_type"] == "TimeoutError"


def test_render_telemetry_workflow_uses_resilient_stage_projection():
    workflow = Path(".github/workflows/render-production-telemetry.yml").read_text(encoding="utf-8")
    assert "capture_render_production_telemetry_resilient.py" in workflow
    assert "enrich_stage_isolated_prequalification_telemetry.py" in workflow
