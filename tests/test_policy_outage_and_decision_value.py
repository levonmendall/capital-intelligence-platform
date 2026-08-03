from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from application.cio_cycle import CanonicalCIOCycle
from cio import CIOAction, PriorDecisionContext, ThesisState
from cio.evidence_outage import (
    EvidenceOutageAuthority,
    EvidenceOutageDisposition,
)
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from evaluation.decision_value import AdvisoryDecisionValueEvaluator
from evaluation.point_in_time import (
    DecisionEvidenceSnapshot,
    EvaluationOutcome,
    PointInTimeDecisionEvaluation,
)
from tests.test_canonical_cio_cycle import _candidate


def _prior(candidate, *, days_ago: int, substitute: bool = False, custody=True, lifecycle=True):
    timestamp = candidate.as_of - timedelta(days=days_ago)
    return PriorDecisionContext(
        candidate_identifier=candidate.identifier,
        prior_decision_identifier="decision:prior",
        prior_action=CIOAction.HOLD,
        prior_target_weight=candidate.current_portfolio_weight,
        decided_at=timestamp,
        thesis_state=ThesisState.ACTIVE,
        last_complete_evidence_at=timestamp,
        operational_outage_started_at=timestamp,
        independent_substitute_evidence_available=substitute,
        custody_settlement_observable=custody,
        lifecycle_observable=lifecycle,
    )


def test_policy_authority_fingerprint_is_stable_and_shared_by_cycle() -> None:
    first = CanonicalDecisionPolicyAuthority()
    second = CanonicalDecisionPolicyAuthority()
    cycle = CanonicalCIOCycle(policy_authority=first)

    assert first.fingerprint == second.fingerprint
    assert first.identifier == second.identifier
    assert cycle.policy_authority.fingerprint == first.fingerprint
    assert cycle.opportunity_engine.policy_authority.fingerprint == first.fingerprint
    assert cycle.cio.policy_authority.fingerprint == first.fingerprint


def test_operational_outage_holds_then_reduces_after_asset_specific_limit() -> None:
    candidate = replace(_candidate("OUTAGE"), current_portfolio_weight=0.08)
    authority = EvidenceOutageAuthority()

    short = authority.assess(
        candidate,
        _prior(candidate, days_ago=1),
        operational_only_veto=True,
    )
    stale = authority.assess(
        candidate,
        _prior(candidate, days_ago=8),
        operational_only_veto=True,
    )

    assert short.disposition is EvidenceOutageDisposition.HOLD_WITH_DECAY
    assert short.confidence_ceiling < 1.0
    assert stale.disposition is EvidenceOutageDisposition.REDUCE
    assert stale.requires_reduction


def test_independent_substitute_evidence_extends_bounded_outage_window() -> None:
    candidate = replace(_candidate("SUBSTITUTE"), current_portfolio_weight=0.08)
    authority = EvidenceOutageAuthority()

    without_substitute = authority.assess(
        candidate,
        _prior(candidate, days_ago=8),
        operational_only_veto=True,
    )
    with_substitute = authority.assess(
        candidate,
        _prior(candidate, days_ago=8, substitute=True),
        operational_only_veto=True,
    )

    assert without_substitute.requires_reduction
    assert with_substitute.disposition is EvidenceOutageDisposition.HOLD_WITH_DECAY
    assert with_substitute.maximum_tolerable_days > without_substitute.maximum_tolerable_days


def test_lost_custody_or_lifecycle_observability_requires_immediate_reduction() -> None:
    candidate = replace(_candidate("CUSTODY"), current_portfolio_weight=0.08)

    assessment = EvidenceOutageAuthority().assess(
        candidate,
        _prior(candidate, days_ago=0, custody=False),
        operational_only_veto=True,
    )

    assert assessment.disposition is EvidenceOutageDisposition.EMERGENCY_REDUCE
    assert assessment.requires_reduction
    assert "custody" in assessment.reason.lower()


def _snapshot(identifier: str, *, action: CIOAction, veto=False, block=False, hysteresis=False):
    candidate = _candidate(identifier.upper())
    return DecisionEvidenceSnapshot(
        identifier=f"snapshot:{identifier}",
        decision_identifier=f"decision:{identifier}",
        candidate_identifier=candidate.identifier,
        instrument_symbol=candidate.instrument.symbol,
        decision_at=candidate.as_of,
        decision_horizon_days=30,
        review_at=candidate.as_of + timedelta(days=30),
        action=action,
        expected_return=0.10,
        expected_downside=-0.15,
        final_confidence=0.70,
        effective_opportunity_cost=0.04,
        original_best_alternative_identifier="cash",
        original_best_alternative_kind="cash",
        original_best_alternative_expected_return=0.04,
        opportunity_context_identifier="opportunity:test",
        analysis_lane="acquisition",
        resolved_policy_profile="policy:test",
        policy_matrix_version="matrix:test",
        recommended_position_weight=(0.05 if action in {CIOAction.BUY, CIOAction.INCREASE} else None),
        implementation_cost_return=0.001,
        evidence_identifiers=("evidence:test",),
        model_versions=("model:test",),
        evidence_vetoes=(("missing evidence",) if veto else ()),
        implementation_blocks=(("liquidity block",) if block else ()),
        hysteresis_applied=hysteresis,
        reconciled_outcomes=(),
    )


def _evaluation(snapshot, *, outcome, candidate_return):
    return PointInTimeDecisionEvaluation(
        identifier=f"evaluation:{snapshot.identifier}",
        snapshot_identifier=snapshot.identifier,
        decision_identifier=snapshot.decision_identifier,
        candidate_identifier=snapshot.candidate_identifier,
        evaluated_at=snapshot.review_at + timedelta(days=1),
        evaluation_horizon_days=30,
        candidate_return=candidate_return,
        implementation_cost_return=snapshot.implementation_cost_return,
        candidate_net_return=candidate_return - snapshot.implementation_cost_return,
        original_best_alternative_identifier="cash",
        original_best_alternative_return=0.02,
        cash_return=0.02,
        excess_return_vs_best_original_alternative=candidate_return - 0.021,
        excess_return_vs_cash=candidate_return - 0.021,
        realized_success=candidate_return > 0.021,
        forecast_brier_score=0.09,
        outcome=outcome,
        data_complete=True,
        source_versions=("prices:v1",),
        notes=("point-in-time test",),
    )


def test_decision_value_report_measures_error_gates_and_remains_advisory() -> None:
    vetoed = _snapshot("vetoed", action=CIOAction.INSUFFICIENT_EVIDENCE, veto=True)
    bought = _snapshot("bought", action=CIOAction.BUY)
    pairs = (
        (
            vetoed,
            _evaluation(
                vetoed,
                outcome=EvaluationOutcome.AVOIDED_LOSS,
                candidate_return=-0.20,
            ),
        ),
        (
            bought,
            _evaluation(
                bought,
                outcome=EvaluationOutcome.VALUE_ADDED,
                candidate_return=0.14,
            ),
        ),
    )

    report = AdvisoryDecisionValueEvaluator().evaluate(
        pairs,
        as_of=bought.review_at + timedelta(days=2),
        segment_labels={
            vetoed.identifier: {"asset_class": "us_equity", "regime": "contraction"},
            bought.identifier: {"asset_class": "us_equity", "regime": "expansion"},
        },
    )

    overall = next(
        item
        for item in report.metrics
        if item.segment.dimension == "all"
    )
    gate = next(item for item in report.gate_metrics if item.gate == "evidence_veto")
    assert overall.count == 2
    assert overall.mean_absolute_return_error > 0.0
    assert gate.avoided_losses == 1
    assert report.advisory_only
    assert report.policy_changes() == ()
