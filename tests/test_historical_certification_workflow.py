from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/historical-backfill.yml")


def test_historical_workflow_publishes_durable_certification_ledger() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "issues: write" in source
    assert 'CERTIFICATION_ISSUE_NUMBER: "208"' in source
    assert "name: Publish running certification state" in source
    assert "name: Publish durable certification ledger" in source
    assert "-f state=pending" in source
    assert "Archive certification" in source
    assert "Canonical CIO replay" in source
    assert "Governed historical learning" in source
    assert "historical-replay/canonical-cio" in source


def test_historical_workflow_reports_calibration_safe_completion_metrics() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for output in (
        "records_written",
        "strict_records",
        "canonical_invoked",
        "blocked_cutoffs",
        "total_cutoffs",
        "relevant_records",
        "price_records",
        "macro_records",
        "archive_scans",
        "runtime_version",
        "learning_observations",
        "cio_decision_observations",
        "qualification_observations",
        "calibration_eligible_observations",
        "governance_only_observations",
        "realized_outcomes",
        "next_cutoff_outcomes",
        "bounded_calibration_outcomes",
        "avoided_losses",
        "missed_opportunities",
        "outcome_alignment",
    ):
        assert f"{output}:" in source

    for field in (
        "archive_scan_count",
        "learning_observation_count",
        "cio_decision_observation_count",
        "qualification_observation_count",
        "calibration_eligible_observation_count",
        "governance_only_observation_count",
        "realized_outcome_count",
        "next_cutoff_outcome_count",
        "bounded_calibration_outcome_count",
        "avoided_loss_count",
        "missed_opportunity_count",
    ):
        assert f'canonical.get("{field}", 0)' in source
    assert 'canonical.get("runtime_version", "unknown")' in source
    assert 'canonical.get("outcome_alignment", "unknown")' in source
    assert "Total governed observations" in source
    assert "Pre-CIO qualification observations" in source
    assert "Calibration-eligible observations" in source
    assert "Governance-only observations excluded from live calibration" in source
    assert "Decision-horizon outcomes" in source
    assert "Next-cutoff monitoring outcomes" in source
    assert "Bounded live-calibration outcomes" in source
    assert "Outcome alignment" in source
    assert "Avoided losses at the decision horizon" in source
    assert "Missed opportunities at the decision horizon" in source
    assert "Research only: **true**" in source
    assert "Execution authorized: **false**" in source
    assert "Real money authorized: **false**" in source
    assert "Performance claims authorized: **false**" in source


def test_canonical_certification_has_no_legacy_shadow_blocker() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "cancel-in-progress: true" in source
    assert "name: Run the production Canonical CIO over historical cutoffs" in source
    assert "Generate legacy strict monthly shadow replay" not in source
    assert "historical-shadow-replay.json" not in source


def test_horizon_aligned_learning_contract_is_in_focused_validation() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    for test_path in (
        "tests/test_canonical_no_action_learning.py",
        "tests/test_horizon_aligned_historical_learning.py",
        "tests/test_historical_replay_ui.py",
    ):
        assert test_path in source
    assert "Capability-policy-only observations remain available for governance review" in source
    assert "decision-horizon-aligned evidence" in source
