"""Construction-backed marginal target selection for the production CIO cycle.

The historical cycle used the largest feasible position as a ranking proxy and asked
construction to trim it later. This runtime binding instead evaluates a deterministic,
bounded grid of candidate target weights with the canonical construction engine,
including the unchanged portfolio, and freezes the target that produces the strongest
feasible after-cost portfolio. It does not change CIO thresholds or execution
authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from cio import CIOAction
from committee.specialists import PortfolioSpecialistContext
from opportunity import OpportunityRankingInput
from portfolio.construction_api import (
    ConstructionIntent,
    ConstructionStatus,
    PortfolioConstructionEngine,
    PortfolioConstructionPolicy,
    TradeSide,
)
from thesis import StructuredThesisConditionScorer

_EPSILON = 1e-7
_INSTALL_MARKER = "_construction_backed_marginal_targeting_v1"
_TARGET_SEARCH_STEPS = 8


@dataclass(frozen=True, slots=True)
class MarginalTargetSelection:
    target_weight: float
    baseline: object
    result: object
    contribution: float
    attempted_blocks: tuple[str, ...]


def _candidate_targets(*, current_weight: float, maximum_weight: float) -> tuple[float, ...]:
    maximum = max(0.0, float(maximum_weight))
    current = max(0.0, min(maximum, float(current_weight)))
    if maximum <= _EPSILON:
        return (0.0,)
    # Comprehensive discovery can produce a large qualified set. Eight intervals
    # preserve meaningful intermediate targets while bounding construction work to
    # at most nine grid points plus an exact off-grid current weight.
    steps = _TARGET_SEARCH_STEPS
    values = {0.0, round(current, 8), round(maximum, 8)}
    values.update(round(maximum * index / steps, 8) for index in range(1, steps))
    return tuple(sorted(values))


def _intent_for_target(candidate, profile, *, target: float, current: float, rank: int, alternative: float):
    if target > current + _EPSILON:
        action = CIOAction.INCREASE if current > _EPSILON else CIOAction.BUY
    elif target < current - _EPSILON:
        action = CIOAction.EXIT if target <= _EPSILON else CIOAction.REDUCE
    else:
        return None
    annualized = ConstructionIntent.annualized_return(
        candidate.net_expected_return,
        horizon_days=candidate.decision_horizon_days,
    )
    return ConstructionIntent(
        candidate_identifier=candidate.identifier,
        symbol=candidate.instrument.symbol,
        action=action,
        requested_target_weight=round(target, 8),
        expected_return=annualized,
        opportunity_edge=round(annualized - alternative, 8),
        maximum_position_weight=candidate.maximum_position_weight,
        sector=profile.sector,
        factor_loadings=profile.factor_loadings,
        correlation_bucket=profile.correlation_bucket,
        average_daily_dollar_volume=candidate.instrument.average_daily_dollar_volume,
        transaction_cost_bps=candidate.transaction_cost_bps,
        slippage_bps=candidate.slippage_bps,
        priority_rank=rank,
        instrument_identifier=candidate.instrument.instrument_id,
        uses_derivatives=candidate.instrument.uses_derivatives,
        derivative_lifecycle=profile.derivative_lifecycle,
    )


def _optimize_target(
    candidate,
    portfolio,
    *,
    construction_engine: PortfolioConstructionEngine,
    rank: int,
    effective_opportunity_cost: float,
) -> MarginalTargetSelection:
    profile = portfolio.profile(candidate.identifier)
    current = portfolio.current_weight(candidate.instrument.symbol)
    if abs(current - candidate.current_portfolio_weight) > 0.000001:
        raise ValueError("candidate current weight does not match portfolio state")
    baseline = construction_engine.construct(
        portfolio.request(
            identifier=f"marginal-baseline:{candidate.identifier}",
            intents=(),
        )
    )
    best = baseline
    best_target = current
    attempted_blocks: list[str] = []
    for target in _candidate_targets(
        current_weight=current,
        maximum_weight=min(
            candidate.maximum_position_weight,
            construction_engine.policy.maximum_position_weight,
        ),
    ):
        intent = _intent_for_target(
            candidate,
            profile,
            target=target,
            current=current,
            rank=rank,
            alternative=effective_opportunity_cost,
        )
        if intent is None:
            continue
        trial = construction_engine.construct(
            portfolio.request(
                identifier=f"marginal-preview:{candidate.identifier}:{target:.8f}",
                intents=(intent,),
            )
        )
        attempted_blocks.extend(trial.blocks)
        if trial.status is ConstructionStatus.BLOCKED:
            continue
        actual_target = dict(trial.target_weights).get(candidate.instrument.symbol, 0.0)
        trial_key = (
            trial.expected_return_after_cost,
            trial.expected_return_improvement,
            -trial.estimated_cost_return,
            -trial.turnover,
            -abs(actual_target - current),
        )
        best_key = (
            best.expected_return_after_cost,
            best.expected_return_improvement,
            -best.estimated_cost_return,
            -best.turnover,
            -abs(best_target - current),
        )
        if trial_key > best_key:
            best = trial
            best_target = actual_target
    contribution = round(
        max(0.0, best.expected_return_after_cost - baseline.expected_return_after_cost),
        8,
    )
    return MarginalTargetSelection(
        target_weight=round(best_target, 8),
        baseline=baseline,
        result=best,
        contribution=contribution,
        attempted_blocks=tuple(dict.fromkeys(attempted_blocks)),
    )


def _ranking_inputs_impl(
    candidates: Iterable[object],
    portfolio,
    *,
    construction_engine: PortfolioConstructionEngine,
) -> tuple[OpportunityRankingInput, ...]:
    sector_weights: dict[str, float] = {}
    bucket_weights: dict[str, float] = {}
    for asset in portfolio.positions:
        sector_weights[asset.sector] = sector_weights.get(asset.sector, 0.0) + asset.current_weight
        bucket_weights[asset.correlation_bucket] = (
            bucket_weights.get(asset.correlation_bucket, 0.0) + asset.current_weight
        )
    scorer = StructuredThesisConditionScorer()
    values: list[OpportunityRankingInput] = []
    for candidate in tuple(candidates):
        try:
            profile = portfolio.profile(candidate.identifier)
            profile_sector = profile.sector
            profile_bucket = profile.correlation_bucket
            thesis_conditions = profile.thesis_conditions
            invalidation_conditions_structured = profile.invalidation_conditions_structured
            selection = _optimize_target(
                candidate,
                portfolio,
                construction_engine=construction_engine,
                rank=1,
                effective_opportunity_cost=portfolio.cash_expected_return,
            )
            contribution = selection.contribution
        except KeyError:
            profile_sector = "unclassified"
            profile_bucket = "unclassified"
            thesis_conditions = ()
            invalidation_conditions_structured = ()
            contribution = 0.0
        concentration = max(
            sector_weights.get(profile_sector, 0.0),
            bucket_weights.get(profile_bucket, 0.0),
        )
        diversification = max(0.0, min(1.0, 1.0 - concentration))
        thesis = scorer.score(thesis_conditions).score
        invalidation = scorer.score(invalidation_conditions_structured).score
        horizon_factor = min(1.0, max(0.20, candidate.decision_horizon_days / 90.0))
        durability = max(
            0.0,
            min(
                1.0,
                horizon_factor
                * (
                    0.50 * candidate.evidence_quality.freshness
                    + 0.30 * candidate.evidence_quality.completeness
                    + 0.20 * candidate.evidence_quality.independence
                ),
            ),
        )
        values.append(
            OpportunityRankingInput(
                candidate_identifier=candidate.identifier,
                marginal_portfolio_contribution=contribution,
                diversification_score=diversification,
                thesis_clarity_score=thesis,
                invalidation_clarity_score=invalidation,
                forecast_durability_score=durability,
            )
        )
    return tuple(values)


def _hybrid_ranking_inputs(self_or_candidates, candidates_or_portfolio, portfolio=None, *, minimum_cash_weight=0.02):
    # Preserve both historical class-level calls and normal instance calls.
    from application.cio_cycle import CanonicalCIOCycle

    if isinstance(self_or_candidates, CanonicalCIOCycle):
        engine = self_or_candidates.construction_engine
        candidates = candidates_or_portfolio
        resolved_portfolio = portfolio
    else:
        engine = PortfolioConstructionEngine(
            PortfolioConstructionPolicy(minimum_cash_weight=minimum_cash_weight)
        )
        candidates = self_or_candidates
        resolved_portfolio = candidates_or_portfolio
    if resolved_portfolio is None:
        raise TypeError("portfolio is required")
    return _ranking_inputs_impl(
        candidates,
        resolved_portfolio,
        construction_engine=engine,
    )


def _preview_portfolio(
    self,
    *,
    candidate,
    rank: int,
    portfolio,
    effective_opportunity_cost: float,
) -> PortfolioSpecialistContext:
    selection = _optimize_target(
        candidate,
        portfolio,
        construction_engine=self.construction_engine,
        rank=rank,
        effective_opportunity_cost=effective_opportunity_cost,
    )
    current = portfolio.current_weight(candidate.instrument.symbol)
    proposed = (
        selection.target_weight
        if abs(selection.target_weight - current) > 0.000001
        else None
    )
    funding_symbols = tuple(
        item.symbol
        for item in selection.result.trades
        if item.side is TradeSide.SELL
        and candidate.instrument.symbol in item.funding_for
    )
    funding_source = (
        "cash above minimum reserve"
        if proposed is not None and not funding_symbols
        else ("reduce " + ", ".join(funding_symbols) if funding_symbols else None)
    )
    if proposed is None:
        hard_blocks = tuple(
            dict.fromkeys(
                (
                    *selection.result.blocks,
                    *selection.attempted_blocks,
                    "No feasible target weight improved the complete portfolio after costs.",
                )
            )
        )
    elif selection.result.status is ConstructionStatus.BLOCKED:
        hard_blocks = selection.result.blocks
    else:
        hard_blocks = ()
    evidence = tuple(
        item.detail for item in selection.result.constraints if item.satisfied
    ) or ("Portfolio constraints were evaluated across candidate target weights",)
    review_conditions = tuple(
        dict.fromkeys(
            (
                *selection.result.blocks,
                "Re-run marginal target optimization when portfolio weights, costs, liquidity, scenarios, or exposures change",
            )
        )
    )
    return PortfolioSpecialistContext(
        as_of=portfolio.as_of,
        proposed_position_weight=proposed,
        funding_source=funding_source,
        expected_portfolio_contribution=selection.contribution,
        opportunity_cost_return=effective_opportunity_cost,
        constraint_evidence=evidence,
        implementation_blocks=hard_blocks,
        review_conditions=review_conditions,
    )


def install_construction_backed_marginal_targeting() -> None:
    """Install the corrected production targeting methods exactly once."""
    from application.cio_cycle import CanonicalCIOCycle

    if bool(getattr(CanonicalCIOCycle, _INSTALL_MARKER, False)):
        return
    CanonicalCIOCycle.prepare_ranking_inputs = _hybrid_ranking_inputs
    CanonicalCIOCycle._ranking_inputs = _hybrid_ranking_inputs
    CanonicalCIOCycle._preview_portfolio = _preview_portfolio
    setattr(CanonicalCIOCycle, _INSTALL_MARKER, True)


__all__ = [
    "MarginalTargetSelection",
    "install_construction_backed_marginal_targeting",
]
