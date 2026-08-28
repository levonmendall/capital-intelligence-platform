from __future__ import annotations

import json
import subprocess

from operations import publication_lane_cache_reclamation as reclamation


def test_publication_lane_reclaimer_runs_streaming_helper(monkeypatch) -> None:
    assert "release_streaming_clean_file_cache" in reclamation._CODE
    report = {
        "schema_version": "pre-comprehensive-cache-reclamation.v1",
        "status": "completed",
        "streaming_release": True,
        "supported": True,
        "candidate_file_count": 10_824,
        "candidate_bytes": 3_195_383_808,
        "selected_file_count": 10_824,
        "selected_bytes": 3_195_383_808,
        "released_file_count": 10_824,
        "released_bytes": 900 * 1024 * 1024,
        "scan_entries": 11_000,
        "scan_truncated": False,
        "reclaim_truncated": False,
        "raw_current_reclaimed_kib": 131_360,
        "inactive_file_reclaimed_kib": 130_000,
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
    monkeypatch.setattr(
        reclamation.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(report),
            stderr="",
        ),
    )

    payload = reclamation.run_publication_lane_cache_reclamation(
        {"RENDER": "true"},
        asset_class="fixed_income",
        index=3,
    )

    assert payload["status"] == "completed"
    assert payload["streaming_release"] is True
    assert payload["raw_current_reclaimed_kib"] == 131_360
    assert payload["evidence_certified"] is False
    assert payload["decision_authority"] is False
    assert payload["real_money_authorized"] is False
