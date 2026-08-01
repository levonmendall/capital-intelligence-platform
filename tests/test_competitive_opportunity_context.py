"""Regression coverage for coherent pre-CIO capital competition."""

from __future__ import annotations

from dataclasses import replace

import pytest

from opportunity import AlternativeKind, OpportunityEngine
from opportunity.competitive import prepare_competitive_opportunity_set
from tests.test_opportunity_engine import _candidate, _context


def test_stronger_holding_realigns_candidate_without_blocking_valid_review() -> None:
    engine = OpportunityEngine()
    context = _context(holding_return=0.08)
    candidate = _candidate("ACME", opportunity_cost=0.04)

    prepared = prepare_competitive_opportunity_set(
        engine,
        (candidate,),
        context,
    )

    expected_baseline = engine._alternative_comparable_return(
        context.alternatives[1],
        cash_anchor=context.alternatives[0].net_expected_return,
    )
    aligned = prepared.candidates[0]
    assert prepared.baseline_opportunity_cost == pytest.approx(expected_baseline)
    assert aligned.opportunity_cost_return == pytest.approx(expected_baseline)
    assert prepared.preliminary_queue.ranked
    assert prepared.queue.ranked
    assert prepared.queue.ranked[0].candidate.identifier == candidate.identifier


def test_cash_relative_success_probability_cannot_create_false_consistency_veto() -> None:
    engine = OpportunityEngine()
    context = _context(holding_return=0.15)
    candidate = replace(
        _candidate(
            "ASYMMETRIC",
            base=0.14,
            bull=0.90,
            bear=-0.05,
            probability=0.90,
            opportunity_cost=0.04,
        ),
        base_case_probability=0.40,
        bull_case_probability=0.45,
        bear_case_probability=0.15,
    )

    stale = engine.qualify(candidate, context)
    assert not stale.qualified
    assert any(
        "inconsistent with the disclosed scenarios" in reason
        for reason in stale.reasons
    )

    prepared = prepare_competitive_opportunity_set(
        engine,
        (candidate,),
        context,
    )

    aligned = prepared.candidates[0]
    assert aligned.opportunity_cost_return > candidate.opportunity_cost_return
    assert aligned.probability_of_success == pytest.approx(0.45)
    assert prepared.preliminary_queue.ranked
    assert not any(
        "inconsistent with the disclosed scenarios" in reason
        for reason in prepared.preliminary_queue.ranked[0].qualification.reasons
    )


def test_unqualified_candidate_cannot_become_a_competing_capital_alternative() -> None:
    engine = OpportunityEngine()
    valid = _candidate("VALID")
    invalid = _candidate(
        "INVALID",
        base=0.80,
        bull=1.20,
        bear=-0.10,
        probability=0.90,
        liquidity=0.10,
    )

    prepared = prepare_competitive_opportunity_set(
        engine,
        (valid, invalid),
        _context(),
    )

    assert valid.identifier in prepared.candidate_alternative_identifiers
    assert invalid.identifier not in prepared.candidate_alternative_identifiers
    assert any(
        item.candidate_identifier == invalid.identifier
        for item in prepared.preliminary_queue.rejected
    )
    assert any(
        item.candidate.identifier == valid.identifier
        for item in prepared.queue.ranked
    )


def test_candidate_alternative_is_net_horizon_normalized_and_not_double_costed() -> None:
    engine = OpportunityEngine()
    context = _context()
    candidate = _candidate("ACME")

    prepared = prepare_competitive_opportunity_set(
        engine,
        (candidate,),
        context,
    )

    aligned = prepared.candidates[0]
    assessment = engine.robustness(aligned, context)
    alternative = next(
        item
        for item in prepared.context.alternatives
        if item.kind is AlternativeKind.QUALIFIED_CANDIDATE
    )
    assert alternative.identifier == aligned.identifier
    assert alternative.expected_return == pytest.approx(
        assessment.evidence_adjusted_return
    )
    assert alternative.implementation_cost_return == 0.0
    assert alternative.net_expected_return == pytest.approx(
        assessment.evidence_adjusted_return
    )


def test_current_holding_is_not_duplicated_as_candidate_alternative() -> None:
    engine = OpportunityEngine()
    held = replace(
        _candidate("HELD", opportunity_cost=0.08),
        current_portfolio_weight=0.10,
        maximum_position_weight=0.10,
    )

    prepared = prepare_competitive_opportunity_set(
        engine,
        (held,),
        _context(holding_return=0.08),
    )

    assert prepared.preliminary_queue.holding_reviews
    assert prepared.candidate_alternative_identifiers == ()
    assert not any(
        item.kind is AlternativeKind.QUALIFIED_CANDIDATE
        for item in prepared.context.alternatives
    )
