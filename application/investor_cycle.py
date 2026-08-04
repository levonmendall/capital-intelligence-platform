"""Investor-first canonical cycle using governed view-to-expression selection."""

from __future__ import annotations

from application.compounding_cycle import CompoundingCanonicalCIOCycle
from portfolio.investment_expression import InvestorPortfolioPostureEngine


class InvestorCanonicalCIOCycle(CompoundingCanonicalCIOCycle):
    """Prepare candidate-specific expression evidence before compounding decisions."""

    def __init__(self, *, posture_engine=None, **kwargs) -> None:
        super().__init__(
            posture_engine=posture_engine or InvestorPortfolioPostureEngine(),
            **kwargs,
        )

    def run(self, **kwargs):
        candidates = kwargs.get("candidates")
        specialist_contexts = kwargs.get("specialist_contexts")
        portfolio = kwargs.get("portfolio")
        engine = self.posture_engine
        if isinstance(engine, InvestorPortfolioPostureEngine):
            engine.set_expression_context(
                candidates=candidates,
                specialist_contexts=specialist_contexts,
                portfolio=portfolio,
            )
        try:
            return super().run(**kwargs)
        finally:
            if isinstance(engine, InvestorPortfolioPostureEngine):
                engine.clear_expression_context()


__all__ = ["InvestorCanonicalCIOCycle"]
