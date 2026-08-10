"""Production canonical cycle for global opportunity rotation.

The cycle enriches already-governed candidates with mispriced-change and corroborated
global-leadership economics, builds one cross-asset marginal-capital context, and
supplies it to the existing CIO. Final construction and paper execution are unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from application.compounding_cycle import CompoundingCanonicalCIOCycle
from application.global_rotation_preview import build_global_rotation_preview
from cio.global_rotation_authority import GlobalRotationChiefInvestmentOfficer
from cio.policy_authority import CanonicalDecisionPolicyAuthority
from intelligence.global_leadership import enrich_bundle_with_global_leadership_economics
from intelligence.mispriced_change import enrich_bundle_with_mispriced_change
from portfolio.global_rotation import build_global_rotation_context

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


class GlobalOpportunityRotationCanonicalCIOCycle(CompoundingCanonicalCIOCycle):
    """Run the six-specialist/CIO process with global marginal-capital context."""

    def __init__(
        self,
        *,
        cio=None,
        policy_authority: CanonicalDecisionPolicyAuthority | None = None,
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

    def run(self, **kwargs):
        contexts = kwargs.get("specialist_contexts")
        candidates = kwargs.get("candidates")
        portfolio = kwargs.get("portfolio")
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
                cycle_identifier=str(kwargs.get("identifier", "unknown")),
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
                kwargs.get("identifier", "unknown"),
            )
        preview_setter = getattr(self.cio, "set_joint_preview_context", None)
        preview_clearer = getattr(self.cio, "clear_joint_preview_context", None)
        if preview is not None and callable(preview_setter):
            preview_setter(preview)
        try:
            return super().run(
                **{
                    **kwargs,
                    "specialist_contexts": enriched_contexts,
                }
            )
        finally:
            if callable(preview_clearer):
                preview_clearer()
            if callable(clearer):
                clearer()


__all__ = [
    "GlobalOpportunityRotationCanonicalCIOCycle",
    "enrich_global_rotation_contexts",
]
