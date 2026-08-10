"""Build one simultaneous, non-executing portfolio preview before CIO synthesis.

The preview reuses the canonical construction engine and portfolio state. It provides
portfolio-level marginal sizing context to the CIO but is never an authorization or
an execution result. Final construction still runs after CIO decisions and remains
the sole portfolio-sizing implementation authority.
"""

from __future__ import annotations

from cio.joint_preview import JointPortfolioPreview
from cio.models import CIOAction, CandidateDecisionRecord
from portfolio.construction_api import ConstructionIntent


def _reviewed_candidates(candidates, authoritative_queue):
    if authoritative_queue is None:
        return tuple(candidates), {}, {}
    ranked = tuple(getattr(authoritative_queue, "ranked", ()) or ())
    identifiers = {item.candidate.identifier for item in ranked}
    selected = tuple(item for item in candidates if item.identifier in identifiers)
    ranks = {item.candidate.identifier: item.rank for item in ranked}
    alternatives = {
        item.candidate.identifier: item.qualification.effective_opportunity_cost
        for item in ranked
    }
    return selected, ranks, alternatives


def build_joint_portfolio_preview(
    *,
    cycle_identifier: str,
    candidates: tuple[CandidateDecisionRecord, ...],
    portfolio,
    construction_engine,
    authoritative_queue=None,
) -> JointPortfolioPreview:
    """Preview all CIO-review candidates together with the existing constructor."""

    if not isinstance(candidates, tuple) or not all(
        isinstance(item, CandidateDecisionRecord) for item in candidates
    ):
        raise TypeError("candidates must contain CandidateDecisionRecord values")
    reviewed, ranks, alternatives = _reviewed_candidates(
        candidates,
        authoritative_queue,
    )
    intents: list[ConstructionIntent] = []
    requested: list[tuple[str, float]] = []
    current_by_identifier: dict[str, float] = {}
    for fallback_rank, candidate in enumerate(reviewed, start=1):
        profile = portfolio.profile(candidate.identifier)
        current = portfolio.current_weight(candidate.instrument.symbol)
        current_by_identifier[candidate.identifier] = current
        if current > 0.0 and candidate.net_expected_return <= -0.05:
            action = CIOAction.EXIT
            target = 0.0
        elif current > 0.0 and candidate.net_expected_return < 0.0:
            action = CIOAction.REDUCE
            target = round(current / 2.0, 8)
        else:
            action = CIOAction.INCREASE if current > 0.0 else CIOAction.BUY
            target = candidate.maximum_position_weight
        requested.append((candidate.identifier, target))
        annualized_return = ConstructionIntent.annualized_return(
            candidate.net_expected_return,
            horizon_days=candidate.decision_horizon_days,
        )
        alternative = alternatives.get(
            candidate.identifier,
            candidate.opportunity_cost_return,
        )
        intents.append(
            ConstructionIntent(
                candidate_identifier=candidate.identifier,
                symbol=candidate.instrument.symbol,
                action=action,
                requested_target_weight=target,
                expected_return=annualized_return,
                opportunity_edge=round(annualized_return - alternative, 8),
                maximum_position_weight=candidate.maximum_position_weight,
                sector=profile.sector,
                factor_loadings=profile.factor_loadings,
                correlation_bucket=profile.correlation_bucket,
                average_daily_dollar_volume=(
                    candidate.instrument.average_daily_dollar_volume
                ),
                transaction_cost_bps=candidate.transaction_cost_bps,
                slippage_bps=candidate.slippage_bps,
                priority_rank=ranks.get(candidate.identifier, fallback_rank),
                instrument_identifier=candidate.instrument.instrument_id,
                uses_derivatives=candidate.instrument.uses_derivatives,
                derivative_lifecycle=profile.derivative_lifecycle,
            )
        )

    policy_version = str(getattr(construction_engine.policy, "version", "unknown"))
    if not intents:
        return JointPortfolioPreview(
            identifier=f"joint-preview:{cycle_identifier}",
            status="no_action",
            policy_version=policy_version,
            requested_targets=(),
            joint_targets=(),
            target_cash_weight=float(portfolio.cash_weight),
            expected_return_improvement=0.0,
            blocks=(),
        )

    result = construction_engine.construct(
        portfolio.request(
            identifier=f"joint-preview:{cycle_identifier}",
            intents=tuple(intents),
        )
    )
    by_symbol = dict(result.target_weights)
    joint_targets = tuple(
        (
            candidate.identifier,
            float(
                by_symbol.get(
                    candidate.instrument.symbol,
                    current_by_identifier[candidate.identifier],
                )
            ),
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


__all__ = ["build_joint_portfolio_preview"]
