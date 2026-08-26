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


def test_exact_spool_reclamation_is_release_scoped_and_non_destructive(
    monkeypatch,
    tmp_path,
):
    data_root = tmp_path / "data"
    release_root = data_root / "comprehensive-discovery-spool" / "release-123"
    request_root = release_root / "epoch" / "request"
    request_root.mkdir(parents=True)
    merged = request_root / "merged-catalog.pkl"
    lane = request_root / "lane.pkl"
    merged.write_bytes(b"merged-cache-pages")
    lane.write_bytes(b"lane-cache-pages")

    other_release = (
        data_root / "comprehensive-discovery-spool" / "other-release" / "epoch" / "request"
    )
    other_release.mkdir(parents=True)
    other_file = other_release / "lane.pkl"
    other_file.write_bytes(b"other-release")
    outside = data_root / "outside.bin"
    outside.write_bytes(b"outside")

    observed: list[object] = []
    monkeypatch.setattr(
        reclamation,
        "_memory_snapshot",
        lambda: (
            {"raw_current_kib": 1800, "inactive_file_kib": 1200}
            if not observed
            else {"raw_current_kib": 1400, "inactive_file_kib": 800}
        ),
    )

    def advise(path):
        observed.append(path)
        return True

    monkeypatch.setattr(reclamation, "_advise_clean_file_cache_dontneed", advise)
    report = reclamation._release_current_release_spool_file_cache(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(data_root),
            "CAPITAL_INTELLIGENCE_RELEASE": "release-123",
        }
    )

    assert set(observed) == {merged, lane}
    assert other_file not in observed
    assert outside not in observed
    assert report["candidate_file_count"] == 2
    assert report["released_file_count"] == 2
    assert report["released_bytes"] == len(b"merged-cache-pages") + len(b"lane-cache-pages")
    assert report["raw_current_reclaimed_kib"] == 400
    assert report["inactive_file_reclaimed_kib"] == 400
    assert merged.read_bytes() == b"merged-cache-pages"
    assert lane.read_bytes() == b"lane-cache-pages"
    assert other_file.read_bytes() == b"other-release"
    assert outside.read_bytes() == b"outside"
    assert report["evidence_certified"] is False
    assert report["decision_authority"] is False


def test_exact_spool_reclamation_precedes_broad_helper(monkeypatch):
    events: list[str] = []

    def exact(values):
        events.append("exact")
        return {
            "candidate_file_count": 2,
            "candidate_bytes": 200,
            "released_file_count": 2,
            "released_bytes": 200,
            "scan_truncated": False,
            "raw_current_reclaimed_kib": 256,
            "inactive_file_reclaimed_kib": 256,
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

    def broad(*args, **kwargs):
        events.append("broad")
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_valid_report(), sort_keys=True),
        )

    monkeypatch.setattr(reclamation, "_release_current_release_spool_file_cache", exact)
    monkeypatch.setattr(reclamation.subprocess, "run", broad)

    payload = reclamation.run_post_lane_cache_reclamation(
        {"RENDER": "true", "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS": "1"},
        node_id="comprehensive-lane:fixed_income",
        asset_class="fixed_income",
    )

    assert events == ["exact", "broad"]
    assert payload["exact_spool_released_bytes"] == 200
    assert payload["exact_spool_raw_current_reclaimed_kib"] == 256
    assert payload["cache_ownership"] == _valid_report()
    assert payload["evidence_certified"] is False
