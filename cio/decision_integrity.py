"""Final semantic normalization for canonical CIO decisions."""

from __future__ import annotations

from dataclasses import replace

from cio.models import CIOAction, CIODecision
from cio.service import ChiefInvestmentOfficer as _ChiefInvestmentOfficer


_ZERO_WEIGHT_TOLERANCE = 0.00000001


def normalize_final_decision(decision: CIODecision) -> CIODecision:
    """Represent a complete liquidation as EXIT rather than REDUCE-to-zero."""

    if not isinstance(decision, CIODecision):
        raise TypeError("decision must be a CIODecision")
    target = decision.recommended_position_weight
    if (
        decision.action is CIOAction.REDUCE
        and target is not None
        and target <= _ZERO_WEIGHT_TOLERANCE
    ):
        return replace(
            decision,
            action=CIOAction.EXIT,
            recommended_position_weight=0.0,
            thesis=decision.thesis.replace("Reduce ", "Exit ", 1),
            rationale=(
                decision.rationale
                + " The final governed target is zero, so the action is normalized "
                "to a complete exit."
            ),
            portfolio_impact=(
                "Exit toward a 0.00% portfolio weight, subject to final execution controls."
            ),
            explanation=decision.explanation.replace(
                "CIO decision: reduce.",
                "CIO decision: exit.",
            ),
        )
    return decision


class ChiefInvestmentOfficer(_ChiefInvestmentOfficer):
    """Canonical CIO service with final action-state normalization."""

    def synthesize(self, *args, **kwargs) -> CIODecision:
        return normalize_final_decision(super().synthesize(*args, **kwargs))


__all__ = ["ChiefInvestmentOfficer", "normalize_final_decision"]
