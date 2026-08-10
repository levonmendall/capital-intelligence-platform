"""Production canonical cycle for global opportunity rotation.

The cycle enriches already-governed candidates with mispriced-change and corroborated
global-leadership economics, builds one cross-asset marginal-capital context, and
supplies it to the existing CIO. Final construction and paper execution are unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from application.compounding_cycle import (
    CompoundingCanonicalCIOCycle,
    CompoundingCanonicalCIOCycleResult,
)
from application.global_rotation_preview import build_global_rotation_preview
from cio.global_rotation_authority import GlobalRotationChiefInvestmentOfficer
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from intelligence.global_leadership import enrich_bundle_with_global_leadership_economics
from intelligence.mispriced_change import enrich_bundle_with_mispriced_change
from portfolio.global_rotation import GlobalRotationContext, build_global_rotation_context
from portfolio.global_rotation_persistence import (
    GlobalCashAccountability,
    SQLiteGlobalRotationStore,
    build_global_cash_accountability,
)

_LOGGER = logging.getLogger("capital_intelligence.global_rotation")


def enrich_global_rotation_contexts(contexts: tuple[object, ...]) -> tuple[object, ...]:
    """Attach one idempotent forward/mispricing/leadership synthesis per candidate."""

    if not isinstance(contexts, tuple):
        raise TypeError("specialist_contexts must be supplied as a tuple")
    result: list[object] = []
    for context in contexts:
        bundle = getattr(context, "forward_intelligence", None)
        if bundle is None:
            result.append(context)
            continue
        enriched = enrich_bundle_with_mispriced_change(bundle)
        enriched = enrich_bundle_with_global_leadership_economics(enriched)
        result.append(replace(context, forward_intelligence=enriched))
    return tuple(result)


class GlobalOpportunityRotationCanonicalCIOCycleResult(CompoundingCanonicalCIOCycleResult):
    """Canonical compounding result plus global rotation/cash accountability."""

    __slots__ = ("global_rotation_context", "global_cash_accountability")

    def __init__(
        self,
        *,
        base_result: CompoundingCanonicalCIOCycleResult,
        global_rotation_context: GlobalRotationContext,
        global_cash_accountability: GlobalCashAccountability,
    ) -> None:
        if not isinstance(base_result, CompoundingCanonicalCIOCycleResult):
            raise TypeError("base_result must be CompoundingCanonicalCIOCycleResult")
        if not isinstance(global_rotation_context, GlobalRotationContext):
            raise TypeError("global_rotation_context must be GlobalRotationContext")
        if not isinstance(global_cash_accountability, GlobalCashAccountability):
            raise TypeError("global_cash_accountability must be GlobalCashAccountability")
        super().__init__(
            base_result=base_result,
            portfolio_posture=base_result.portfolio_posture,
            view_expressions=base_result.view_expressions,
            portfolio_alternatives=base_result.portfolio_alternatives,
            position_lifecycle=base_result.position_lifecycle,
            reactive_monitoring=base_result.reactive_monitoring,
            compounding_accountability=base_result.compounding_accountability,
            advanced_intelligence_shadow=base_result.advanced_intelligence_shadow,
        )
        object.__setattr__(self, "global_rotation_context", global_rotation_context)
        object.__setattr__(
            self,
            "global_cash_accountability",
            global_cash_accountability,
        )


class GlobalOpportunityRotationCanonicalCIOCycle(CompoundingCanonicalCIOCycle):
    """Run the six-specialist/CIO process with global marginal-capital context."""

    def __init__(
        self,
        *,
        cio=None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
        global_rotation_store: SQLiteGlobalRotationStore | None = None,
        **kwargs,
    ) -> None:
        opportunity_engine = kwargs.get("opportunity_engine")
        authority = (
            policy_authority
            or getattr(cio, "policy_authority", None)
            or getattr(opportunity_engine, "policy_authority", None)
            or CanonicalDecisionPolicyAuthority()
        )
        resolved_cio = cio or GlobalRotationChiefInvestmentOfficer(
            policy_authority=authority
        )
        super().__init__(
            cio=resolved_cio,
            policy_authority=authority,
            **kwargs,
        )
        self.global_rotation_store = global_rotation_store
        if self.global_rotation_store is None and self.journal is not None:
            self.global_rotation_store = SQLiteGlobalRotationStore(self.journal.path)

    def run(self, **kwargs) -> GlobalOpportunityRotationCanonicalCIOCycleResult:
        contexts = kwargs.get("specialist_contexts")
        candidates = kwargs.get("candidates")
        portfolio = kwargs.get("portfolio")
        cycle_identifier = str(kwargs.get("identifier", "unknown"))
        code_version = str(kwargs.get("code_version") or "unknown")
        if not isinstance(contexts, tuple):
            raise TypeError("specialist_contexts must be supplied as a tuple")
        if not isinstance(candidates, tuple):
            raise TypeError("candidates must be supplied as a tuple")
        if portfolio is None:
            raise TypeError("portfolio must be supplied")

        enriched_contexts = enrich_global_rotation_contexts(contexts)
        rotation_context = build_global_rotation_context(
            candidates=candidates,
            specialist_contexts=enriched_contexts,
            portfolio=portfolio,
            minimum_cash_weight=self.construction_engine.policy.minimum_cash_weight,
        )
        setter = getattr(self.cio, "set_global_rotation_context", None)
        clearer = getattr(self.cio, "clear_global_rotation_context", None)
        if callable(setter):
            setter(rotation_context)

        preview = None
        try:
            preview = build_global_rotation_preview(
                cycle_identifier=cycle_identifier,
                candidates=candidates,
                portfolio=portfolio,
                construction_engine=self.construction_engine,
                rotation_context=rotation_context,
                authoritative_queue=kwargs.get("authoritative_opportunity_queue"),
            )
        except Exception:
            # Additional portfolio context must never become a hidden veto. The final
            # constructor still fails closed after the CIO makes any positive decision.
            _LOGGER.exception(
                "global joint portfolio preview unavailable for %s; continuing without pre-CIO cap",
                cycle_identifier,
            )
        preview_setter = getattr(self.cio, "set_joint_preview_context", None)
        preview_clearer = getattr(self.cio, "clear_joint_preview_context", None)
        if preview is not None and callable(preview_setter):
            preview_setter(preview)
        try:
            base_result = super().run(
                **{
                    **kwargs,
                    "specialist_contexts": enriched_contexts,
                }
            )
            accountability = build_global_cash_accountability(
                cycle_identifier=cycle_identifier,
                context=rotation_context,
                result=base_result,
            )
            if self.global_rotation_store is not None:
                self.global_rotation_store.append(
                    cycle_identifier=cycle_identifier,
                    context=rotation_context,
                    accountability=accountability,
                    code_version=code_version,
                )
            return GlobalOpportunityRotationCanonicalCIOCycleResult(
                base_result=base_result,
                global_rotation_context=rotation_context,
                global_cash_accountability=accountability,
            )
        finally:
            if callable(preview_clearer):
                preview_clearer()
            if callable(clearer):
                clearer()


__all__ = [
    "GlobalOpportunityRotationCanonicalCIOCycle",
    "GlobalOpportunityRotationCanonicalCIOCycleResult",
    "enrich_global_rotation_contexts",
]
