"""Build a simultaneous construction preview from global opportunity ranks.

The preview is non-authoritative. When six-specialist preliminary conviction targets
are available, it previews those bounded targets together rather than raw candidate
maximums. Final CIO actions and final construction remain independent authorities.
"""
from __future__ import annotations

from collections.abc import Mapping

from cio.joint_preview import JointPortfolioPreview
from cio.models import CIOAction
from portfolio.construction_api import ConstructionIntent
from portfolio.global_rotation import GlobalRotationContext


def _reviewed(candidates, queue):
    if queue is None:
        return tuple(candidates), {}, {}
    ranked = tuple(getattr(queue, "ranked", ()) or ())
    identifiers = {item.candidate.identifier for item in ranked}
    return (
        tuple(item for item in candidates if item.identifier in identifiers),
        {item.candidate.identifier: item.rank for item in ranked},
        {
            item.candidate.identifier: item.qualification.effective_opportunity_cost
            for item in ranked
        },
    )


def _action_for_target(*, current: float, target: float) -> CIOAction:
    if current <= 0.0:
        return CIOAction.BUY
    if target < current - 0.00000001:
        return CIOAction.REDUCE
    if target > current + 0.00000001:
        return CIOAction.INCREASE
    return CIOAction.HOLD


def _requested_target(
    candidate,
    current: float,
    context: GlobalRotationContext,
    conviction_targets: Mapping[str, float | None] | None,
) -> tuple[CIOAction, float]:
    # Existing-holding deterioration remains visible even if a preliminary positive
    # conviction target is unavailable. Final CIO holding logic remains authoritative.
    if current > 0.0 and candidate.net_expected_return <= -0.05:
        return CIOAction.EXIT, 0.0
    if current > 0.0 and candidate.net_expected_return < 0.0:
        return CIOAction.REDUCE, round(current / 2.0, 8)

    maximum = float(candidate.maximum_position_weight)
    if conviction_targets is not None and candidate.identifier in conviction_targets:
        proposed = conviction_targets[candidate.identifier]
        target = (
            current
            if proposed is None and current > 0.0
            else 0.0
            if proposed is None
            else min(maximum, max(0.0, float(proposed)))
        )
        return _action_for_target(current=current, target=target), round(target, 8)

    # Compatibility fallback for callers without a complete six-specialist preliminary
    # pass. This remains bounded by the globally ranked score and cannot create authority.
    signal = context.by_candidate.get(candidate.identifier)
    if signal is None or signal.expected_return_edge <= 0.0:
        target = current if current > 0.0 else 0.0
    elif signal.score < 0.40:
        target = current if current > 0.0 else 0.0
    elif signal.score < 0.55:
        target = min(maximum, 0.01)
    elif signal.score < 0.78:
        target = min(maximum, 0.03)
    else:
        target = min(maximum, 0.10)
    return _action_for_target(current=current, target=target), round(target, 8)


def build_global_rotation_preview(
    *,
    cycle_identifier: str,
    candidates: tuple[object, ...],
    portfolio: object,
    construction_engine: object,
    rotation_context: GlobalRotationContext,
    authoritative_queue=None,
    conviction_targets: Mapping[str, float | None] | None = None,
) -> JointPortfolioPreview:
    """Preview globally ranked candidate targets together using canonical construction."""

    if not isinstance(rotation_context, GlobalRotationContext):
        raise TypeError("rotation_context must be GlobalRotationContext")
    if conviction_targets is not None and not isinstance(conviction_targets, Mapping):
        raise TypeError("conviction_targets must be a mapping or None")
    reviewed, ranks, alternatives = _reviewed(candidates, authoritative_queue)
    intents: list[ConstructionIntent] = []
    requested: list[tuple[str, float]] = []
    current_by_id: dict[str, float] = {}
    for fallback_rank, candidate in enumerate(reviewed, start=1):
        current = float(portfolio.current_weight(candidate.instrument.symbol))
        current_by_id[candidate.identifier] = current
        action, target = _requested_target(
            candidate,
            current,
            rotation_context,
            conviction_targets,
        )
        requested.append((candidate.identifier, target))
        if action is CIOAction.HOLD:
            continue
        if target <= 0.0 and current <= 0.0:
            continue
        profile = portfolio.profile(candidate.identifier)
        annualized = ConstructionIntent.annualized_return(
            candidate.net_expected_return,
            horizon_days=candidate.decision_horizon_days,
        )
        alternative = alternatives.get(candidate.identifier, candidate.opportunity_cost_return)
        signal = rotation_context.by_candidate.get(candidate.identifier)
        priority = ranks.get(candidate.identifier, fallback_rank) if signal is None else signal.rank
        intents.append(
            ConstructionIntent(
                candidate_identifier=candidate.identifier,
                symbol=candidate.instrument.symbol,
                action=action,
                requested_target_weight=target,
                expected_return=annualized,
                opportunity_edge=round(annualized - alternative, 8),
                maximum_position_weight=candidate.maximum_position_weight,
                sector=profile.sector,
                factor_loadings=profile.factor_loadings,
                correlation_bucket=profile.correlation_bucket,
                average_daily_dollar_volume=candidate.instrument.average_daily_dollar_volume,
                transaction_cost_bps=candidate.transaction_cost_bps,
                slippage_bps=candidate.slippage_bps,
                priority_rank=priority,
                instrument_identifier=candidate.instrument.instrument_id,
                uses_derivatives=candidate.instrument.uses_derivatives,
                derivative_lifecycle=profile.derivative_lifecycle,
            )
        )
    policy_version = str(getattr(construction_engine.policy, "version", "unknown"))
    if not intents:
        return JointPortfolioPreview(
            identifier=f"global-joint-preview:{cycle_identifier}",
            status="no_action",
            policy_version=policy_version,
            requested_targets=tuple(requested),
            joint_targets=tuple(
                (item.identifier, current_by_id.get(item.identifier, 0.0)) for item in reviewed
            ),
            target_cash_weight=float(portfolio.cash_weight),
            expected_return_improvement=0.0,
            blocks=(),
        )
    result = construction_engine.construct(
        portfolio.request(
            identifier=f"global-joint-preview:{cycle_identifier}",
            intents=tuple(intents),
        )
    )
    by_symbol = dict(result.target_weights)
    joint_targets = tuple(
        (
            candidate.identifier,
            float(by_symbol.get(candidate.instrument.symbol, current_by_id[candidate.identifier])),
        )
        for candidate in reviewed
    )
    return JointPortfolioPreview(
        identifier=result.request_identifier,
        status=result.status.value,
        policy_version=result.policy_version,
        requested_targets=tuple(requested),
        joint_targets=joint_targets,
        target_cash_weight=result.target_cash_weight,
        expected_return_improvement=result.expected_return_improvement,
        blocks=result.blocks,
    )


__all__ = ["build_global_rotation_preview"]
