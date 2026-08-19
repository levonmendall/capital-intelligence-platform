"""Canonical import surface for global opportunity rotation context and conviction."""
from portfolio.global_conviction import (
    ConvictionStage,
    GlobalConvictionDecision,
    GlobalConvictionPolicy,
)
from portfolio.global_rotation_models import (
    CashCompetitionState,
    GlobalOpportunityDomain,
    GlobalOpportunitySignal,
    GlobalRotationContext,
    build_global_rotation_context as _build_global_rotation_context,
    opportunity_domain,
)
from portfolio.marginal_compounding_value import rerank_global_rotation_context


def build_global_rotation_context(*, candidates, **kwargs) -> GlobalRotationContext:
    """Build canonical context, then compare every candidate on one economic scale."""

    context = _build_global_rotation_context(candidates=candidates, **kwargs)
    return rerank_global_rotation_context(context, candidates=candidates)


__all__ = [
    "CashCompetitionState",
    "ConvictionStage",
    "GlobalConvictionDecision",
    "GlobalConvictionPolicy",
    "GlobalOpportunityDomain",
    "GlobalOpportunitySignal",
    "GlobalRotationContext",
    "build_global_rotation_context",
    "opportunity_domain",
]
