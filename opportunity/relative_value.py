"""Governed multi-leg relative-value opportunity contracts.

Relative-value expressions are candidate structures, not a seventh specialist and not
an execution shortcut.  Every leg must remain inside the existing certified universe,
pass asset-specific decision readiness, and have an atomic paper implementation path
before a structure can be considered executable.  The structure itself never
authorizes capital.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class RelativeValueExpressionType(str, Enum):
    PAIR = "pair"
    CURVE = "curve"
    BASIS = "basis"
    CALENDAR_SPREAD = "calendar_spread"
    CREDIT_SPREAD = "credit_spread"
    HEDGED_CATALYST = "hedged_catalyst"
    VOLATILITY_SPREAD = "volatility_spread"
    CROSS_ASSET = "cross_asset"


class RelativeValueLegSide(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(frozen=True, slots=True)
class RelativeValueLeg:
    instrument_identifier: str
    symbol: str
    side: RelativeValueLegSide
    gross_weight: float
    expected_return: float
    implementation_cost_return: float
    financing_return: float
    liquidity_score: float
    decision_ready: bool
    paper_execution_certified: bool
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.instrument_identifier.strip() or not self.symbol.strip():
            raise ValueError("relative-value leg identity cannot be empty")
        if not isinstance(self.side, RelativeValueLegSide):
            raise TypeError("side must be RelativeValueLegSide")
        for name in (
            "gross_weight",
            "expected_return",
            "implementation_cost_return",
            "financing_return",
            "liquidity_score",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 < float(self.gross_weight) <= 1.0:
            raise ValueError("gross_weight must be between zero and one")
        if float(self.implementation_cost_return) < 0.0:
            raise ValueError("implementation_cost_return cannot be negative")
        if not 0.0 <= float(self.liquidity_score) <= 1.0:
            raise ValueError("liquidity_score must be between zero and one")
        if not isinstance(self.decision_ready, bool):
            raise TypeError("decision_ready must be bool")
        if not isinstance(self.paper_execution_certified, bool):
            raise TypeError("paper_execution_certified must be bool")
        if not self.evidence_identifiers:
            raise ValueError("relative-value legs require governed evidence")

    @property
    def signed_weight(self) -> float:
        sign = 1.0 if self.side is RelativeValueLegSide.LONG else -1.0
        return round(sign * float(self.gross_weight), 8)

    @property
    def net_expected_return_contribution(self) -> float:
        sign = 1.0 if self.side is RelativeValueLegSide.LONG else -1.0
        return round(
            float(self.gross_weight)
            * (
                sign * float(self.expected_return)
                + float(self.financing_return)
                - float(self.implementation_cost_return)
            ),
            8,
        )


@dataclass(frozen=True, slots=True)
class RelativeValueCandidateExpression:
    identifier: str
    as_of: datetime
    expression_type: RelativeValueExpressionType
    legs: tuple[RelativeValueLeg, ...]
    thesis: str
    base_case_return: float
    bull_case_return: float
    bear_case_return: float
    base_probability: float
    bull_probability: float
    bear_probability: float
    maximum_loss_return: float
    evidence_identifiers: tuple[str, ...]
    model_versions: tuple[str, ...]
    atomic_paper_execution_certified: bool = False
    investment_authority: bool = False
    real_money_authorized: bool = False
    schema_version: str = "relative-value-candidate-expression.v1"

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.thesis.strip():
            raise ValueError("relative-value identifier and thesis cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("relative-value as_of must be timezone-aware")
        if not isinstance(self.expression_type, RelativeValueExpressionType):
            raise TypeError("expression_type must be RelativeValueExpressionType")
        if len(self.legs) < 2 or not all(isinstance(item, RelativeValueLeg) for item in self.legs):
            raise ValueError("relative-value expressions require at least two governed legs")
        identifiers = tuple(item.instrument_identifier for item in self.legs)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("relative-value leg instruments must be unique")
        sides = {item.side for item in self.legs}
        if sides != {RelativeValueLegSide.LONG, RelativeValueLegSide.SHORT}:
            raise ValueError("relative-value expressions require both long and short legs")
        for name in (
            "base_case_return",
            "bull_case_return",
            "bear_case_return",
            "base_probability",
            "bull_probability",
            "bear_probability",
            "maximum_loss_return",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if not isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        probabilities = (
            float(self.base_probability),
            float(self.bull_probability),
            float(self.bear_probability),
        )
        if any(not 0.0 <= item <= 1.0 for item in probabilities):
            raise ValueError("scenario probabilities must be between zero and one")
        if abs(sum(probabilities) - 1.0) > 1e-6:
            raise ValueError("relative-value scenario probabilities must sum to one")
        if not -1.0 <= float(self.maximum_loss_return) <= 0.0:
            raise ValueError("maximum_loss_return must be between -1 and zero")
        if not self.evidence_identifiers or not self.model_versions:
            raise ValueError("relative-value expressions require evidence and model lineage")
        if self.atomic_paper_execution_certified and not all(
            item.paper_execution_certified for item in self.legs
        ):
            raise ValueError("atomic execution cannot be certified when a leg is uncertified")
        if self.investment_authority or self.real_money_authorized:
            raise ValueError("relative-value expressions cannot independently authorize capital")

    @property
    def all_legs_decision_ready(self) -> bool:
        return all(item.decision_ready for item in self.legs)

    @property
    def net_exposure(self) -> float:
        return round(sum(item.signed_weight for item in self.legs), 8)

    @property
    def gross_exposure(self) -> float:
        return round(sum(float(item.gross_weight) for item in self.legs), 8)

    @property
    def modeled_leg_return(self) -> float:
        return round(sum(item.net_expected_return_contribution for item in self.legs), 8)


@dataclass(frozen=True, slots=True)
class RelativeValueAdmission:
    candidate_identifier: str
    research_eligible: bool
    cio_review_eligible: bool
    paper_execution_eligible: bool
    reasons: tuple[str, ...]
    authorizes_capital: bool = False
    schema_version: str = "relative-value-admission.v1"


class RelativeValueAdmissionPolicy:
    version = "relative-value-admission-policy.v1"

    def assess(self, expression: RelativeValueCandidateExpression) -> RelativeValueAdmission:
        if not isinstance(expression, RelativeValueCandidateExpression):
            raise TypeError("expression must be RelativeValueCandidateExpression")
        reasons: list[str] = []
        research_eligible = bool(expression.evidence_identifiers)
        if not expression.all_legs_decision_ready:
            reasons.append("one or more legs fail asset-specific decision readiness")
        if not expression.atomic_paper_execution_certified:
            reasons.append("atomic multi-leg paper implementation is not certified")
        if any(not item.paper_execution_certified for item in expression.legs):
            reasons.append("one or more legs lack paper execution certification")
        cio_review_eligible = research_eligible and expression.all_legs_decision_ready
        paper_execution_eligible = bool(
            cio_review_eligible
            and expression.atomic_paper_execution_certified
            and all(item.paper_execution_certified for item in expression.legs)
        )
        if not reasons:
            reasons.append("all legs are decision-ready and atomic paper execution is certified")
        return RelativeValueAdmission(
            candidate_identifier=expression.identifier,
            research_eligible=research_eligible,
            cio_review_eligible=cio_review_eligible,
            paper_execution_eligible=paper_execution_eligible,
            reasons=tuple(reasons),
        )


__all__ = [
    "RelativeValueAdmission",
    "RelativeValueAdmissionPolicy",
    "RelativeValueCandidateExpression",
    "RelativeValueExpressionType",
    "RelativeValueLeg",
    "RelativeValueLegSide",
]
