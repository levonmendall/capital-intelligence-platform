"""Value-of-information prioritization for missing candidate evidence.

The purpose is to decide what research to resolve next, not to increase conviction or
manufacture a trade. Missing information is ranked by its potential to change a
portfolio decision, its current uncertainty, and whether it is realistically
resolvable before the candidate's decision horizon.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from governance.decision_readiness import CandidateDecisionReadiness
from intelligence.asset_underwriting import UnderwritingDimension


_BASE_DECISION_IMPACT: dict[UnderwritingDimension, float] = {
    UnderwritingDimension.IDENTITY: 1.00,
    UnderwritingDimension.MARKET_DATA: 0.95,
    UnderwritingDimension.LIQUIDITY: 0.90,
    UnderwritingDimension.MACRO: 0.60,
    UnderwritingDimension.FUNDAMENTALS: 0.85,
    UnderwritingDimension.VALUATION: 0.90,
    UnderwritingDimension.CARRY: 0.80,
    UnderwritingDimension.CURVE: 0.80,
    UnderwritingDimension.CREDIT: 0.95,
    UnderwritingDimension.CURRENCY: 0.75,
    UnderwritingDimension.PHYSICAL_BALANCE: 0.95,
    UnderwritingDimension.POSITIONING: 0.55,
    UnderwritingDimension.ONCHAIN: 0.95,
    UnderwritingDimension.DERIVATIVES: 0.95,
    UnderwritingDimension.CASH_FLOW: 0.90,
    UnderwritingDimension.CORPORATE_ACTIONS: 0.55,
    UnderwritingDimension.HISTORY: 0.80,
    UnderwritingDimension.EXECUTION: 1.00,
}


@dataclass(frozen=True, slots=True)
class MissingInformationInput:
    dimension: UnderwritingDimension
    uncertainty: float
    probability_resolvable: float
    time_relevance: float
    independent_source_gain: float
    estimated_acquisition_cost: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, UnderwritingDimension):
            raise TypeError("dimension must be UnderwritingDimension")
        for name in (
            "uncertainty",
            "probability_resolvable",
            "time_relevance",
            "independent_source_gain",
            "estimated_acquisition_cost",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be between zero and one")


@dataclass(frozen=True, slots=True)
class InformationAcquisitionPriority:
    candidate_identifier: str
    dimension: UnderwritingDimension
    priority_score: float
    blocking: bool
    rationale: tuple[str, ...]
    authorizes_capital: bool = False
    schema_version: str = "information-acquisition-priority.v1"


class ValueOfInformationEngine:
    version = "value-of-information.v1"

    def prioritize(
        self,
        *,
        readiness: CandidateDecisionReadiness,
        inputs: tuple[MissingInformationInput, ...] = (),
    ) -> tuple[InformationAcquisitionPriority, ...]:
        if not isinstance(readiness, CandidateDecisionReadiness):
            raise TypeError("readiness must be CandidateDecisionReadiness")
        missing = tuple(readiness.coverage.missing)
        supplied = {item.dimension: item for item in inputs}
        if len(supplied) != len(inputs):
            raise ValueError("missing-information inputs must be unique by dimension")
        unknown = set(supplied).difference(missing)
        if unknown:
            raise ValueError("value-of-information inputs must refer to missing dimensions")
        blocking = set(readiness.blocking_missing)
        priorities: list[InformationAcquisitionPriority] = []
        for dimension in missing:
            item = supplied.get(
                dimension,
                MissingInformationInput(
                    dimension=dimension,
                    uncertainty=1.0,
                    probability_resolvable=0.50,
                    time_relevance=0.75,
                    independent_source_gain=0.50,
                ),
            )
            impact = _BASE_DECISION_IMPACT[dimension]
            blocking_multiplier = 1.25 if dimension in blocking else 1.0
            information_value = (
                impact
                * float(item.uncertainty)
                * float(item.probability_resolvable)
                * float(item.time_relevance)
                * (0.75 + 0.25 * float(item.independent_source_gain))
                * blocking_multiplier
            )
            score = max(
                0.0,
                min(1.0, information_value - 0.20 * float(item.estimated_acquisition_cost)),
            )
            priorities.append(
                InformationAcquisitionPriority(
                    candidate_identifier=readiness.candidate_identifier,
                    dimension=dimension,
                    priority_score=round(score, 8),
                    blocking=dimension in blocking,
                    rationale=(
                        f"base decision impact={impact:.0%}",
                        f"uncertainty={float(item.uncertainty):.0%}",
                        f"resolvable probability={float(item.probability_resolvable):.0%}",
                        f"time relevance={float(item.time_relevance):.0%}",
                        "critical decision-readiness blocker" if dimension in blocking else "completeness enhancement",
                    ),
                )
            )
        return tuple(
            sorted(
                priorities,
                key=lambda value: (
                    value.blocking,
                    value.priority_score,
                    value.dimension.value,
                ),
                reverse=True,
            )
        )


__all__ = [
    "InformationAcquisitionPriority",
    "MissingInformationInput",
    "ValueOfInformationEngine",
]
