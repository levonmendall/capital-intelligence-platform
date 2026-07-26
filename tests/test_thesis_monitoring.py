"""Tests for living-thesis state, monitoring, and CIO-review authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from cio import ThesisState
from tests.cio_test_fixtures import AS_OF, build_candidate, build_decision
from thesis import (
    LivingThesis,
    ThesisEvidenceUpdate,
    ThesisMonitor,
    ThesisReviewProposal,
)


def _thesis() -> LivingThesis:
    candidate = build_candidate()
    return LivingThesis.from_decision(candidate, build_decision(candidate))


def _update(
    thesis: LivingThesis,
    *,
    expected_return: float | None = None,
    expected_downside: float | None = None,
    confidence: float | None = None,
    strengthened: tuple[str, ...] = (),
    weakened: tuple[str, ...] = (),
    invalidations: tuple[str, ...] = (),
    data_current: bool = True,
    replacement_return: float = 0.04,
) -> ThesisEvidenceUpdate:
    return ThesisEvidenceUpdate(
        thesis_identifier=thesis.identifier,
        as_of=AS_OF + timedelta(days=1),
        expected_return=(
            thesis.expected_return
            if expected_return is None
            else expected_return
        ),
        expected_downside=(
            thesis.expected_downside
            if expected_downside is None
            else expected_downside
        ),
        confidence=(
            thesis.current_confidence if confidence is None else confidence
        ),
        evidence_identifiers=("evidence:review:1",),
        strengthened_indicators=strengthened,
        weakened_indicators=weakened,
        triggered_invalidation_conditions=invalidations,
        data_current=data_current,
        performance_since_approval=0.01,
        best_replacement_expected_return=replacement_return,
        next_review_at=AS_OF + timedelta(days=31),
    )


def test_approved_decision_creates_active_living_thesis() -> None:
    candidate = build_candidate()
    decision = build_decision(candidate)

    thesis = LivingThesis.from_decision(candidate, decision)

    assert thesis.state is ThesisState.ACTIVE
    assert thesis.asset == "ACME"
    assert thesis.original_rationale == decision.thesis
    assert thesis.initial_confidence == decision.final_confidence
    assert thesis.current_confidence == decision.final_confidence
    assert thesis.review_count == 0


def test_stable_update_continues_monitoring_without_cio_action_proposal() -> None:
    thesis = _thesis()

    review = ThesisMonitor().evaluate(thesis, _update(thesis))

    assert review.new_state is ThesisState.STABLE
    assert review.proposal is ThesisReviewProposal.CONTINUE_MONITORING
    assert not review.required_cio_review


def test_strengthening_thesis_proposes_cio_increase_review() -> None:
    thesis = _thesis()

    review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=thesis.expected_return + 0.04,
            confidence=min(1.0, thesis.current_confidence + 0.12),
            strengthened=("Forward revisions accelerated",),
        ),
    )

    assert review.new_state is ThesisState.STRENGTHENING
    assert review.proposal is ThesisReviewProposal.REVIEW_INCREASE
    assert review.required_cio_review
    assert review.expected_return_change == pytest.approx(0.04)


def test_weakening_thesis_proposes_cio_reduce_review() -> None:
    thesis = _thesis()

    review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=thesis.expected_return - 0.04,
            confidence=max(0.0, thesis.current_confidence - 0.12),
            weakened=("Estimate revisions reversed",),
        ),
    )

    assert review.new_state is ThesisState.WEAKENING
    assert review.proposal is ThesisReviewProposal.REVIEW_REDUCE
    assert review.required_cio_review


def test_stale_evidence_forces_evidence_review() -> None:
    thesis = _thesis()

    review = ThesisMonitor().evaluate(
        thesis,
        _update(thesis, data_current=False),
    )

    assert review.new_state is ThesisState.WEAKENING
    assert review.proposal is ThesisReviewProposal.REVIEW_EVIDENCE
    assert review.required_cio_review


def test_materially_superior_replacement_proposes_reduce_or_exit() -> None:
    thesis = _thesis()

    reduce_review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=0.10,
            replacement_return=0.15,
        ),
    )
    exit_review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=0.08,
            replacement_return=0.20,
        ),
    )

    assert reduce_review.proposal is ThesisReviewProposal.REVIEW_REDUCE
    assert reduce_review.replacement_opportunity_edge == pytest.approx(0.05)
    assert exit_review.proposal is ThesisReviewProposal.REVIEW_EXIT
    assert exit_review.replacement_opportunity_edge == pytest.approx(0.12)


def test_explicit_invalidation_has_priority_over_other_changes() -> None:
    thesis = _thesis()

    review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=thesis.expected_return + 0.10,
            strengthened=("Revenue accelerated",),
            invalidations=("Forward estimates fell more than 10%",),
        ),
    )

    assert review.new_state is ThesisState.INVALIDATED
    assert review.proposal is ThesisReviewProposal.INVALIDATE
    assert review.triggered_invalidation_conditions
    assert review.required_cio_review


def test_applying_review_preserves_original_thesis_and_appends_state() -> None:
    thesis = _thesis()
    review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=thesis.expected_return + 0.04,
            strengthened=("Cash flow improved",),
        ),
    )

    updated = thesis.apply(review)

    assert updated is not thesis
    assert updated.original_rationale == thesis.original_rationale
    assert updated.created_at == thesis.created_at
    assert updated.state is ThesisState.STRENGTHENING
    assert updated.review_count == 1
    assert updated.updated_at == review.reviewed_at
    assert updated.current_confidence == review.current_confidence


def test_terminal_thesis_cannot_be_reviewed_again() -> None:
    thesis = replace(_thesis(), state=ThesisState.INVALIDATED)

    with pytest.raises(ValueError, match="cannot receive"):
        ThesisMonitor().evaluate(thesis, _update(thesis))


def test_monitoring_proposals_are_not_final_cio_actions() -> None:
    thesis = _thesis()
    review = ThesisMonitor().evaluate(
        thesis,
        _update(
            thesis,
            expected_return=thesis.expected_return + 0.04,
            strengthened=("Margins expanded",),
        ),
    )

    assert isinstance(review.proposal, ThesisReviewProposal)
    assert review.proposal.value.startswith("review_")
    assert review.required_cio_review


def test_review_must_match_current_thesis_snapshot() -> None:
    thesis = _thesis()
    review = ThesisMonitor().evaluate(thesis, _update(thesis))

    wrong_state = replace(review, prior_state=ThesisState.WEAKENING)
    with pytest.raises(ValueError, match="prior_state"):
        thesis.apply(wrong_state)

    wrong_thesis = replace(review, thesis_identifier="thesis:other")
    with pytest.raises(ValueError, match="does not match"):
        thesis.apply(wrong_thesis)
