"""Prospective compounding accountability with explicit authority separation.

Actual selected-construction metrics remain tied to the independently constructed
portfolio. Cash opportunity cost is a different diagnostic: it measures the strongest
advisory alternative against cash without representing that alternative as selected,
approved, constructible, or executable.
"""

from __future__ import annotations

from dataclasses import replace

from portfolio.active_investor import (
    CompoundingAccountabilityEngine,
    CompoundingAccountabilitySnapshot,
)


class ProspectiveCompoundingAccountabilityEngine(
    CompoundingAccountabilityEngine
):
    version = "compounding-accountability-engine.v2-advisory-opportunity"

    def build(self, *, alternatives, **kwargs) -> CompoundingAccountabilitySnapshot:
        snapshot = super().build(alternatives=alternatives, **kwargs)
        cash = next(
            (
                item
                for item in alternatives.alternatives
                if item.kind.value == "all_cash"
            ),
            None,
        )
        best = max(
            alternatives.alternatives,
            key=lambda item: (
                item.estimated_compound_return,
                item.estimated_annualized_return_after_cost,
                -item.cash_weight,
            ),
        )
        cash_return = 0.0 if cash is None else float(cash.estimated_compound_return)
        return replace(
            snapshot,
            cash_opportunity_cost=max(
                0.0,
                float(best.estimated_compound_return) - cash_return,
            ),
            limitations=tuple(
                dict.fromkeys(
                    (
                        *snapshot.limitations,
                        "Cash opportunity cost compares the strongest advisory portfolio alternative with cash; it does not represent CIO selection, construction feasibility, or an executable target",
                    )
                )
            ),
            model_version="compounding-accountability.v2-advisory-opportunity",
        )


__all__ = ["ProspectiveCompoundingAccountabilityEngine"]
