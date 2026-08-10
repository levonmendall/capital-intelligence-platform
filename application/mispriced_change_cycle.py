"""Production-cycle binding for governed mispriced-change synthesis.

The synthesis operates only on already-certified point-in-time forward evidence and
runs before the existing six specialists. It does not create candidates, change
qualification thresholds, alter CIO authority, construct final positions, or
authorize real-money execution. Before final CIO synthesis, the existing construction
engine also produces one simultaneous non-executing portfolio preview so positive
CIO sizing can account for joint feasibility rather than isolated candidates alone.
"""
from __future__ import annotations

from dataclasses import replace

from application.compounding_cycle import CompoundingCanonicalCIOCycle
from application.joint_portfolio_preview import build_joint_portfolio_preview
from intelligence.mispriced_change import enrich_bundle_with_mispriced_change


def enrich_mispriced_change_contexts(contexts: tuple[object, ...]) -> tuple[object, ...]:
    """Attach the advisory synthesis to existing candidate contexts idempotently."""

    if not isinstance(contexts, tuple):
        raise TypeError("specialist_contexts must be supplied as a tuple")
    enriched: list[object] = []
    for context in contexts:
        bundle = getattr(context, "forward_intelligence", None)
        if bundle is None:
            enriched.append(context)
            continue
        enriched.append(
            replace(
                context,
                forward_intelligence=enrich_bundle_with_mispriced_change(bundle),
            )
        )
    return tuple(enriched)


class MispricedChangeCanonicalCIOCycle(CompoundingCanonicalCIOCycle):
    """Run compounding intelligence with a joint pre-CIO construction preview."""

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

        preview = build_joint_portfolio_preview(
            cycle_identifier=str(kwargs.get("identifier", "unknown")),
            candidates=candidates,
            portfolio=portfolio,
            construction_engine=self.construction_engine,
            authoritative_queue=kwargs.get("authoritative_opportunity_queue"),
        )
        setter = getattr(self.cio, "set_joint_preview_context", None)
        clearer = getattr(self.cio, "clear_joint_preview_context", None)
        if callable(setter):
            setter(preview)
        try:
            return super().run(
                **{
                    **kwargs,
                    "specialist_contexts": enrich_mispriced_change_contexts(contexts),
                }
            )
        finally:
            if callable(clearer):
                clearer()


__all__ = [
    "MispricedChangeCanonicalCIOCycle",
    "enrich_mispriced_change_contexts",
]
