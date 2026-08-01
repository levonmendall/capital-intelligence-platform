"""Prepare a coherent point-in-time capital competition before CIO review.

Candidate records are built independently from the current portfolio and initially
carry the observable cash hurdle. Once the current portfolio is known, every candidate
must be compared with the same strongest baseline use of capital. Only candidates that
first pass the governed universe, evidence, liquidity, downside, cost, and applicable
robustness controls may then appear as competing candidate alternatives.

This module changes no investment threshold and grants no decision or execution
authority. It only prevents stale baseline values and unqualified candidates from
blocking otherwise valid specialist and CIO review.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cio import CandidateDecisionRecord
from opportunity.engine import OpportunityEngine
from opportunity.models import (
    AlternativeKind,
    AlternativeUse,
    OpportunityQueue,
    OpportunitySetContext,
)


@dataclass(frozen=True, slots=True)
class CompetitiveOpportunitySet:
    """Two-pass governed opportunity-set preparation result."""

    candidates: tuple[CandidateDecisionRecord, ...]
    context: OpportunitySetContext
    preliminary_queue: OpportunityQueue
    queue: OpportunityQueue
    baseline_opportunity_cost: float
    candidate_alternative_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not all(
            isinstance(item, CandidateDecisionRecord) for item in self.candidates
        ):
            raise TypeError("candidates must contain CandidateDecisionRecord values")
        if not isinstance(self.context, OpportunitySetContext):
            raise TypeError("context must be OpportunitySetContext")
        if not isinstance(self.preliminary_queue, OpportunityQueue):
            raise TypeError("preliminary_queue must be OpportunityQueue")
        if not isinstance(self.queue, OpportunityQueue):
            raise TypeError("queue must be OpportunityQueue")
        if isinstance(self.baseline_opportunity_cost, bool) or not isinstance(
            self.baseline_opportunity_cost, (int, float)
        ):
            raise TypeError("baseline_opportunity_cost must be numeric")
        if not isinstance(self.candidate_alternative_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.candidate_alternative_identifiers
        ):
            raise TypeError(
                "candidate_alternative_identifiers must contain non-empty strings"
            )
        if len(self.candidate_alternative_identifiers) != len(
            set(self.candidate_alternative_identifiers)
        ):
            raise ValueError("candidate alternative identifiers must be unique")


def _baseline_opportunity_cost(
    engine: OpportunityEngine,
    context: OpportunitySetContext,
) -> float:
    baseline = tuple(
        item
        for item in context.alternatives
        if item.kind is not AlternativeKind.QUALIFIED_CANDIDATE
    )
    if not baseline:
        raise ValueError("baseline opportunity context requires cash or a holding")
    cash = tuple(item for item in baseline if item.kind is AlternativeKind.CASH)
    if not cash:
        raise ValueError("baseline opportunity context requires a cash alternative")
    cash_anchor = max(item.net_expected_return for item in cash)
    best = max(
        baseline,
        key=lambda item: (
            engine._alternative_comparable_return(  # package-internal shared rule
                item,
                cash_anchor=cash_anchor,
            ),
            item.evidence_quality,
            item.liquidity_score,
            item.identifier,
        ),
    )
    return engine._alternative_comparable_return(
        best,
        cash_anchor=cash_anchor,
    )


def _scenario_success_probability(
    engine: OpportunityEngine,
    candidate: CandidateDecisionRecord,
    *,
    baseline_opportunity_cost: float,
) -> float:
    """Resolve success as disclosed scenarios outperforming the actual baseline."""

    horizon_baseline = engine.robust_assessor.horizon_return(
        baseline_opportunity_cost,
        horizon_days=candidate.decision_horizon_days,
    )
    return round(
        sum(
            outcome.probability
            for outcome in candidate.scenario_distribution
            if outcome.total_return - candidate.implementation_cost_return
            > horizon_baseline
        ),
        8,
    )


def _align_candidate(
    engine: OpportunityEngine,
    candidate: CandidateDecisionRecord,
    *,
    baseline_opportunity_cost: float,
) -> CandidateDecisionRecord:
    if abs(candidate.opportunity_cost_return - baseline_opportunity_cost) <= 1e-12:
        return candidate
    return replace(
        candidate,
        opportunity_cost_return=baseline_opportunity_cost,
        probability_of_success=_scenario_success_probability(
            engine,
            candidate,
            baseline_opportunity_cost=baseline_opportunity_cost,
        ),
    )


def prepare_competitive_opportunity_set(
    engine: OpportunityEngine,
    candidates: tuple[CandidateDecisionRecord, ...],
    baseline_context: OpportunitySetContext,
) -> CompetitiveOpportunitySet:
    """Align candidates to one baseline, then admit only vetted competitors.

    Pass one evaluates all candidates against cash and current holdings only. Candidate
    records are immutably aligned to that same point-in-time baseline so the engine's
    stale-opportunity-cost integrity control remains effective without rejecting every
    new candidate after the portfolio acquires a stronger holding. When that baseline
    changes, probability of success is resolved from the candidate's disclosed scenario
    distribution against the same horizon-matched baseline, preventing a cash-relative
    probability from creating a false scenario-consistency veto. Unchanged all-cash
    baselines retain the candidate's existing probability estimate.

    Pass two adds only pass-one qualified, non-held candidates as competing uses of
    capital. Their alternative return is already net, horizon-normalized,
    evidence-adjusted, and uncertainty-penalized, so no second implementation cost or
    evidence shrinkage is applied to that resolved comparable return.
    """

    if not isinstance(engine, OpportunityEngine):
        raise TypeError("engine must be OpportunityEngine")
    if not isinstance(candidates, tuple) or not all(
        isinstance(item, CandidateDecisionRecord) for item in candidates
    ):
        raise TypeError("candidates must contain CandidateDecisionRecord values")
    if not isinstance(baseline_context, OpportunitySetContext):
        raise TypeError("baseline_context must be OpportunitySetContext")
    if any(
        item.kind is AlternativeKind.QUALIFIED_CANDIDATE
        for item in baseline_context.alternatives
    ):
        raise ValueError(
            "baseline_context cannot contain candidate alternatives before qualification"
        )

    baseline_cost = _baseline_opportunity_cost(engine, baseline_context)
    aligned = tuple(
        _align_candidate(
            engine,
            candidate,
            baseline_opportunity_cost=baseline_cost,
        )
        for candidate in candidates
    )
    preliminary = engine.build_queue(aligned, baseline_context)

    alternatives = list(baseline_context.alternatives)
    admitted: list[str] = []
    for ranked in preliminary.ranked:
        candidate = ranked.candidate
        if candidate.current_portfolio_weight > 0.0:
            # The same exposure already exists as a CURRENT_HOLDING alternative.
            continue
        assessment = engine.robustness(candidate, baseline_context)
        alternatives.append(
            AlternativeUse(
                identifier=candidate.identifier,
                kind=AlternativeKind.QUALIFIED_CANDIDATE,
                expected_return=assessment.evidence_adjusted_return,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=0.0,
            )
        )
        admitted.append(candidate.identifier)

    final_context = replace(
        baseline_context,
        alternatives=tuple(alternatives),
    )
    final_queue = engine.build_queue(aligned, final_context)
    return CompetitiveOpportunitySet(
        candidates=aligned,
        context=final_context,
        preliminary_queue=preliminary,
        queue=final_queue,
        baseline_opportunity_cost=baseline_cost,
        candidate_alternative_identifiers=tuple(admitted),
    )


__all__ = [
    "CompetitiveOpportunitySet",
    "prepare_competitive_opportunity_set",
]
