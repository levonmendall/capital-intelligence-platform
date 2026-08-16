from __future__ import annotations

from datetime import datetime, timezone

import pytest

from operations.layered_readiness import compose_layered_readiness


def test_all_layers_ready_and_paper_only() -> None:
    report = compose_layered_readiness(
        serving_ready=True,
        evidence_ready=True,
        decision_ready=True,
        execution_ready=True,
        generated_at=datetime(2026, 8, 15, 23, 0, tzinfo=timezone.utc),
    )

    payload = report.to_dict()
    assert payload["layers"]["serving"]["ready"] is True
    assert payload["layers"]["evidence"]["ready"] is True
    assert payload["layers"]["decision"]["ready"] is True
    assert payload["layers"]["execution"]["ready"] is True
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    assert payload["downstream_repair_authorized"] is False


def test_evidence_block_forces_decision_and_execution_closed() -> None:
    report = compose_layered_readiness(
        serving_ready=True,
        evidence_ready=False,
        decision_ready=True,
        execution_ready=True,
        evidence_blockers=("global_snapshot_stale",),
    )

    assert report.serving.ready is True
    assert report.evidence.ready is False
    assert report.decision.ready is False
    assert "evidence_not_ready" in report.decision.blockers
    assert report.execution.ready is False
    assert "decision_not_ready" in report.execution.blockers


def test_serving_block_forces_every_downstream_layer_closed() -> None:
    report = compose_layered_readiness(
        serving_ready=False,
        evidence_ready=True,
        decision_ready=True,
        execution_ready=True,
        serving_blockers=("canonical_portfolio_unreadable",),
    )

    assert report.serving.ready is False
    assert report.evidence.ready is False
    assert "serving_not_ready" in report.evidence.blockers
    assert report.decision.ready is False
    assert report.execution.ready is False


def test_execution_cannot_be_ready_without_decision_ready() -> None:
    report = compose_layered_readiness(
        serving_ready=True,
        evidence_ready=True,
        decision_ready=False,
        execution_ready=True,
        decision_blockers=("reconciliation_not_ready",),
    )

    assert report.decision.ready is False
    assert report.execution.ready is False
    assert "decision_not_ready" in report.execution.blockers


def test_blockers_are_stable_and_deduplicated() -> None:
    report = compose_layered_readiness(
        serving_ready=True,
        evidence_ready=False,
        decision_ready=False,
        execution_ready=False,
        evidence_blockers=("stale", "stale"),
    )

    assert report.evidence.blockers == ("stale",)
    assert report.decision.blockers.count("evidence_not_ready") == 1


def test_generated_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        compose_layered_readiness(
            serving_ready=True,
            evidence_ready=True,
            decision_ready=True,
            execution_ready=True,
            generated_at=datetime(2026, 8, 15, 23, 0),
        )
