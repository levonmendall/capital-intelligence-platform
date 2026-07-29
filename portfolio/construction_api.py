"""Canonical portfolio construction import surface.

New callers should import portfolio construction contracts from this module.
The engine produces non-executing trade proposals after CIO approval.
"""

from portfolio.construction_engine import PortfolioConstructionEngine
from portfolio.derivative_lifecycle import (
    DerivativeLifecycleAssessment,
    DerivativeLifecycleAuthority,
    DerivativeLifecyclePolicy,
    DerivativeLifecycleProfile,
)
from portfolio.scenario_authority import (
    GovernedPortfolioScenario,
    GovernedPortfolioScenarioSet,
    PortfolioScenarioAuthority,
)
from portfolio.construction_models import (
    ConstructionIntent,
    ConstructionMode,
    ConstructionStatus,
    ConstraintCheck,
    ExposureLimit,
    PortfolioAsset,
    PortfolioConstructionPolicy,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
    PortfolioScenario,
    PortfolioScenarioMetrics,
    TradeProposal,
    TradeSide,
)

__all__ = [
    "ConstructionIntent",
    "ConstructionMode",
    "ConstructionStatus",
    "ConstraintCheck",
    "DerivativeLifecycleAssessment",
    "DerivativeLifecycleAuthority",
    "DerivativeLifecyclePolicy",
    "DerivativeLifecycleProfile",
    "ExposureLimit",
    "GovernedPortfolioScenario",
    "GovernedPortfolioScenarioSet",
    "PortfolioAsset",
    "PortfolioConstructionEngine",
    "PortfolioConstructionPolicy",
    "PortfolioConstructionRequest",
    "PortfolioConstructionResult",
    "PortfolioScenario",
    "PortfolioScenarioAuthority",
    "PortfolioScenarioMetrics",
    "TradeProposal",
    "TradeSide",
]
