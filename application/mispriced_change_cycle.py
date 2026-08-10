"""Production-cycle binding for governed mispriced-change synthesis.

The synthesis operates only on already-certified point-in-time forward evidence and
runs before the existing six specialists. It does not create candidates, change
qualification thresholds, alter CIO authority, construct positions, or authorize
real-money execution.
"""
from __future__ import annotations

from dataclasses import replace

from application.compounding_cycle import CompoundingCanonicalCIOCycle
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
    """Run the compounding cycle with adaptive interaction evidence for specialists."""

    def run(self, **kwargs):
        contexts = kwargs.get("specialist_contexts")
        if not isinstance(contexts, tuple):
            raise TypeError("specialist_contexts must be supplied as a tuple")
        return super().run(
            **{
                **kwargs,
                "specialist_contexts": enrich_mispriced_change_contexts(contexts),
            }
        )


__all__ = [
    "MispricedChangeCanonicalCIOCycle",
    "enrich_mispriced_change_contexts",
]
