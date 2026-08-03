"""Research-only gate contribution attribution tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from cio import CIOAction
from evaluation import (
    GateContributionAnalyzer,
    GateContributionEffect,
    GateContributionStage,
    PointInTimeDecisionEvaluator,
)
from tests.test_point_in_time_evaluation import AS_OF, _cycle, _realized


def _metric(report, stage: GateContributionStage):
    return next(item for item in report.metrics if item.stage is stage)


def test_exact_gate_components_reconcile_to_existing_evaluation(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(snapshot),
    )

    report = GateContributionAnalyzer().analyze(
        ((snapshot, evaluation),),
        as_of=AS_OF + timedelta(days=367),
    )

    assert report.total_net_active_contribution == pytest.approx(
        evaluation.attribution.net_active_contribution
    )
    assert report.reconciled_exact_contribution == pytest.approx(
        evaluation.attribution.selection
        + evaluation.attribution.sizing
        + evaluation.attribution.timing
        + evaluation.attribution.implementation_cost
    )
    assert _metric(
        report,
        GateContributionStage.CIO_SELECTION,
    ).exact_portfolio_contribution == pytest.approx(
        evaluation.attribution.selection
    )
    assert report.research_only
    assert not report.automatic_policy_change
    assert not report.execution_authority


def test_construction_reduction_is_costly_when_reduced_candidate_outperforms(
    tmp_path,
) -> None:
    _, _, result = _cycle(tmp_path)
    original = result.evaluation_snapshots[0]
    snapshot = replace(
        original,
        identifier="evaluation-snapshot:construction-reduction",
        decision_identifier="decision:construction-reduction",
        recommended_position_weight=0.10,
        implemented_position_weight=0.05,
    )
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        replace(
            _realized(snapshot, candidate_return=0.20, implementation_return=0.18),
            snapshot_identifier=snapshot.identifier,
        ),
    )

    report = GateContributionAnalyzer().analyze(
        ((snapshot, evaluation),),
        as_of=AS_OF + timedelta(days=367),
    )
    sizing = _metric(report, GateContributionStage.CONSTRUCTION_SIZING)

    assert sizing.destroyed_value_count == 1
    assert sizing.exact_portfolio_contribution < 0.0
    assert sizing.constrained_weight == pytest.approx(0.05)


def test_evidence_veto_distinguishes_protection_from_missed_opportunity(
    tmp_path,
) -> None:
    _, _, result = _cycle(tmp_path)
    original = result.evaluation_snapshots[0]
    protected_snapshot = replace(
        original,
        identifier="evaluation-snapshot:veto-protected",
        decision_identifier="decision:veto-protected",
        action=CIOAction.INSUFFICIENT_EVIDENCE,
        recommended_position_weight=None,
        implemented_position_weight=0.0,
        evidence_vetoes=("Applicable valuation evidence was incomplete",),
    )
    costly_snapshot = replace(
        protected_snapshot,
        identifier="evaluation-snapshot:veto-costly",
        decision_identifier="decision:veto-costly",
    )
    protected = PointInTimeDecisionEvaluator().evaluate(
        protected_snapshot,
        replace(
            _realized(
                protected_snapshot,
                candidate_return=-0.10,
                implementation_return=-0.10,
            ),
            snapshot_identifier=protected_snapshot.identifier,
        ),
    )
    costly = PointInTimeDecisionEvaluator().evaluate(
        costly_snapshot,
        replace(
            _realized(
                costly_snapshot,
                candidate_return=0.20,
                implementation_return=0.20,
            ),
            snapshot_identifier=costly_snapshot.identifier,
        ),
    )

    report = GateContributionAnalyzer().analyze(
        (
            (protected_snapshot, protected),
            (costly_snapshot, costly),
        ),
        as_of=AS_OF + timedelta(days=367),
    )
    veto = _metric(report, GateContributionStage.EVIDENCE_VETO)
    abstention = _metric(report, GateContributionStage.CIO_ABSTENTION)

    assert veto.activation_count == 2
    assert veto.protected_count == 1
    assert veto.costly_count == 1
    assert abstention.protected_count == 1
    assert abstention.costly_count == 1
    assert {
        item.effect
        for item in report.observations
        if item.stage is GateContributionStage.EVIDENCE_VETO
    } == {
        GateContributionEffect.PROTECTED_CAPITAL,
        GateContributionEffect.COSTLY_RESTRAINT,
    }


def test_gate_contribution_rejects_duplicate_decision_history(tmp_path) -> None:
    _, _, result = _cycle(tmp_path)
    snapshot = result.evaluation_snapshots[0]
    evaluation = PointInTimeDecisionEvaluator().evaluate(
        snapshot,
        _realized(snapshot),
    )

    with pytest.raises(ValueError, match="each decision may appear only once"):
        GateContributionAnalyzer().analyze(
            (
                (snapshot, evaluation),
                (snapshot, evaluation),
            ),
            as_of=AS_OF + timedelta(days=367),
        )
