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
    build_global_rotation_context,
    opportunity_domain,
)

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
