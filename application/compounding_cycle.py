"""Compounding-first extension of the canonical CIO decision cycle.

The base canonical cycle remains authoritative for opportunity qualification, six
specialists, CIO decisions, construction, thesis lineage, and reporting.  This
extension supplies one governed portfolio posture to the CIO, persists complete
portfolio alternatives, and returns the base result with additional read-only
allocation context.
"""

from __future__ import annotations

from dataclasses import fields

from application.cio_cycle import CanonicalCIOCycle, CanonicalCIOCycleResult
from cio.compounding_authority import CompoundingChiefInvestmentOfficer
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from portfolio.compounding_allocation import (
    CompoundingPortfolioAlternativeEngine,
    CompoundingPortfolioAlternativeSet,
    PortfolioPosture,
    PortfolioPostureEngine,
    SQLiteCompoundingAllocationStore,
)


class CompoundingCanonicalCIOCycleResult(CanonicalCIOCycleResult):
    """Canonical result with additional advisory compounding context."""

    __slots__ = ("portfolio_posture", "portfolio_alternatives")

    def __init__(
        self,
        *,
        base_result: CanonicalCIOCycleResult,
        portfolio_posture: PortfolioPosture,
        portfolio_alternatives: CompoundingPortfolioAlternativeSet,
    ) -> None:
        if not isinstance(base_result, CanonicalCIOCycleResult):
            raise TypeError("base_result must be CanonicalCIOCycleResult")
        if not isinstance(portfolio_posture, PortfolioPosture):
            raise TypeError("portfolio_posture must be PortfolioPosture")
        if not isinstance(
            portfolio_alternatives,
            CompoundingPortfolioAlternativeSet,
        ):
            raise TypeError(
                "portfolio_alternatives must be CompoundingPortfolioAlternativeSet"
            )
        super().__init__(
            **{
                item.name: getattr(base_result, item.name)
                for item in fields(CanonicalCIOCycleResult)
            }
        )
        object.__setattr__(self, "portfolio_posture", portfolio_posture)
        object.__setattr__(self, "portfolio_alternatives", portfolio_alternatives)


class CompoundingCanonicalCIOCycle(CanonicalCIOCycle):
    """Run the canonical cycle with portfolio posture and staged participation."""

    def __init__(
        self,
        *,
        posture_engine: PortfolioPostureEngine | None = None,
        alternative_engine: CompoundingPortfolioAlternativeEngine | None = None,
        allocation_store: SQLiteCompoundingAllocationStore | None = None,
        cio=None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
        journal=None,
        **kwargs,
    ) -> None:
        authority = policy_authority or CanonicalDecisionPolicyAuthority()
        resolved_cio = cio or CompoundingChiefInvestmentOfficer(
            policy_authority=authority
        )
        super().__init__(
            cio=resolved_cio,
            policy_authority=authority,
            journal=journal,
            **kwargs,
        )
        self.posture_engine = posture_engine or PortfolioPostureEngine()
        self.alternative_engine = (
            alternative_engine or CompoundingPortfolioAlternativeEngine()
        )
        self.allocation_store = allocation_store
        if self.allocation_store is None and self.journal is not None:
            self.allocation_store = SQLiteCompoundingAllocationStore(
                self.journal.path
            )

    def run(self, **kwargs) -> CompoundingCanonicalCIOCycleResult:
        candidates = kwargs.get("candidates")
        specialist_contexts = kwargs.get("specialist_contexts")
        portfolio = kwargs.get("portfolio")
        identifier = kwargs.get("identifier")
        code_version = kwargs.get("code_version") or "unknown"
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be supplied as a tuple")
        if not isinstance(specialist_contexts, tuple):
            raise TypeError("specialist_contexts must be supplied as a tuple")
        if portfolio is None:
            raise TypeError("portfolio must be supplied")
        posture = self.posture_engine.assess(
            as_of=portfolio.as_of,
            specialist_contexts=specialist_contexts,
        )
        directives = self.posture_engine.directives(candidates, posture)
        compounding_cio = (
            self.cio
            if isinstance(self.cio, CompoundingChiefInvestmentOfficer)
            else None
        )
        if compounding_cio is not None:
            compounding_cio.set_compounding_context(posture, directives)
        try:
            base_result = super().run(**kwargs)
        finally:
            if compounding_cio is not None:
                compounding_cio.clear_compounding_context()

        qualified_candidates = tuple(
            item.candidate for item in base_result.opportunity_queue.ranked
        )
        alternatives = self.alternative_engine.build(
            cycle_identifier=str(identifier),
            posture=posture,
            candidates=qualified_candidates,
            directives=tuple(
                item
                for item in directives
                if item.candidate_identifier
                in {candidate.identifier for candidate in qualified_candidates}
            ),
            portfolio=portfolio,
            construction=base_result.construction,
        )
        if self.allocation_store is not None:
            self.allocation_store.append(
                cycle_identifier=str(identifier),
                posture=posture,
                alternatives=alternatives,
                code_version=str(code_version),
            )
        return CompoundingCanonicalCIOCycleResult(
            base_result=base_result,
            portfolio_posture=posture,
            portfolio_alternatives=alternatives,
        )


__all__ = [
    "CompoundingCanonicalCIOCycle",
    "CompoundingCanonicalCIOCycleResult",
]
