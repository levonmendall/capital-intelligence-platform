from __future__ import annotations

import json
from pathlib import Path

from historical_replay_ui import (
    canonical_replay_manifest_path,
    canonical_replay_summary,
    load_canonical_replay_manifest,
)


def _payload() -> dict[str, object]:
    return {
        "schema_version": "canonical-historical-replay.v1",
        "generated_at": "2026-07-29T19:00:00Z",
        "start_date": "2016-07-29",
        "end_date": "2026-07-29",
        "cadence": "monthly",
        "strict_replay": False,
        "research_only": True,
        "canonical_cio_available": True,
        "canonical_cio_invoked_count": 100,
        "blocked_cutoff_count": 20,
        "decision_cutoff_count": 120,
        "execution_authorized": False,
        "paper_execution_authorized": False,
        "real_money_authorized": False,
        "policy_promotion_authorized": False,
        "performance_claims_authorized": False,
        "decisions": [],
    }


def test_manifest_path_uses_persistent_historical_root(tmp_path):
    path = canonical_replay_manifest_path(
        {
            "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        }
    )
    assert path == (
        tmp_path
        / "historical_replay"
        / "manifests"
        / "latest-canonical-replay.json"
    )


def test_load_and_summarize_canonical_replay_manifest(tmp_path):
    path = tmp_path / "latest-canonical-replay.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    payload = load_canonical_replay_manifest(path)
    assert payload is not None
    summary = canonical_replay_summary(payload)

    assert summary["state"] == "Partially available"
    assert summary["invoked_cutoffs"] == 100
    assert summary["blocked_cutoffs"] == 20
    assert summary["research_only"] is True
    assert summary["execution_authorized"] is False
    assert summary["real_money_authorized"] is False
    assert summary["performance_claims_authorized"] is False


def test_invalid_or_unrecognized_manifest_is_not_displayed(tmp_path):
    missing = tmp_path / "missing.json"
    assert load_canonical_replay_manifest(missing) is None

    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    assert load_canonical_replay_manifest(invalid) is None

    wrong_schema = tmp_path / "wrong.json"
    wrong_schema.write_text(
        json.dumps({"schema_version": "unknown"}),
        encoding="utf-8",
    )
    assert load_canonical_replay_manifest(wrong_schema) is None


def test_history_archive_calls_historical_learning_surface():
    source = Path("cio_report_history_ui.py").read_text(encoding="utf-8")
    assert "from historical_replay_ui import render_canonical_historical_replay" in source
    assert "render_canonical_historical_replay()" in source
