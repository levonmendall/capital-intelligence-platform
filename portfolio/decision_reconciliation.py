"""CIO-to-construction accountability for every governed candidate decision."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cio import CIOAction, CIODecision, CandidateDecisionRecord
from portfolio.construction_models import (
    ConstructionStatus,
    PortfolioConstructionResult,
)


class ConstructionDisposition(str, Enum):
    """Why the construction engine did or did not implement the CIO target."""

    NOT_ACTIONABLE = "not_actionable"
    NO_CONSTRUCTION = "no_construction"
    IMPLEMENTED_EXACTLY = "implemented_exactly"
    REDUCED_BY_CONSTRUCTION = "reduced_by_construction"
    ZEROED_AFTER_APPROVAL = "zeroed_after_approval"
    RISK_REDUCTION_IMPLEMENTED = "risk_reduction_implemented"
    RISK_REDUCTION_PARTIAL = "risk_reduction_partial"


@dataclass(frozen=True, slots=True)
class ConstructionDecisionReconciliation:
    """One immutable explanation of CIO target versus final portfolio target."""

    candidate_identifier: str
    decision_identifier: str
    symbol: str
    action: CIOAction
    prior_weight: float
    cio_target_weight: float | None
    final_target_weight: float
    target_delta: float | None
    disposition: ConstructionDisposition
    binding_constraints: tuple[str, ...]
    funding_conflict: bool
    displaced_by: tuple[str, ...]
    explanation: str

    @property
    def approved_positive_allocation(self) -> bool:
        return self.action in {CIOAction.BUY, CIOAction.INCREASE}

    @property
    def zeroed_after_approval(self) -> bool:
        return self.disposition is ConstructionDisposition.ZEROED_AFTER_APPROVAL

    @property
    def reduced_by_construction(self) -> bool:
        return self.disposition in {
            ConstructionDisposition.REDUCED_BY_CONSTRUCTION,
            ConstructionDisposition.RISK_REDUCTION_PARTIAL,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "decision_identifier": self.decision_identifier,
            "symbol": self.symbol,
            "action": self.action.value,
            "prior_weight": self.prior_weight,
            "cio_target_weight": self.cio_target_weight,
            "final_target_weight": self.final_target_weight,
            "target_delta": self.target_delta,
            "disposition": self.disposition.value,
            "binding_constraints": list(self.binding_constraints),
            "funding_conflict": self.funding_conflict,
            "displaced_by": list(self.displaced_by),
            "explanation": self.explanation,
        }


def _binding_constraints(
    construction: PortfolioConstructionResult | None,
) -> tuple[str, ...]:
    if construction is None:
        return ()
    values = list(construction.blocks)
    values.extend(
        f"{item.name}: {item.detail}"
        for item in construction.constraints
        if not item.satisfied
    )
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def reconcile_construction_decisions(
    *,
    decisions: tuple[CIODecision, ...],
    candidates: tuple[CandidateDecisionRecord, ...],
    construction: PortfolioConstructionResult | None,
    tolerance: float = 0.000001,
) -> tuple[ConstructionDecisionReconciliation, ...]:
    """Reconcile every CIO decision against the final constructed portfolio."""

    by_candidate = {item.identifier: item for item in candidates}
    if len(by_candidate) != len(candidates):
        raise ValueError("candidates must be unique")
    final_weights = (
        {} if construction is None else dict(construction.target_weights)
    )
    constraints = _binding_constraints(construction)
    funded_symbols = tuple(
        sorted(
            proposal.symbol
            for proposal in (() if construction is None else construction.trades)
            if proposal.to_weight > proposal.from_weight + tolerance
        )
    )
    values: list[ConstructionDecisionReconciliation] = []
    for decision in decisions:
        candidate = by_candidate.get(decision.candidate_identifier)
        if candidate is None:
            raise KeyError(
                f"missing candidate for decision {decision.candidate_identifier}"
            )
        symbol = candidate.instrument.symbol
        prior = candidate.current_portfolio_weight
        requested = decision.recommended_position_weight
        if construction is None:
            final = prior
        elif symbol in final_weights:
            final = final_weights[symbol]
        elif prior > 0.0 and decision.action not in {CIOAction.EXIT}:
            final = prior
        else:
            final = 0.0
        actionable = decision.action in {
            CIOAction.BUY,
            CIOAction.INCREASE,
            CIOAction.REDUCE,
            CIOAction.EXIT,
        }
        if not actionable:
            disposition = ConstructionDisposition.NOT_ACTIONABLE
            explanation = (
                "The CIO issued no portfolio-changing action, so construction had no "
                "target to implement."
            )
        elif construction is None:
            disposition = ConstructionDisposition.NO_CONSTRUCTION
            explanation = (
                "The CIO issued an actionable decision, but no final construction "
                "result was produced."
            )
        elif decision.action in {CIOAction.BUY, CIOAction.INCREASE}:
            expected = requested or 0.0
            if final <= tolerance and expected > tolerance:
                disposition = ConstructionDisposition.ZEROED_AFTER_APPROVAL
                explanation = (
                    "The CIO approved a positive target, but final portfolio "
                    "construction assigned no position."
                )
            elif final + tolerance < expected:
                disposition = ConstructionDisposition.REDUCED_BY_CONSTRUCTION
                explanation = (
                    "Final portfolio construction reduced the CIO-approved target "
                    "because portfolio-level constraints or competing allocations bound."
                )
            else:
                disposition = ConstructionDisposition.IMPLEMENTED_EXACTLY
                explanation = (
                    "Final portfolio construction preserved the CIO-approved target."
                )
        else:
            expected = 0.0 if decision.action is CIOAction.EXIT else (requested or prior)
            if abs(final - expected) <= tolerance:
                disposition = ConstructionDisposition.RISK_REDUCTION_IMPLEMENTED
                explanation = (
                    "Final portfolio construction implemented the CIO risk-reducing target."
                )
            else:
                disposition = ConstructionDisposition.RISK_REDUCTION_PARTIAL
                explanation = (
                    "Final portfolio construction implemented only part of the CIO "
                    "risk-reducing target."
                )
        target_delta = None if requested is None else round(final - requested, 8)
        funding_conflict = any(
            token in detail.lower()
            for detail in constraints
            for token in ("cash", "fund", "turnover", "cost", "liquidity")
        ) or (
            disposition is ConstructionDisposition.ZEROED_AFTER_APPROVAL
            and construction is not None
            and construction.status is ConstructionStatus.PARTIAL
        )
        displaced_by = (
            tuple(item for item in funded_symbols if item != symbol)
            if disposition is ConstructionDisposition.ZEROED_AFTER_APPROVAL
            else ()
        )
        values.append(
            ConstructionDecisionReconciliation(
                candidate_identifier=candidate.identifier,
                decision_identifier=decision.identifier,
                symbol=symbol,
                action=decision.action,
                prior_weight=round(prior, 8),
                cio_target_weight=requested,
                final_target_weight=round(final, 8),
                target_delta=target_delta,
                disposition=disposition,
                binding_constraints=constraints,
                funding_conflict=funding_conflict,
                displaced_by=displaced_by,
                explanation=explanation,
            )
        )
    return tuple(values)


__all__ = [
    "ConstructionDecisionReconciliation",
    "ConstructionDisposition",
    "reconcile_construction_decisions",
]
