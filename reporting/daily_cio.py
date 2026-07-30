"""User-facing Daily Capital Intelligence briefing from canonical CIO results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from cio import CIOAction, CIODecision
from opportunity import OpportunityQueue
from portfolio.construction_api import (
    ConstructionStatus,
    PortfolioConstructionResult,
)
from thesis import LivingThesis


class DailyCIOStatus(str, Enum):
    CURRENT = "current"
    NO_SUPERIOR_OPPORTUNITY = "no_superior_opportunity"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    IMPLEMENTATION_BLOCKED = "implementation_blocked"
    UNAVAILABLE = "unavailable"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text_tuple(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    return tuple(dict.fromkeys(normalized))


@dataclass(frozen=True, slots=True)
class DailyCIOBriefing:
    """One coherent CIO briefing without exposing committee mechanics by default."""

    identifier: str
    as_of: datetime
    status: DailyCIOStatus
    what_changed: str
    why_it_matters: str
    opportunity_or_risk: str
    portfolio_decision: str
    confidence: float | None
    evidence_that_changes_conclusion: tuple[str, ...]
    material_developments: tuple[str, ...]
    candidate_identifier: str | None = None
    decision_identifier: str | None = None
    construction_status: ConstructionStatus | None = None
    thesis_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "what_changed",
            "why_it_matters",
            "opportunity_or_risk",
            "portfolio_decision",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.status, DailyCIOStatus):
            raise TypeError("status must be a DailyCIOStatus")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(
                self.confidence,
                (int, float),
            ):
                raise TypeError("confidence must be numeric or None")
            normalized = float(self.confidence)
            if not 0.0 <= normalized <= 1.0:
                raise ValueError("confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", round(normalized, 8))
        for field_name, minimum in (
            ("evidence_that_changes_conclusion", 1),
            ("material_developments", 1),
            ("thesis_identifiers", 0),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        for field_name in ("candidate_identifier", "decision_identifier"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _required_text(value, field_name=field_name),
                )
        if self.construction_status is not None and not isinstance(
            self.construction_status,
            ConstructionStatus,
        ):
            raise TypeError(
                "construction_status must be ConstructionStatus or None"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "status": self.status.value,
            "what_changed": self.what_changed,
            "why_it_matters": self.why_it_matters,
            "opportunity_or_risk": self.opportunity_or_risk,
            "portfolio_decision": self.portfolio_decision,
            "confidence": self.confidence,
            "evidence_that_changes_conclusion": list(
                self.evidence_that_changes_conclusion
            ),
            "material_developments": list(self.material_developments),
            "candidate_identifier": self.candidate_identifier,
            "decision_identifier": self.decision_identifier,
            "construction_status": (
                None
                if self.construction_status is None
                else self.construction_status.value
            ),
            "thesis_identifiers": list(self.thesis_identifiers),
        }

    def to_markdown(self) -> str:
        confidence = (
            "Not applicable"
            if self.confidence is None
            else f"{self.confidence:.0%}"
        )
        developments = "\n".join(
            f"- {item}" for item in self.material_developments
        )
        change_conditions = "\n".join(
            f"- {item}" for item in self.evidence_that_changes_conclusion
        )
        return (
            "# Daily Capital Intelligence\n\n"
            f"**Status:** {self.status.value.replace('_', ' ').title()}  \n"
            f"**Confidence:** {confidence}\n\n"
            f"## What changed?\n{self.what_changed}\n\n"
            f"## Why does it matter?\n{self.why_it_matters}\n\n"
            f"## Opportunity or risk\n{self.opportunity_or_risk}\n\n"
            f"## Should the portfolio change?\n{self.portfolio_decision}\n\n"
            f"## Material developments\n{developments}\n\n"
            f"## Evidence that would change the conclusion\n{change_conditions}\n"
        )


class DailyCIOBriefingBuilder:
    """Translate canonical decisions into the restrained daily user experience."""

    _ACTIONABLE = {
        CIOAction.BUY,
        CIOAction.INCREASE,
        CIOAction.REDUCE,
        CIOAction.EXIT,
    }

    def build(
        self,
        *,
        as_of: datetime,
        queue: OpportunityQueue,
        decisions: tuple[CIODecision, ...],
        construction: PortfolioConstructionResult | None,
        theses: tuple[LivingThesis, ...],
    ) -> DailyCIOBriefing:
        _aware(as_of, field_name="as_of")
        if not isinstance(queue, OpportunityQueue):
            raise TypeError("queue must be an OpportunityQueue")
        if not isinstance(decisions, tuple) or not all(
            isinstance(item, CIODecision) for item in decisions
        ):
            raise TypeError("decisions must contain CIODecision values")
        if construction is not None and not isinstance(
            construction,
            PortfolioConstructionResult,
        ):
            raise TypeError(
                "construction must be PortfolioConstructionResult or None"
            )
        if not isinstance(theses, tuple) or not all(
            isinstance(item, LivingThesis) for item in theses
        ):
            raise TypeError("theses must contain LivingThesis values")

        if not queue.ranked:
            rejection_reasons = tuple(
                reason
                for rejected in queue.rejected
                for reason in rejected.reasons
            )
            evidence_limited_terms = (
                "insufficient evidence",
                "evidence quality",
                "stale data",
                "data is stale",
                "missing",
                "incomplete",
                "analytical coverage",
                "coverage is below",
                "unavailable",
                "uncertified",
                "unapproved",
            )
            evidence_incomplete = not queue.rejected or any(
                term in reason.lower()
                for reason in rejection_reasons
                for term in evidence_limited_terms
            )
            if evidence_incomplete:
                return DailyCIOBriefing(
                    identifier=f"daily-cio:{as_of.isoformat()}",
                    as_of=as_of,
                    status=DailyCIOStatus.INSUFFICIENT_EVIDENCE,
                    what_changed=(
                        "The governed review did not produce a complete candidate evidence set."
                    ),
                    why_it_matters=(
                        "The CIO cannot conclude that cash or current holdings are superior when one or more eligible instruments were not supported by decision-complete evidence."
                    ),
                    opportunity_or_risk=(
                        "No portfolio action is authorized until comparative candidate evidence is complete."
                    ),
                    portfolio_decision="No portfolio action is permitted.",
                    confidence=None,
                    evidence_that_changes_conclusion=(
                        rejection_reasons
                        or (
                            "Produce certified candidate evidence for the complete governed review set",
                        )
                    ),
                    material_developments=(
                        "The comparative opportunity set is incomplete",
                    ),
                    thesis_identifiers=tuple(
                        item.identifier for item in theses
                    ),
                )
            return DailyCIOBriefing(
                identifier=f"daily-cio:{as_of.isoformat()}",
                as_of=as_of,
                status=DailyCIOStatus.NO_SUPERIOR_OPPORTUNITY,
                what_changed=(
                    "No candidate cleared the governed opportunity qualification process."
                ),
                why_it_matters=(
                    "Cash and current holdings remain preferable to the screened alternatives after evidence, cost, downside, liquidity, and opportunity-cost controls."
                ),
                opportunity_or_risk=(
                    "No superior evidence-supported use of capital is available."
                ),
                portfolio_decision="No portfolio action is required.",
                confidence=None,
                evidence_that_changes_conclusion=rejection_reasons,
                material_developments=(
                    "The governed review queue contains no qualified opportunity",
                ),
                thesis_identifiers=tuple(
                    item.identifier for item in theses
                ),
            )

        primary = next(
            (
                item
                for item in decisions
                if item.action in self._ACTIONABLE
            ),
            decisions[0] if decisions else None,
        )
        if primary is None:
            return DailyCIOBriefing(
                identifier=f"daily-cio:{as_of.isoformat()}",
                as_of=as_of,
                status=DailyCIOStatus.UNAVAILABLE,
                what_changed=(
                    "Qualified opportunities exist, but no CIO decision record is available."
                ),
                why_it_matters=(
                    "The platform cannot translate the opportunity queue into a capital-allocation conclusion without the governed CIO step."
                ),
                opportunity_or_risk="Decision synthesis is unavailable.",
                portfolio_decision="No portfolio action is permitted.",
                confidence=None,
                evidence_that_changes_conclusion=(
                    "Complete all six specialist analyses and CIO synthesis",
                ),
                material_developments=(
                    "Qualified opportunities are awaiting CIO synthesis",
                ),
            )

        top = next(
            item
            for item in queue.ranked
            if item.candidate.identifier == primary.candidate_identifier
        )
        status = self._status(primary, construction)
        portfolio_decision = self._portfolio_decision(
            primary,
            construction,
        )
        change_conditions = tuple(
            dict.fromkeys(
                primary.invalidation_conditions
                + (
                    ()
                    if primary.dissent is None
                    else primary.dissent.resolving_evidence
                )
                + primary.evidence_vetoes
                + primary.implementation_blocks
            )
        ) or ("Material new evidence changes expected return or downside",)
        material = tuple(
            dict.fromkeys(
                (
                    top.candidate.primary_catalysts[0],
                    f"Cost-adjusted expected return is {top.candidate.net_expected_return:.2%}",
                    f"Opportunity edge is {top.qualification.opportunity_edge:.2%}",
                    f"CIO action is {primary.action.value.replace('_', ' ')}",
                )
            )
        )
        return DailyCIOBriefing(
            identifier=f"daily-cio:{as_of.isoformat()}",
            as_of=as_of,
            status=status,
            what_changed=top.candidate.primary_catalysts[0],
            why_it_matters=(
                f"The candidate offers a {top.candidate.net_expected_return:.2%} "
                f"cost-adjusted expected return versus a "
                f"{top.qualification.effective_opportunity_cost:.2%} alternative, "
                f"with {top.candidate.expected_downside:.2%} expected downside."
            ),
            opportunity_or_risk=(
                f"{top.candidate.instrument.symbol} is ranked #{top.rank}; "
                f"the central risk is {primary.risks[0]}"
            ),
            portfolio_decision=portfolio_decision,
            confidence=primary.final_confidence,
            evidence_that_changes_conclusion=change_conditions,
            material_developments=material,
            candidate_identifier=primary.candidate_identifier,
            decision_identifier=primary.identifier,
            construction_status=(
                None if construction is None else construction.status
            ),
            thesis_identifiers=tuple(
                item.identifier for item in theses
            ),
        )

    @staticmethod
    def _status(
        decision: CIODecision,
        construction: PortfolioConstructionResult | None,
    ) -> DailyCIOStatus:
        if decision.action is CIOAction.INSUFFICIENT_EVIDENCE:
            return DailyCIOStatus.INSUFFICIENT_EVIDENCE
        if construction is not None and construction.status is ConstructionStatus.BLOCKED:
            return DailyCIOStatus.IMPLEMENTATION_BLOCKED
        if decision.action is CIOAction.NO_SUPERIOR_OPPORTUNITY:
            return DailyCIOStatus.NO_SUPERIOR_OPPORTUNITY
        return DailyCIOStatus.CURRENT

    @staticmethod
    def _portfolio_decision(
        decision: CIODecision,
        construction: PortfolioConstructionResult | None,
    ) -> str:
        if construction is None or not construction.trades:
            return (
                f"CIO decision: {decision.action.value.replace('_', ' ')}. "
                "No executable portfolio change is proposed."
            )
        trades = ", ".join(
            f"{item.side.value} {item.symbol} from {item.from_weight:.2%} to {item.to_weight:.2%}"
            for item in construction.trades
        )
        return (
            f"CIO decision: {decision.action.value.replace('_', ' ')}. "
            f"Proposed implementation: {trades}. Estimated portfolio-level "
            f"cost is {construction.estimated_cost_return:.3%}."
        )


__all__ = [
    "DailyCIOBriefing",
    "DailyCIOBriefingBuilder",
    "DailyCIOStatus",
]
