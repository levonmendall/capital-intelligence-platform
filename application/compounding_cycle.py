"""Compounding-first extension of the canonical CIO decision cycle.

The base canonical cycle remains authoritative for opportunity qualification, six
specialists, CIO decisions, construction, thesis lineage, and reporting. This
extension supplies governed portfolio posture, certified view-to-expression ranking,
position lifecycle, reactive dependencies, portfolio alternatives, and compounding
accountability without creating a parallel decision or execution path.
"""

from __future__ import annotations

from dataclasses import fields

from application.cio_cycle import CanonicalCIOCycle, CanonicalCIOCycleResult
from cio.compounding_authority import CompoundingChiefInvestmentOfficer
from intelligence.advanced_shadow import (
    AdvancedIntelligenceShadowCoordinator,
    AdvancedShadowSnapshot,
    SQLiteAdvancedShadowStore,
)
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from portfolio.active_investor import (
    CompoundingAccountabilityEngine,
    CompoundingAccountabilitySnapshot,
    PositionLifecycleEngine,
    PositionLifecyclePlan,
    ReactiveMonitoringEngine,
    ReactiveMonitoringPlan,
    SQLiteActiveInvestorStore,
    ViewExpressionSet,
    ViewToExpressionEngine,
)
from portfolio.compounding_accountability import (
    ProspectiveCompoundingAccountabilityEngine,
)
from portfolio.compounding_allocation import (
    AllocationRange,
    CompoundingPortfolioAlternativeEngine,
    CompoundingPortfolioAlternativeSet,
    PortfolioPosture,
    PortfolioPostureEngine,
    PortfolioRegime,
    PortfolioSleeve,
    RegimeTransition,
    SQLiteCompoundingAllocationStore,
)


class CompoundingCanonicalCIOCycleResult(CanonicalCIOCycleResult):
    """Canonical result with additional non-authoritative investor-loop context."""

    __slots__ = (
        "portfolio_posture",
        "view_expressions",
        "portfolio_alternatives",
        "position_lifecycle",
        "reactive_monitoring",
        "compounding_accountability",
        "advanced_intelligence_shadow",
    )

    def __init__(
        self,
        *,
        base_result: CanonicalCIOCycleResult,
        portfolio_posture: PortfolioPosture,
        view_expressions: ViewExpressionSet,
        portfolio_alternatives: CompoundingPortfolioAlternativeSet,
        position_lifecycle: PositionLifecyclePlan,
        reactive_monitoring: ReactiveMonitoringPlan,
        compounding_accountability: CompoundingAccountabilitySnapshot,
        advanced_intelligence_shadow: AdvancedShadowSnapshot,
    ) -> None:
        if not isinstance(base_result, CanonicalCIOCycleResult):
            raise TypeError("base_result must be CanonicalCIOCycleResult")
        if not isinstance(portfolio_posture, PortfolioPosture):
            raise TypeError("portfolio_posture must be PortfolioPosture")
        if not isinstance(view_expressions, ViewExpressionSet):
            raise TypeError("view_expressions must be ViewExpressionSet")
        if not isinstance(
            portfolio_alternatives,
            CompoundingPortfolioAlternativeSet,
        ):
            raise TypeError(
                "portfolio_alternatives must be CompoundingPortfolioAlternativeSet"
            )
        if not isinstance(position_lifecycle, PositionLifecyclePlan):
            raise TypeError("position_lifecycle must be PositionLifecyclePlan")
        if not isinstance(reactive_monitoring, ReactiveMonitoringPlan):
            raise TypeError("reactive_monitoring must be ReactiveMonitoringPlan")
        if not isinstance(
            compounding_accountability,
            CompoundingAccountabilitySnapshot,
        ):
            raise TypeError(
                "compounding_accountability must be CompoundingAccountabilitySnapshot"
            )
        if not isinstance(advanced_intelligence_shadow, AdvancedShadowSnapshot):
            raise TypeError(
                "advanced_intelligence_shadow must be AdvancedShadowSnapshot"
            )
        super().__init__(
            **{
                item.name: getattr(base_result, item.name)
                for item in fields(CanonicalCIOCycleResult)
            }
        )
        object.__setattr__(self, "portfolio_posture", portfolio_posture)
        object.__setattr__(self, "view_expressions", view_expressions)
        object.__setattr__(self, "portfolio_alternatives", portfolio_alternatives)
        object.__setattr__(self, "position_lifecycle", position_lifecycle)
        object.__setattr__(self, "reactive_monitoring", reactive_monitoring)
        object.__setattr__(
            self,
            "compounding_accountability",
            compounding_accountability,
        )
        object.__setattr__(
            self,
            "advanced_intelligence_shadow",
            advanced_intelligence_shadow,
        )


def _neutral_posture(as_of) -> PortfolioPosture:
    """Represent unavailable posture evidence without blocking the no-candidate cycle."""

    return PortfolioPosture(
        identifier=f"portfolio-posture:{as_of.isoformat()}:unavailable",
        as_of=as_of,
        regime=PortfolioRegime.BALANCED_TRANSITION,
        confidence=0.0,
        risk_score=0.0,
        productive_risk=AllocationRange(0.0, 0.50),
        defensive_income=AllocationRange(0.0, 0.50),
        dollar_liquidity=AllocationRange(0.20, 1.0),
        inflation_real_assets=AllocationRange(0.0, 0.25),
        diversifiers=AllocationRange(0.0, 0.25),
        preferred_sleeves=(),
        discouraged_sleeves=(),
        transitions=(
            RegimeTransition(
                PortfolioRegime.BALANCED_TRANSITION,
                0.50,
                "No qualified specialist context exists, so the current state remains explicitly uncertain.",
                ("complete specialist context",),
            ),
            RegimeTransition(
                PortfolioRegime.RISK_ON_DISINFLATION,
                0.25,
                "A supportive state remains possible but is not established without complete evidence.",
                ("growth", "inflation", "liquidity"),
            ),
            RegimeTransition(
                PortfolioRegime.RISK_OFF_RECESSION,
                0.25,
                "A defensive state remains possible but is not established without complete evidence.",
                ("credit", "financial stress", "breadth"),
            ),
        ),
        evidence=(
            "No qualified candidate specialist context was available for portfolio-posture inference",
        ),
        contradictory_evidence=(),
        change_conditions=(
            "Recalculate when at least one complete qualified specialist context becomes available",
        ),
        model_version="compounding-portfolio-posture.v1-unavailable",
    )


class CompoundingCanonicalCIOCycle(CanonicalCIOCycle):
    """Run the canonical cycle with a complete active-investor reasoning loop."""

    def __init__(
        self,
        *,
        posture_engine: PortfolioPostureEngine | None = None,
        expression_engine: ViewToExpressionEngine | None = None,
        alternative_engine: CompoundingPortfolioAlternativeEngine | None = None,
        lifecycle_engine: PositionLifecycleEngine | None = None,
        reactive_engine: ReactiveMonitoringEngine | None = None,
        accountability_engine: CompoundingAccountabilityEngine | None = None,
        allocation_store: SQLiteCompoundingAllocationStore | None = None,
        active_investor_store: SQLiteActiveInvestorStore | None = None,
        advanced_shadow_coordinator: AdvancedIntelligenceShadowCoordinator | None = None,
        advanced_shadow_store: SQLiteAdvancedShadowStore | None = None,
        cio=None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
        journal=None,
        **kwargs,
    ) -> None:
        opportunity_engine = kwargs.get("opportunity_engine")
        authority = (
            policy_authority
            or getattr(cio, "policy_authority", None)
            or getattr(opportunity_engine, "policy_authority", None)
            or CanonicalDecisionPolicyAuthority()
        )
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
        self.expression_engine = expression_engine or ViewToExpressionEngine()
        self.alternative_engine = (
            alternative_engine or CompoundingPortfolioAlternativeEngine()
        )
        self.lifecycle_engine = lifecycle_engine or PositionLifecycleEngine()
        self.reactive_engine = reactive_engine or ReactiveMonitoringEngine()
        self.accountability_engine = (
            accountability_engine
            or ProspectiveCompoundingAccountabilityEngine()
        )
        self.allocation_store = allocation_store
        self.active_investor_store = active_investor_store
        self.advanced_shadow_coordinator = (
            advanced_shadow_coordinator or AdvancedIntelligenceShadowCoordinator()
        )
        self.advanced_shadow_store = advanced_shadow_store
        if self.journal is not None:
            if self.allocation_store is None:
                self.allocation_store = SQLiteCompoundingAllocationStore(
                    self.journal.path
                )
            if self.active_investor_store is None:
                self.active_investor_store = SQLiteActiveInvestorStore(
                    self.journal.path
                )
            if self.advanced_shadow_store is None:
                self.advanced_shadow_store = SQLiteAdvancedShadowStore(
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

        posture = (
            self.posture_engine.assess(
                as_of=portfolio.as_of,
                specialist_contexts=specialist_contexts,
            )
            if specialist_contexts
            else _neutral_posture(portfolio.as_of)
        )
        base_directives = self.posture_engine.directives(candidates, posture)
        view_expressions = self.expression_engine.build(
            posture=posture,
            candidates=candidates,
            specialist_contexts=specialist_contexts,
            directives=base_directives,
        )
        directives = self.expression_engine.enhance_directives(
            base_directives,
            view_expressions,
        )
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
        qualified_identifiers = {
            candidate.identifier for candidate in qualified_candidates
        }
        alternatives = self.alternative_engine.build(
            cycle_identifier=str(identifier),
            posture=posture,
            candidates=qualified_candidates,
            directives=tuple(
                item
                for item in directives
                if item.candidate_identifier in qualified_identifiers
            ),
            portfolio=portfolio,
            construction=base_result.construction,
        )
        lifecycle = self.lifecycle_engine.build(
            as_of=portfolio.as_of,
            candidates=candidates,
            decisions=base_result.decisions,
            theses=base_result.theses,
            expression_set=view_expressions,
            portfolio=portfolio,
            construction=base_result.construction,
        )
        reactive = self.reactive_engine.build(
            posture=posture,
            expression_set=view_expressions,
            lifecycle=lifecycle,
        )
        accountability = self.accountability_engine.build(
            posture=posture,
            alternatives=alternatives,
            candidates=candidates,
            decisions=base_result.decisions,
            construction=base_result.construction,
        )
        advanced_shadow = self.advanced_shadow_coordinator.observe_cycle(
            cycle_identifier=str(identifier),
            as_of=portfolio.as_of,
            code_version=str(code_version),
            candidate_count=len(candidates),
            specialist_context_count=len(specialist_contexts),
            decision_count=len(base_result.decisions),
            alternative_count=len(alternatives.alternatives),
            posture_identifier=posture.identifier,
        )
        if self.allocation_store is not None:
            self.allocation_store.append(
                cycle_identifier=str(identifier),
                posture=posture,
                alternatives=alternatives,
                code_version=str(code_version),
            )
        if self.advanced_shadow_store is not None:
            self.advanced_shadow_store.append(advanced_shadow)
        if self.active_investor_store is not None:
            self.active_investor_store.append_cycle(
                cycle_identifier=str(identifier),
                expressions=view_expressions,
                lifecycle=lifecycle,
                reactive=reactive,
                accountability=accountability,
                code_version=str(code_version),
            )
        return CompoundingCanonicalCIOCycleResult(
            base_result=base_result,
            portfolio_posture=posture,
            view_expressions=view_expressions,
            portfolio_alternatives=alternatives,
            position_lifecycle=lifecycle,
            reactive_monitoring=reactive,
            compounding_accountability=accountability,
            advanced_intelligence_shadow=advanced_shadow,
        )


__all__ = [
    "CompoundingCanonicalCIOCycle",
    "CompoundingCanonicalCIOCycleResult",
]
