from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from operations import post_lane_cache_reclamation as reclamation


def _valid_report() -> dict[str, object]:
    return {
        "schema_version": "pre-comprehensive-cache-reclamation.v1",
        "status": "completed",
        "candidate_file_count": 10,
        "candidate_bytes": 1000,
        "selected_file_count": 8,
        "selected_bytes": 800,
        "released_file_count": 7,
        "released_bytes": 700,
        "scan_truncated": False,
        "manifest_truncated": False,
        "raw_current_reclaimed_kib": 128,
        "inactive_file_reclaimed_kib": 96,
        "advisory_only": True,
        "evidence_certified": False,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
        "credential_safe": True,
    }


def test_post_lane_reclamation_skips_outside_serialized_render(monkeypatch):
    def forbidden_run(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("reclaimer subprocess must not launch")

    monkeypatch.setattr(reclamation.subprocess, "run", forbidden_run)
    payload = reclamation.run_post_lane_cache_reclamation(
        {"RENDER": "false", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        node_id="deep-market-evidence:equity",
        asset_class="equity",
    )

    assert payload["status"] == "skipped"
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False


def test_post_lane_reclamation_reports_exact_owner_release(monkeypatch):
    report = _valid_report()
    monkeypatch.setattr(
        reclamation.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(report, sort_keys=True),
        ),
    )

    payload = reclamation.run_post_lane_cache_reclamation(
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        node_id="deep-market-evidence:international_equity",
        asset_class="international_equity",
    )

    assert payload["status"] == "completed"
    assert payload["released_bytes"] == 700
    assert payload["inactive_file_reclaimed_kib"] == 96
    assert payload["cache_ownership"] == report
    assert payload["evidence_certified"] is False


def test_post_lane_reclamation_timeout_is_advisory(monkeypatch):
    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=("python", "-c"), timeout=10.0)

    monkeypatch.setattr(reclamation.subprocess, "run", timed_out)
    payload = reclamation.run_post_lane_cache_reclamation(
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        node_id="deep-market-evidence:fx",
        asset_class="fx",
    )

    assert payload["status"] == "timed_out"
    assert payload["error_type"] == "CacheReclamationTimeout"
    assert payload["advisory_only"] is True
    assert payload["evidence_certified"] is False


def test_post_lane_reclamation_rejects_authoritative_report(monkeypatch):
    report = _valid_report()
    report["evidence_certified"] = True
    monkeypatch.setattr(
        reclamation.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(report, sort_keys=True),
        ),
    )

    payload = reclamation.run_post_lane_cache_reclamation(
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        node_id="deep-market-evidence:futures",
        asset_class="futures",
    )

    assert payload["status"] == "invalid_report"
    assert payload["error_type"] == "CacheReclamationReportError"
    assert "cache_ownership" not in payload
    assert payload["evidence_certified"] is False
