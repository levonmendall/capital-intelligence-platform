from __future__ import annotations

import json
from pathlib import Path

from historical_replay_ui import (
    SUPPORTED_SCHEMA_VERSIONS,
    canonical_replay_cutoff_rows,
    canonical_replay_manifest_path,
    canonical_replay_summary,
    load_canonical_replay_manifest,
)


def _payload(*, schema_version: str = "canonical-historical-replay.v3") -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_version": "single-pass-availability-cursor.v3",
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
        "learning_observation_count": 295,
        "cio_decision_observation_count": 0,
        "qualification_observation_count": 295,
        "realized_outcome_count": 292,
        "avoided_loss_count": 138,
        "missed_opportunity_count": 154,
        "execution_authorized": False,
        "paper_execution_authorized": False,
        "real_money_authorized": False,
        "policy_promotion_authorized": False,
        "performance_claims_authorized": False,
        "decisions": [
            {
                "cutoff": "2020-01-31T23:59:59Z",
                "state": "completed",
                "canonical_cio_invoked": True,
                "candidate_count": 2,
                "decision_count": 0,
                "qualification_rejection_count": 2,
                "learning_observation_count": 2,
                "decisions": [
                    {
                        "action": "insufficient_evidence",
                        "decision_stage": "pre_cio_qualification",
                        "canonical_cio_decision": False,
                        "realized_outcome": "avoided_loss",
                    },
                    {
                        "action": "no_superior_opportunity",
                        "decision_stage": "pre_cio_qualification",
                        "canonical_cio_decision": False,
                        "realized_outcome": "missed_opportunity",
                    },
                ],
                "construction": None,
            }
        ],
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


def test_load_and_summarize_canonical_replay_manifest_v3(tmp_path):
    path = tmp_path / "latest-canonical-replay.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    payload = load_canonical_replay_manifest(path)
    assert payload is not None
    summary = canonical_replay_summary(payload)

    assert summary["state"] == "Partially available"
    assert summary["schema_version"] == "canonical-historical-replay.v3"
    assert summary["runtime_version"] == "single-pass-availability-cursor.v3"
    assert summary["invoked_cutoffs"] == 100
    assert summary["blocked_cutoffs"] == 20
    assert summary["learning_observations"] == 295
    assert summary["cio_decision_observations"] == 0
    assert summary["qualification_observations"] == 295
    assert summary["realized_outcomes"] == 292
    assert summary["avoided_losses"] == 138
    assert summary["missed_opportunities"] == 154
    assert summary["research_only"] is True
    assert summary["execution_authorized"] is False
    assert summary["real_money_authorized"] is False
    assert summary["performance_claims_authorized"] is False


def test_supported_replay_schemas_remain_readable(tmp_path):
    for schema_version in sorted(SUPPORTED_SCHEMA_VERSIONS):
        path = tmp_path / f"{schema_version}.json"
        path.write_text(
            json.dumps(_payload(schema_version=schema_version)),
            encoding="utf-8",
        )
        assert load_canonical_replay_manifest(path) is not None


def test_cutoff_rows_distinguish_cio_and_pre_cio_observations():
    rows = canonical_replay_cutoff_rows(_payload())

    assert len(rows) == 1
    row = rows[0]
    assert row["Canonical cycle"] == "Invoked"
    assert row["CIO decisions"] == 0
    assert row["Pre-CIO outcomes"] == 2
    assert row["Learning observations"] == 2
    assert row["Avoided losses"] == 1
    assert row["Missed opportunities"] == 1
    assert "Insufficient Evidence × 1" in row["Actions / outcomes"]
    assert "No Superior Opportunity × 1" in row["Actions / outcomes"]


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
