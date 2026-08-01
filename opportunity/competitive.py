"""Prepare coherent point-in-time capital competition before CIO review.

Candidate records are built independently from the current portfolio and initially
carry the observable cash hurdle. Once the portfolio and competing candidates are
known, each candidate must be evaluated against the same governed baseline and its
actual strongest alternative. Only candidates that first pass the governed universe,
evidence, liquidity, downside, cost, and applicable robustness controls may compete.

This module changes no investment threshold and grants no decision or execution
authority. It prevents stale comparison fields and unqualified candidates from
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


def _cash_anchor(context: OpportunitySetContext) -> float:
    cash = tuple(
        item for item in context.alternatives if item.kind is AlternativeKind.CASH
    )
    if not cash:
        raise ValueError("opportunity context requires a cash alternative")
    return max(item.net_expected_return for item in cash)


def _comparable_return(
    engine: OpportunityEngine,
    alternative: AlternativeUse,
    *,
    cash_anchor: float,
) -> float:
    return engine._alternative_comparable_return(  # package-internal shared rule
        alternative,
        cash_anchor=cash_anchor,
    )


def _strongest_return(
    engine: OpportunityEngine,
    alternatives: tuple[AlternativeUse, ...],
    *,
    cash_anchor: float,
) -> float:
    if not alternatives:
        raise ValueError("at least one capital alternative is required")
    best = max(
        alternatives,
        key=lambda item: (
            _comparable_return(engine, item, cash_anchor=cash_anchor),
            item.evidence_quality,
            item.liquidity_score,
            item.identifier,
        ),
    )
    return _comparable_return(engine, best, cash_anchor=cash_anchor)


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
    return _strongest_return(
        engine,
        baseline,
        cash_anchor=_cash_anchor(context),
    )


def _effective_opportunity_cost(
    engine: OpportunityEngine,
    candidate: CandidateDecisionRecord,
    context: OpportunitySetContext,
) -> float:
    alternatives = tuple(
        item
        for item in context.alternatives
        if not (
            item.kind is AlternativeKind.QUALIFIED_CANDIDATE
            and item.identifier == candidate.identifier
        )
    )
    if not alternatives:
        raise ValueError("candidate has no other available capital alternative")
    return _strongest_return(
        engine,
        alternatives,
        cash_anchor=_cash_anchor(context),
    )


def _scenario_success_probability(
    engine: OpportunityEngine,
    candidate: CandidateDecisionRecord,
    *,
    effective_opportunity_cost: float,
) -> float:
    horizon_alternative = engine.robust_assessor.horizon_return(
        effective_opportunity_cost,
        horizon_days=candidate.decision_horizon_days,
    )
    return round(
        sum(
            outcome.probability
            for outcome in candidate.scenario_distribution
            if outcome.total_return - candidate.implementation_cost_return
            > horizon_alternative
        ),
        8,
    )


def _align_to_baseline(
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
            effective_opportunity_cost=baseline_opportunity_cost,
        ),
    )


def _align_to_final_competition(
    engine: OpportunityEngine,
    candidate: CandidateDecisionRecord,
    *,
    context: OpportunitySetContext,
    baseline_opportunity_cost: float,
) -> CandidateDecisionRecord:
    effective = _effective_opportunity_cost(engine, candidate, context)
    if abs(effective - baseline_opportunity_cost) <= 1e-12:
        return candidate
    return replace(
        candidate,
        probability_of_success=_scenario_success_probability(
            engine,
            candidate,
            effective_opportunity_cost=effective,
        ),
    )


def prepare_competitive_opportunity_set(
    engine: OpportunityEngine,
    candidates: tuple[CandidateDecisionRecord, ...],
    baseline_context: OpportunitySetContext,
) -> CompetitiveOpportunitySet:
    """Build a vetted, internally consistent final committee queue.

    Pass one evaluates candidates against cash and current holdings only. A candidate's
    recorded opportunity cost is aligned to that baseline. Its existing probability is
    preserved when the baseline is unchanged; otherwise probability is derived from its
    disclosed scenarios against the horizon-matched baseline.

    Only pass-one-qualified, non-held candidates become competing candidate
    alternatives. Their comparable return is already net, horizon-normalized,
    evidence-adjusted, and uncertainty-penalized, so it is not charged or shrunk twice.

    Before the final queue is built, each pass-one-qualified candidate's probability is
    aligned to its actual strongest other alternative, including a qualified peer. A
    preliminary reject is never realigned or resurrected during this final pass.
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
    baseline_aligned = tuple(
        _align_to_baseline(
            engine,
            candidate,
            baseline_opportunity_cost=baseline_cost,
        )
        for candidate in candidates
    )
    preliminary = engine.build_queue(baseline_aligned, baseline_context)
    preliminary_qualified = {
        item.candidate.identifier for item in preliminary.ranked
    }

    alternatives = list(baseline_context.alternatives)
    admitted: list[str] = []
    for ranked in preliminary.ranked:
        candidate = ranked.candidate
        if candidate.current_portfolio_weight > 0.0:
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
    final_candidates = tuple(
        (
            _align_to_final_competition(
                engine,
                candidate,
                context=final_context,
                baseline_opportunity_cost=baseline_cost,
            )
            if candidate.identifier in preliminary_qualified
            else candidate
        )
        for candidate in baseline_aligned
    )
    final_queue = engine.build_queue(final_candidates, final_context)
    return CompetitiveOpportunitySet(
        candidates=final_candidates,
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
