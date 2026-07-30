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


def _payload(
    *,
    schema_version: str = "canonical-historical-replay.v5",
    certification_ready: bool = True,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "runtime_version": "single-pass-availability-cursor.v5",
        "generated_at": "2026-07-30T00:00:00Z",
        "start_date": "2016-07-30",
        "end_date": "2026-07-30",
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
        "calibration_eligible_observation_count": 192,
        "governance_only_observation_count": 103,
        "realized_outcome_count": 160,
        "outcome_alignment": "decision_horizon",
        "avoided_loss_count": 75,
        "missed_opportunity_count": 85,
        "macro_coverage_satisfied": certification_ready,
        "certification_ready": certification_ready,
        "required_macro_dataset_count": 3,
        "present_macro_dataset_count": 3 if certification_ready else 2,
        "macro_incomplete_cutoff_count": 0 if certification_ready else 5,
        "macro_excluded_observation_count": 0 if certification_ready else 12,
        "missing_macro_datasets": [] if certification_ready else ["series.vixcls"],
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
                "macro_coverage_complete": certification_ready,
                "candidate_count": 2,
                "decision_count": 0,
                "qualification_rejection_count": 2,
                "learning_observation_count": 2,
                "decisions": [
                    {
                        "action": "insufficient_evidence",
                        "decision_stage": "pre_cio_qualification",
                        "canonical_cio_decision": False,
                        "calibration_eligible": False,
                        "realized_outcome": "avoided_loss",
                    },
                    {
                        "action": "no_superior_opportunity",
                        "decision_stage": "pre_cio_qualification",
                        "canonical_cio_decision": False,
                        "calibration_eligible": True,
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


def test_load_and_summarize_macro_complete_v5_manifest(tmp_path):
    path = tmp_path / "latest-canonical-replay.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    payload = load_canonical_replay_manifest(path)
    assert payload is not None
    summary = canonical_replay_summary(payload)

    assert summary["state"] == "Partially available"
    assert summary["schema_version"] == "canonical-historical-replay.v5"
    assert summary["runtime_version"] == "single-pass-availability-cursor.v5"
    assert summary["invoked_cutoffs"] == 100
    assert summary["blocked_cutoffs"] == 20
    assert summary["learning_observations"] == 295
    assert summary["cio_decision_observations"] == 0
    assert summary["qualification_observations"] == 295
    assert summary["calibration_eligible_observations"] == 192
    assert summary["governance_only_observations"] == 103
    assert summary["realized_outcomes"] == 160
    assert summary["outcome_alignment"] == "decision_horizon"
    assert summary["macro_coverage_satisfied"] is True
    assert summary["certification_ready"] is True
    assert summary["present_macro_dataset_count"] == 3
    assert summary["required_macro_dataset_count"] == 3
    assert summary["macro_incomplete_cutoffs"] == 0
    assert summary["macro_excluded_observations"] == 0
    assert summary["research_only"] is True
    assert summary["execution_authorized"] is False
    assert summary["real_money_authorized"] is False
    assert summary["performance_claims_authorized"] is False


def test_macro_incomplete_v5_manifest_is_visibly_blocked() -> None:
    summary = canonical_replay_summary(_payload(certification_ready=False))

    assert summary["state"] == "Certification blocked"
    assert summary["macro_coverage_satisfied"] is False
    assert summary["certification_ready"] is False
    assert summary["missing_macro_datasets"] == ["series.vixcls"]
    assert summary["macro_incomplete_cutoffs"] == 5
    assert summary["macro_excluded_observations"] == 12


def test_supported_replay_schemas_remain_readable(tmp_path):
    assert "canonical-historical-replay.v5" in SUPPORTED_SCHEMA_VERSIONS
    for schema_version in sorted(SUPPORTED_SCHEMA_VERSIONS):
        path = tmp_path / f"{schema_version}.json"
        path.write_text(
            json.dumps(_payload(schema_version=schema_version)),
            encoding="utf-8",
        )
        assert load_canonical_replay_manifest(path) is not None


def test_cutoff_rows_distinguish_macro_and_governed_observations():
    rows = canonical_replay_cutoff_rows(_payload())

    assert len(rows) == 1
    row = rows[0]
    assert row["Canonical cycle"] == "Invoked"
    assert row["Macro evidence"] == "Complete"
    assert row["CIO decisions"] == 0
    assert row["Pre-CIO outcomes"] == 2
    assert row["Learning observations"] == 2
    assert row["Governance only"] == 1
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
