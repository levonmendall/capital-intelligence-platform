"""Paper-operation evidence command-line contract tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from evaluation import PaperOperationObservation, SQLitePaperOperationEvidenceStore
from run_paper_operation_review import main

UTC = timezone.utc


def _payload(identifier: str, day: int, regime: str) -> dict:
    start = datetime(2026, 7, day, tzinfo=UTC)
    return PaperOperationObservation(
        identifier=identifier,
        period_start=start,
        period_end=start + timedelta(hours=23),
        observed_at=start + timedelta(days=1),
        regime=regime,
        expected_full_universe_cycles=1,
        completed_full_universe_cycles=1,
        decision_count=2,
        action_decision_count=1,
        abstention_decision_count=1,
        evaluations_due=2,
        evaluations_completed=2,
        confidence_sample_count=2,
        brier_score_sum=0.2,
        calibration_absolute_error_sum=0.08,
        paper_execution_batches=1,
        paper_execution_completed=1,
        paper_execution_reconciled=1,
        paper_execution_failed=0,
        turnover=0.05,
        transaction_cost_return=0.0002,
        thesis_reviews_due=2,
        thesis_reviews_completed=2,
        theses_strengthening=1,
        theses_stable=1,
        theses_weakening=0,
        theses_invalidated=0,
        alerts_generated=1,
        alerts_sent=1,
        alerts_suppressed=0,
        alerts_acknowledged=1,
        alerts_useful=1,
        alerts_false_positive=0,
        portfolio_return=0.001,
        benchmark_return=0.001,
        cash_return=0.0001,
        passive_return=0.0008,
        evidence_identifiers=(f"journal:{day}",),
    ).to_dict()


def test_cli_records_observations_and_report_without_live_authority(tmp_path, capsys) -> None:
    observation_path = tmp_path / "observations.json"
    observation_path.write_text(
        json.dumps([_payload("obs:1", 1, "expansion"), _payload("obs:2", 2, "contraction")]),
        encoding="utf-8",
    )
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "minimum_observation_days": 2,
                "minimum_distinct_regimes": 2,
                "minimum_completed_cycles": 2,
                "minimum_decisions": 4,
                "minimum_confidence_samples": 4,
                "minimum_paper_execution_batches": 2,
                "minimum_alert_feedback_samples": 2,
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "evidence.db"
    result = main(
        [
            "--database", str(database),
            "--observation", str(observation_path),
            "--policy", str(policy_path),
            "--evaluated-at", "2026-07-04T00:00:00+00:00",
            "--record-report",
            "--require-governance-ready",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "ready_for_governance_review"
    assert payload["real_money_authorized"] is False
    assert payload["performance_claims_permitted"] is False
    store = SQLitePaperOperationEvidenceStore(database, initialize=False)
    assert len(store.observations()) == 2
    assert store.latest_report() is not None


def test_cli_fails_closed_when_evidence_is_not_ready(tmp_path, capsys) -> None:
    observation_path = tmp_path / "observation.json"
    observation_path.write_text(json.dumps(_payload("obs:1", 1, "expansion")), encoding="utf-8")
    result = main(
        [
            "--database", str(tmp_path / "evidence.db"),
            "--observation", str(observation_path),
            "--evaluated-at", "2026-07-03T00:00:00+00:00",
            "--require-governance-ready",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 3
    assert payload["status"] == "insufficient_evidence"
