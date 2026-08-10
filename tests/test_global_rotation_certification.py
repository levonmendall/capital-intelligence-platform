from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from evaluation.global_rotation_certification import (
    GlobalRotationCertificationPolicy,
    GlobalRotationOutcomeObservation,
    build_global_rotation_certification,
)

NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def _observation(index: int, *, action: bool = True) -> GlobalRotationOutcomeObservation:
    decision = NOW - timedelta(days=40 - index)
    return GlobalRotationOutcomeObservation(
        identifier=f"rotation:{index}",
        decision_as_of=decision,
        knowledge_cutoff=decision,
        outcome_observed_at=decision + timedelta(days=10),
        portfolio_return=0.02 if index % 2 == 0 else 0.01,
        equity_market_return=-0.03 if index % 2 == 0 else 0.01,
        starting_cash_weight=0.40,
        minimum_cash_weight=0.05,
        ending_cash_weight=0.20 if action else 0.40,
        deployment_opportunity_present=True,
        positive_rotation_action_taken=action,
        deteriorating_owned_leadership=index % 3 == 0,
        derisk_action_taken=True,
        strongest_leadership_return=0.06,
        selected_rotation_return=0.05 if action else None,
        evidence_identifiers=(f"evidence:{index}",),
    )


def _policy() -> GlobalRotationCertificationPolicy:
    return GlobalRotationCertificationPolicy(
        minimum_observations=10,
        minimum_equity_down_observations=5,
        minimum_deployment_opportunities=10,
        minimum_leadership_participation_rate=0.80,
        minimum_derisk_response_rate=0.80,
        maximum_unexplained_cash_rate=0.10,
        minimum_positive_return_rate_during_equity_down_periods=0.60,
    )


def test_rotation_certification_rewards_deployment_derisk_and_equity_down_growth():
    report = build_global_rotation_certification(
        observations=tuple(_observation(index) for index in range(20)),
        as_of=NOW,
        policy=_policy(),
    )
    assert report.rotation_behavior_certified is True
    assert report.leadership_participation_rate == 1.0
    assert report.derisk_response_rate == 1.0
    assert report.unexplained_cash_count == 0
    assert report.positive_return_rate_during_equity_down_periods == 1.0
    assert report.performance_claim_authorized is False
    assert report.policy_change_authorized is False
    assert report.investment_authority is False


def test_rotation_certification_flags_excess_cash_when_leadership_was_ignored():
    report = build_global_rotation_certification(
        observations=tuple(
            _observation(index, action=index % 2 == 0) for index in range(20)
        ),
        as_of=NOW,
        policy=_policy(),
    )
    assert report.rotation_behavior_certified is False
    assert report.unexplained_cash_count == 10
    assert report.unexplained_cash_rate == 0.5
    assert dict(report.gates)["unexplained_cash"] is False
    assert dict(report.gates)["leadership_participation"] is False


def test_rotation_certification_fails_closed_on_future_knowledge():
    item = _observation(0)
    leaked = replace(
        item,
        knowledge_cutoff=item.decision_as_of + timedelta(minutes=1),
    )
    report = build_global_rotation_certification(
        observations=(leaked,),
        as_of=NOW,
        policy=GlobalRotationCertificationPolicy(
            minimum_observations=1,
            minimum_equity_down_observations=1,
            minimum_deployment_opportunities=1,
            minimum_leadership_participation_rate=0.0,
            minimum_derisk_response_rate=0.0,
            maximum_unexplained_cash_rate=1.0,
            minimum_positive_return_rate_during_equity_down_periods=0.0,
        ),
    )
    assert report.point_in_time_valid is False
    assert report.rotation_behavior_certified is False
    assert dict(report.gates)["point_in_time_integrity"] is False
