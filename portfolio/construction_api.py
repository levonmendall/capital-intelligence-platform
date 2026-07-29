"""Canonical portfolio construction import surface.

New callers should import portfolio construction contracts from this module.
The engine produces non-executing trade proposals after CIO approval.
"""

from portfolio.construction_engine import PortfolioConstructionEngine
from portfolio.construction_models import (
    ConstructionIntent,
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
    "ConstructionStatus",
    "ConstraintCheck",
    "ExposureLimit",
    "PortfolioAsset",
    "PortfolioConstructionEngine",
    "PortfolioConstructionPolicy",
    "PortfolioConstructionRequest",
    "PortfolioConstructionResult",
    "PortfolioScenario",
    "PortfolioScenarioMetrics",
    "TradeProposal",
    "TradeSide",
]
