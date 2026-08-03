"""Governed portfolio-posture, sleeve-search, and alternative-portfolio contracts.

This module changes the unit of investment reasoning from an isolated candidate to
capital allocation across competing sleeves.  It has no investment, construction,
execution, or real-money authority.  The CIO remains the only authority that may
issue a positive capital action, and independent portfolio construction remains the
only authority that may turn approved actions into feasible paper targets.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import exp, isfinite, log1p
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, Iterable, Mapping, Sequence

from cio.models import CandidateAssetClass


_EPSILON = 1e-9


def _text(value: object, *, field_name: str) -> str:
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


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _bounded(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=-1.0, maximum=1.0)


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


def _enum_tuple(
    value: object,
    *,
    field_name: str,
    enum_type: type[Enum],
) -> tuple[Enum, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    if not all(isinstance(item, enum_type) for item in value):
        raise TypeError(f"{field_name} must contain {enum_type.__name__} values")
    if len(value) != len(set(value)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return value


class PortfolioRegime(str, Enum):
    RISK_ON_GROWTH = "risk_on_growth"
    RISK_ON_DISINFLATION = "risk_on_disinflation"
    BALANCED_TRANSITION = "balanced_transition"
    RISK_OFF_RECESSION = "risk_off_recession"
    RISK_OFF_INFLATION = "risk_off_inflation"
    RISK_OFF_FUNDING_STRESS = "risk_off_funding_stress"


class PortfolioSleeve(str, Enum):
    PRODUCTIVE_RISK = "productive_risk"
    DEFENSIVE_INCOME = "defensive_income"
    DOLLAR_LIQUIDITY = "dollar_liquidity"
    INFLATION_REAL_ASSETS = "inflation_real_assets"
    DIVERSIFIERS = "diversifiers"
    ALTERNATIVES = "alternatives"


class PortfolioAlternativeKind(str, Enum):
    CURRENT = "current"
    ALL_CASH = "all_cash"
    POSTURE_CONSISTENT = "posture_consistent"
    PRODUCTIVE_RISK = "productive_risk"
    DEFENSIVE = "defensive"
    DIVERSIFIED_EXPLORATORY = "diversified_exploratory"
    SELECTED_CONSTRUCTION = "selected_construction"


@dataclass(frozen=True, slots=True)
class AllocationRange:
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "minimum", _ratio(self.minimum, field_name="minimum"))
        object.__setattr__(self, "maximum", _ratio(self.maximum, field_name="maximum"))
        if self.minimum > self.maximum:
            raise ValueError("allocation range minimum cannot exceed maximum")

    @property
    def midpoint(self) -> float:
        return round((self.minimum + self.maximum) / 2.0, 8)

    def to_dict(self) -> dict[str, float]:
        return {"minimum": self.minimum, "maximum": self.maximum}


@dataclass(frozen=True, slots=True)
class RegimeTransition:
    regime: PortfolioRegime
    probability: float
    rationale: str
    leading_indicators: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.regime, PortfolioRegime):
            raise TypeError("regime must be PortfolioRegime")
        object.__setattr__(self, "probability", _ratio(self.probability, field_name="probability"))
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))
        object.__setattr__(
            self,
            "leading_indicators",
            _texts(self.leading_indicators, field_name="leading_indicators", minimum=1),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "regime": self.regime.value,
            "probability": self.probability,
            "rationale": self.rationale,
            "leading_indicators": list(self.leading_indicators),
        }


@dataclass(frozen=True, slots=True)
class PortfolioPosture:
    identifier: str
    as_of: datetime
    regime: PortfolioRegime
    confidence: float
    risk_score: float
    productive_risk: AllocationRange
    defensive_income: AllocationRange
    dollar_liquidity: AllocationRange
    inflation_real_assets: AllocationRange
    diversifiers: AllocationRange
    preferred_sleeves: tuple[PortfolioSleeve, ...]
    discouraged_sleeves: tuple[PortfolioSleeve, ...]
    transitions: tuple[RegimeTransition, ...]
    evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    change_conditions: tuple[str, ...]
    model_version: str = "compounding-portfolio-posture.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.regime, PortfolioRegime):
            raise TypeError("regime must be PortfolioRegime")
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        object.__setattr__(self, "risk_score", _bounded(self.risk_score, field_name="risk_score"))
        for name in (
            "productive_risk",
            "defensive_income",
            "dollar_liquidity",
            "inflation_real_assets",
            "diversifiers",
        ):
            if not isinstance(getattr(self, name), AllocationRange):
                raise TypeError(f"{name} must be AllocationRange")
        object.__setattr__(
            self,
            "preferred_sleeves",
            _enum_tuple(
                self.preferred_sleeves,
                field_name="preferred_sleeves",
                enum_type=PortfolioSleeve,
            ),
        )
        object.__setattr__(
            self,
            "discouraged_sleeves",
            _enum_tuple(
                self.discouraged_sleeves,
                field_name="discouraged_sleeves",
                enum_type=PortfolioSleeve,
            ),
        )
        if set(self.preferred_sleeves).intersection(self.discouraged_sleeves):
            raise ValueError("a sleeve cannot be both preferred and discouraged")
        if not isinstance(self.transitions, tuple) or not all(
            isinstance(item, RegimeTransition) for item in self.transitions
        ):
            raise TypeError("transitions must contain RegimeTransition values")
        if not self.transitions:
            raise ValueError("portfolio posture requires regime transitions")
        if abs(sum(item.probability for item in self.transitions) - 1.0) > 0.000001:
            raise ValueError("regime transition probabilities must sum to 1.0")
        transition_regimes = tuple(item.regime for item in self.transitions)
        if len(transition_regimes) != len(set(transition_regimes)):
            raise ValueError("regime transition targets must be unique")
        for field_name, minimum in (
            ("evidence", 1),
            ("contradictory_evidence", 0),
            ("change_conditions", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        object.__setattr__(
            self,
            "model_version",
            _text(self.model_version, field_name="model_version"),
        )

    def range_for(self, sleeve: PortfolioSleeve) -> AllocationRange:
        if sleeve is PortfolioSleeve.PRODUCTIVE_RISK:
            return self.productive_risk
        if sleeve is PortfolioSleeve.DEFENSIVE_INCOME:
            return self.defensive_income
        if sleeve is PortfolioSleeve.DOLLAR_LIQUIDITY:
            return self.dollar_liquidity
        if sleeve is PortfolioSleeve.INFLATION_REAL_ASSETS:
            return self.inflation_real_assets
        if sleeve is PortfolioSleeve.DIVERSIFIERS:
            return self.diversifiers
        return AllocationRange(0.0, 0.20)

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "regime": self.regime.value,
            "confidence": self.confidence,
            "risk_score": self.risk_score,
            "productive_risk": self.productive_risk.to_dict(),
            "defensive_income": self.defensive_income.to_dict(),
            "dollar_liquidity": self.dollar_liquidity.to_dict(),
            "inflation_real_assets": self.inflation_real_assets.to_dict(),
            "diversifiers": self.diversifiers.to_dict(),
            "preferred_sleeves": [item.value for item in self.preferred_sleeves],
            "discouraged_sleeves": [item.value for item in self.discouraged_sleeves],
            "transitions": [item.to_dict() for item in self.transitions],
            "evidence": list(self.evidence),
            "contradictory_evidence": list(self.contradictory_evidence),
            "change_conditions": list(self.change_conditions),
            "model_version": self.model_version,
            "investment_authority": False,
            "construction_authority": False,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class CandidateAllocationDirective:
    candidate_identifier: str
    sleeve: PortfolioSleeve
    posture_alignment: float
    preferred: bool
    discouraged: bool
    maximum_staged_weight: float
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_identifier",
            _text(self.candidate_identifier, field_name="candidate_identifier"),
        )
        if not isinstance(self.sleeve, PortfolioSleeve):
            raise TypeError("sleeve must be PortfolioSleeve")
        object.__setattr__(
            self,
            "posture_alignment",
            _bounded(self.posture_alignment, field_name="posture_alignment"),
        )
        if not isinstance(self.preferred, bool) or not isinstance(self.discouraged, bool):
            raise TypeError("preferred and discouraged must be bool values")
        if self.preferred and self.discouraged:
            raise ValueError("a directive cannot be preferred and discouraged")
        object.__setattr__(
            self,
            "maximum_staged_weight",
            _ratio(self.maximum_staged_weight, field_name="maximum_staged_weight"),
        )
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_identifier": self.candidate_identifier,
            "sleeve": self.sleeve.value,
            "posture_alignment": self.posture_alignment,
            "preferred": self.preferred,
            "discouraged": self.discouraged,
            "maximum_staged_weight": self.maximum_staged_weight,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class StagedParticipationDecision:
    authorized: bool
    target_weight: float | None
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be a bool")
        if self.target_weight is not None:
            object.__setattr__(
                self,
                "target_weight",
                _ratio(self.target_weight, field_name="target_weight"),
            )
        object.__setattr__(self, "reasons", _texts(self.reasons, field_name="reasons", minimum=1))
        if self.authorized != (self.target_weight is not None and self.target_weight > 0.0):
            raise ValueError("authorization and target weight are inconsistent")


@dataclass(frozen=True, slots=True)
class CompoundingPortfolioAlternative:
    identifier: str
    kind: PortfolioAlternativeKind
    as_of: datetime
    target_weights: tuple[tuple[str, float], ...]
    cash_weight: float
    estimated_annualized_return_after_cost: float
    estimated_compound_return: float
    sleeve_weights: tuple[tuple[str, float], ...]
    candidate_identifiers: tuple[str, ...]
    rationale: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        if not isinstance(self.kind, PortfolioAlternativeKind):
            raise TypeError("kind must be PortfolioAlternativeKind")
        _aware(self.as_of, field_name="as_of")
        normalized_weights: list[tuple[str, float]] = []
        for symbol, weight in self.target_weights:
            normalized_weights.append(
                (
                    _text(symbol, field_name="symbol").upper(),
                    _ratio(weight, field_name="weight"),
                )
            )
        if len(normalized_weights) != len({symbol for symbol, _ in normalized_weights}):
            raise ValueError("alternative target symbols must be unique")
        object.__setattr__(self, "target_weights", tuple(normalized_weights))
        object.__setattr__(self, "cash_weight", _ratio(self.cash_weight, field_name="cash_weight"))
        if abs(sum(weight for _, weight in self.target_weights) + self.cash_weight - 1.0) > 0.000001:
            raise ValueError("alternative target weights and cash must sum to 1.0")
        object.__setattr__(
            self,
            "estimated_annualized_return_after_cost",
            _number(
                self.estimated_annualized_return_after_cost,
                field_name="estimated_annualized_return_after_cost",
                minimum=-1.0,
                maximum=10.0,
            ),
        )
        object.__setattr__(
            self,
            "estimated_compound_return",
            _number(
                self.estimated_compound_return,
                field_name="estimated_compound_return",
                minimum=-1.0,
                maximum=10.0,
            ),
        )
        normalized_sleeves = tuple(
            (
                _text(name, field_name="sleeve"),
                _ratio(weight, field_name="sleeve weight"),
            )
            for name, weight in self.sleeve_weights
        )
        object.__setattr__(self, "sleeve_weights", normalized_sleeves)
        object.__setattr__(
            self,
            "candidate_identifiers",
            _texts(self.candidate_identifiers, field_name="candidate_identifiers"),
        )
        object.__setattr__(self, "rationale", _text(self.rationale, field_name="rationale"))
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations", minimum=1),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "kind": self.kind.value,
            "as_of": self.as_of.isoformat(),
            "target_weights": [
                {"symbol": symbol, "weight": weight}
                for symbol, weight in self.target_weights
            ],
            "cash_weight": self.cash_weight,
            "estimated_annualized_return_after_cost": self.estimated_annualized_return_after_cost,
            "estimated_compound_return": self.estimated_compound_return,
            "sleeve_weights": [
                {"sleeve": sleeve, "weight": weight}
                for sleeve, weight in self.sleeve_weights
            ],
            "candidate_identifiers": list(self.candidate_identifiers),
            "rationale": self.rationale,
            "limitations": list(self.limitations),
            "advisory_only": True,
        }


@dataclass(frozen=True, slots=True)
class CompoundingPortfolioAlternativeSet:
    identifier: str
    as_of: datetime
    posture_identifier: str
    alternatives: tuple[CompoundingPortfolioAlternative, ...]
    selected_alternative_identifier: str | None
    cash_is_best_estimate: bool
    explanation: str
    model_version: str = "compounding-portfolio-alternatives.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "posture_identifier",
            _text(self.posture_identifier, field_name="posture_identifier"),
        )
        if not isinstance(self.alternatives, tuple) or not all(
            isinstance(item, CompoundingPortfolioAlternative) for item in self.alternatives
        ):
            raise TypeError("alternatives must contain CompoundingPortfolioAlternative values")
        if len(self.alternatives) < 2:
            raise ValueError("at least current and cash alternatives are required")
        identifiers = tuple(item.identifier for item in self.alternatives)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("portfolio alternative identifiers must be unique")
        if self.selected_alternative_identifier is not None:
            object.__setattr__(
                self,
                "selected_alternative_identifier",
                _text(
                    self.selected_alternative_identifier,
                    field_name="selected_alternative_identifier",
                ),
            )
            if self.selected_alternative_identifier not in identifiers:
                raise ValueError("selected alternative is not present")
        if not isinstance(self.cash_is_best_estimate, bool):
            raise TypeError("cash_is_best_estimate must be a bool")
        object.__setattr__(self, "explanation", _text(self.explanation, field_name="explanation"))
        object.__setattr__(
            self,
            "model_version",
            _text(self.model_version, field_name="model_version"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "posture_identifier": self.posture_identifier,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "selected_alternative_identifier": self.selected_alternative_identifier,
            "cash_is_best_estimate": self.cash_is_best_estimate,
            "explanation": self.explanation,
            "model_version": self.model_version,
            "cio_selection_authority": False,
            "construction_authority": False,
        }


@dataclass(frozen=True, slots=True)
class CompoundingParticipationPolicy:
    version: str = "compounding-staged-participation.v1"
    minimum_posture_alignment: float = 0.25
    minimum_robust_edge: float = 0.0
    minimum_stressed_edge: float = 0.0
    minimum_probability_of_success: float = 0.48
    maximum_probability_of_loss: float = 0.55
    maximum_probability_consistency_gap: float = 0.30
    maximum_independent_high_confidence_opposition: int = 1
    default_maximum_staged_weight: float = 0.01

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_posture_alignment",
            _bounded(
                self.minimum_posture_alignment,
                field_name="minimum_posture_alignment",
            ),
        )
        for field_name in (
            "minimum_probability_of_success",
            "maximum_probability_of_loss",
            "maximum_probability_consistency_gap",
            "default_maximum_staged_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        for field_name in ("minimum_robust_edge", "minimum_stressed_edge"):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name),
            )
        if (
            isinstance(self.maximum_independent_high_confidence_opposition, bool)
            or not isinstance(self.maximum_independent_high_confidence_opposition, int)
        ):
            raise TypeError("maximum independent opposition must be an integer")
        if self.maximum_independent_high_confidence_opposition < 0:
            raise ValueError("maximum independent opposition cannot be negative")

    def assess(
        self,
        *,
        candidate: object,
        directive: CandidateAllocationDirective | None,
        universe: object,
        specialists: object,
        robustness: object,
        reconciliation: object,
        ensemble: object,
        effective_alternative: float,
        material_opposition_threshold: float,
    ) -> StagedParticipationDecision:
        reasons: list[str] = []
        if directive is None:
            reasons.append("no portfolio-posture directive exists for the candidate")
        elif directive.discouraged or not directive.preferred:
            reasons.append("the candidate sleeve is not preferred by the current posture")
        elif directive.posture_alignment < self.minimum_posture_alignment:
            reasons.append("posture alignment is below the staged-participation threshold")

        direct_allowed = bool(getattr(universe, "direct_recommendation_allowed", False))
        if not direct_allowed:
            reasons.append("current capability authority prohibits a positive recommendation")
        evidence_vetoes = tuple(getattr(specialists, "evidence_vetoes", ()) or ())
        implementation_blocks = tuple(
            getattr(specialists, "implementation_blocks", ()) or ()
        )
        if evidence_vetoes:
            reasons.append("evidence integrity vetoes remain unresolved")
        if implementation_blocks:
            reasons.append("portfolio implementation blocks remain unresolved")

        quality = getattr(candidate, "evidence_quality", None)
        if quality is None or float(getattr(quality, "score", 0.0)) < 0.70:
            reasons.append("aggregate evidence quality is below 70%")
        if quality is None or float(getattr(quality, "ceiling", 0.0)) < 0.50:
            reasons.append("a required evidence dimension is below 50%")

        robust_edge = float(getattr(robustness, "robust_edge", -1.0))
        stressed_edge = float(getattr(robustness, "stressed_edge", -1.0))
        probability_loss = float(getattr(robustness, "probability_of_loss", 1.0))
        probability_gap = float(
            getattr(robustness, "probability_consistency_gap", 1.0)
        )
        if robust_edge <= self.minimum_robust_edge + _EPSILON:
            reasons.append("robust edge is not positive")
        if stressed_edge < self.minimum_stressed_edge - _EPSILON:
            reasons.append("stressed edge is negative")
        if probability_loss > self.maximum_probability_of_loss + _EPSILON:
            reasons.append("probability of loss exceeds staged-participation policy")
        if probability_gap > self.maximum_probability_consistency_gap + _EPSILON:
            reasons.append("stated and scenario-implied success probabilities diverge too far")

        probability_success = float(getattr(reconciliation, "probability_of_success", 0.0))
        expected_return = float(getattr(reconciliation, "expected_return", -1.0))
        if probability_success < self.minimum_probability_of_success - _EPSILON:
            reasons.append("reconciled success probability is below the exploration floor")
        if expected_return <= float(effective_alternative) + _EPSILON:
            reasons.append("reconciled return does not exceed the best capital alternative")

        opposition_count = 0
        independence = getattr(specialists, "evidence_independence", None)
        analyses = tuple(getattr(specialists, "analyses", ()) or ())
        counter = getattr(independence, "independent_opposition_count", None)
        if callable(counter):
            opposition_count = int(
                counter(
                    analyses,
                    minimum_confidence=float(material_opposition_threshold),
                )
            )
        if opposition_count > self.maximum_independent_high_confidence_opposition:
            reasons.append("multiple independent high-confidence objections remain")

        stage = str(getattr(getattr(ensemble, "stage", None), "value", "observe"))
        if stage == "observe":
            reasons.append("the adaptive growth ensemble remains at observe")

        portfolio = getattr(specialists, "portfolio_recommendation", None)
        recommended = getattr(portfolio, "recommended_position_weight", None)
        funding_source = getattr(portfolio, "funding_source", None)
        if recommended is None or float(recommended) <= 0.0:
            reasons.append("the Portfolio and Risk specialist found no positive feasible weight")
        if not isinstance(funding_source, str) or not funding_source.strip():
            reasons.append("the Portfolio and Risk specialist identified no funding source")

        if reasons:
            return StagedParticipationDecision(False, None, tuple(dict.fromkeys(reasons)))

        maximum = min(
            float(getattr(candidate, "maximum_position_weight", 0.0)),
            float(recommended),
            float(getattr(ensemble, "maximum_target_weight", 0.0)),
            directive.maximum_staged_weight,
            self.default_maximum_staged_weight,
        )
        minimum = max(
            0.0025,
            float(getattr(ensemble, "minimum_target_weight", 0.0)),
        )
        target = min(maximum, max(minimum, maximum * float(getattr(ensemble, "target_multiplier", 1.0))))
        if target <= 0.0:
            return StagedParticipationDecision(
                False,
                None,
                ("no positive staged weight survives the complete sizing boundary",),
            )
        return StagedParticipationDecision(
            True,
            round(target, 8),
            (
                "A small posture-consistent position is authorized because evidence integrity, capability, liquidity, funding, positive robust edge, positive stressed edge, and bounded disagreement all remain acceptable",
            ),
        )


class PortfolioPostureEngine:
    version = "portfolio-posture-engine.v1"

    _RECESSION_WORDS = (
        "recession",
        "contraction",
        "growth deterioration",
        "growth slowdown",
        "hard landing",
    )
    _INFLATION_WORDS = (
        "inflation shock",
        "inflationary",
        "inflation reacceleration",
        "stagflation",
        "price pressure",
    )
    _FUNDING_WORDS = (
        "funding stress",
        "liquidity stress",
        "credit stress",
        "bank stress",
        "dollar funding stress",
        "financial stress",
    )
    _DISINFLATION_WORDS = (
        "disinflation",
        "inflation easing",
        "cooling inflation",
        "stable inflation",
    )

    @staticmethod
    def _unique_contexts(contexts: Sequence[object]) -> tuple[object, ...]:
        unique: dict[tuple[object, ...], object] = {}
        for context in contexts:
            macro = getattr(context, "macro", None)
            market = getattr(context, "market", None)
            key = (
                tuple(getattr(macro, "evidence_identifiers", ()) or ()),
                tuple(getattr(market, "evidence_identifiers", ()) or ()),
                str(getattr(macro, "regime", "")),
                str(getattr(market, "market_regime", "")),
            )
            unique.setdefault(key, context)
        return tuple(unique.values())

    @staticmethod
    def _contains(text: str, phrases: Iterable[str]) -> bool:
        lowered = text.lower()
        return any(item in lowered for item in phrases)

    def assess(
        self,
        *,
        as_of: datetime,
        specialist_contexts: Sequence[object],
    ) -> PortfolioPosture:
        timestamp = _aware(as_of, field_name="as_of")
        contexts = self._unique_contexts(tuple(specialist_contexts))
        if not contexts:
            raise ValueError("portfolio posture requires specialist contexts")

        macro_impacts: list[float] = []
        market_impacts: list[float] = []
        trends: list[float] = []
        breadths: list[float] = []
        liquidities: list[float] = []
        positionings: list[float] = []
        confidences: list[float] = []
        evidence: list[str] = []
        contradictions: list[str] = []
        change_conditions: list[str] = []
        narrative: list[str] = []
        strong_dollar = False

        for context in contexts:
            macro = getattr(context, "macro")
            market = getattr(context, "market")
            macro_impacts.append(float(getattr(macro, "expected_return_impact")))
            market_impacts.append(float(getattr(market, "expected_return_impact")))
            trends.append(float(getattr(market, "trend")))
            breadths.append(float(getattr(market, "breadth")))
            liquidities.append(float(getattr(market, "liquidity")))
            positionings.append(float(getattr(market, "positioning")))
            confidences.extend(
                (
                    float(getattr(macro, "confidence")),
                    float(getattr(market, "confidence")),
                )
            )
            narrative.extend(
                (
                    str(getattr(macro, "regime")),
                    str(getattr(market, "market_regime")),
                    *tuple(getattr(macro, "tailwinds", ()) or ()),
                    *tuple(getattr(macro, "headwinds", ()) or ()),
                    *tuple(getattr(macro, "systemic_risks", ()) or ()),
                    *tuple(getattr(market, "risks", ()) or ()),
                )
            )
            evidence.extend(tuple(getattr(macro, "evidence_identifiers", ()) or ()))
            evidence.extend(tuple(getattr(market, "evidence_identifiers", ()) or ()))
            contradictions.extend(tuple(getattr(macro, "headwinds", ()) or ()))
            contradictions.extend(tuple(getattr(market, "risks", ()) or ()))
            change_conditions.extend(tuple(getattr(market, "entry_conditions", ()) or ()))
            forward = getattr(context, "forward_intelligence", None)
            currency_regime = getattr(forward, "currency_regime", None)
            if str(getattr(currency_regime, "value", currency_regime)) == "strong_dollar":
                strong_dollar = True

        macro = fmean(macro_impacts)
        market = fmean(market_impacts)
        trend = fmean(trends)
        breadth = fmean(breadths)
        liquidity = fmean(liquidities)
        positioning = fmean(positionings)
        risk_score = _clamp(
            0.32 * macro
            + 0.23 * market
            + 0.16 * trend
            + 0.12 * breadth
            + 0.11 * liquidity
            + 0.06 * positioning,
            -1.0,
            1.0,
        )
        text = " | ".join(narrative)
        recession = self._contains(text, self._RECESSION_WORDS)
        inflation = self._contains(text, self._INFLATION_WORDS)
        funding = self._contains(text, self._FUNDING_WORDS)
        disinflation = self._contains(text, self._DISINFLATION_WORDS)

        if funding and risk_score < 0.15:
            regime = PortfolioRegime.RISK_OFF_FUNDING_STRESS
        elif inflation and risk_score < 0.10:
            regime = PortfolioRegime.RISK_OFF_INFLATION
        elif recession and risk_score < 0.10:
            regime = PortfolioRegime.RISK_OFF_RECESSION
        elif risk_score >= 0.25 and macro > 0.0 and liquidity > -0.10:
            regime = PortfolioRegime.RISK_ON_GROWTH
        elif risk_score >= 0.10 and (disinflation or liquidity >= 0.10):
            regime = PortfolioRegime.RISK_ON_DISINFLATION
        elif risk_score <= -0.15:
            regime = PortfolioRegime.RISK_OFF_RECESSION
        else:
            regime = PortfolioRegime.BALANCED_TRANSITION

        ranges = self._ranges(regime, strong_dollar=strong_dollar)
        preferred, discouraged = self._sleeves(regime, strong_dollar=strong_dollar)
        dispersion = pstdev(macro_impacts + market_impacts + trends + breadths + liquidities)
        confidence = _clamp(fmean(confidences) * (1.0 - min(0.55, dispersion)), 0.0, 1.0)
        transitions = self._transitions(
            regime,
            confidence=confidence,
            inflation=inflation,
            recession=recession,
            funding=funding,
        )
        evidence_summary = tuple(
            dict.fromkeys(
                (
                    f"Aggregated macro impact={macro:+.2f}",
                    f"Aggregated market impact={market:+.2f}",
                    f"Trend={trend:+.2f}; breadth={breadth:+.2f}; liquidity={liquidity:+.2f}; positioning={positioning:+.2f}",
                    f"Risk score={risk_score:+.2f}; regime={regime.value}",
                    *(evidence or ("portfolio-posture:context-derived",)),
                )
            )
        )
        return PortfolioPosture(
            identifier=f"portfolio-posture:{timestamp.isoformat()}",
            as_of=timestamp,
            regime=regime,
            confidence=confidence,
            risk_score=risk_score,
            productive_risk=ranges[PortfolioSleeve.PRODUCTIVE_RISK],
            defensive_income=ranges[PortfolioSleeve.DEFENSIVE_INCOME],
            dollar_liquidity=ranges[PortfolioSleeve.DOLLAR_LIQUIDITY],
            inflation_real_assets=ranges[PortfolioSleeve.INFLATION_REAL_ASSETS],
            diversifiers=ranges[PortfolioSleeve.DIVERSIFIERS],
            preferred_sleeves=preferred,
            discouraged_sleeves=discouraged,
            transitions=transitions,
            evidence=evidence_summary,
            contradictory_evidence=tuple(dict.fromkeys(contradictions)),
            change_conditions=tuple(
                dict.fromkeys(
                    change_conditions
                    + [
                        "Recalculate when growth, inflation, liquidity, credit, dollar, breadth, positioning, or market-regime evidence changes materially",
                    ]
                )
            ),
            model_version=self.version,
        )

    @staticmethod
    def _ranges(
        regime: PortfolioRegime,
        *,
        strong_dollar: bool,
    ) -> dict[PortfolioSleeve, AllocationRange]:
        if regime is PortfolioRegime.RISK_ON_GROWTH:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.50, 0.85),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.05, 0.25),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.05, 0.25),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.00, 0.20),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.00, 0.15),
            }
        elif regime is PortfolioRegime.RISK_ON_DISINFLATION:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.45, 0.75),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.15, 0.40),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.05, 0.25),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.00, 0.15),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.00, 0.15),
            }
        elif regime is PortfolioRegime.RISK_OFF_RECESSION:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.10, 0.35),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.35, 0.70),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.15, 0.45),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.00, 0.20),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.05, 0.25),
            }
        elif regime is PortfolioRegime.RISK_OFF_INFLATION:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.10, 0.40),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.10, 0.35),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.15, 0.45),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.15, 0.45),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.05, 0.25),
            }
        elif regime is PortfolioRegime.RISK_OFF_FUNDING_STRESS:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.05, 0.25),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.20, 0.55),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.30, 0.70),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.00, 0.20),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.05, 0.25),
            }
        else:
            values = {
                PortfolioSleeve.PRODUCTIVE_RISK: AllocationRange(0.30, 0.60),
                PortfolioSleeve.DEFENSIVE_INCOME: AllocationRange(0.20, 0.45),
                PortfolioSleeve.DOLLAR_LIQUIDITY: AllocationRange(0.15, 0.40),
                PortfolioSleeve.INFLATION_REAL_ASSETS: AllocationRange(0.00, 0.25),
                PortfolioSleeve.DIVERSIFIERS: AllocationRange(0.05, 0.25),
            }
        if strong_dollar:
            current = values[PortfolioSleeve.DOLLAR_LIQUIDITY]
            values[PortfolioSleeve.DOLLAR_LIQUIDITY] = AllocationRange(
                min(0.70, current.minimum + 0.05),
                min(0.75, current.maximum + 0.10),
            )
        return values

    @staticmethod
    def _sleeves(
        regime: PortfolioRegime,
        *,
        strong_dollar: bool,
    ) -> tuple[tuple[PortfolioSleeve, ...], tuple[PortfolioSleeve, ...]]:
        if regime in {PortfolioRegime.RISK_ON_GROWTH, PortfolioRegime.RISK_ON_DISINFLATION}:
            preferred = [PortfolioSleeve.PRODUCTIVE_RISK]
            if regime is PortfolioRegime.RISK_ON_DISINFLATION:
                preferred.append(PortfolioSleeve.DEFENSIVE_INCOME)
            discouraged = []
        elif regime is PortfolioRegime.RISK_OFF_INFLATION:
            preferred = [
                PortfolioSleeve.DOLLAR_LIQUIDITY,
                PortfolioSleeve.INFLATION_REAL_ASSETS,
                PortfolioSleeve.DIVERSIFIERS,
            ]
            discouraged = [PortfolioSleeve.DEFENSIVE_INCOME]
        elif regime is PortfolioRegime.RISK_OFF_FUNDING_STRESS:
            preferred = [
                PortfolioSleeve.DOLLAR_LIQUIDITY,
                PortfolioSleeve.DEFENSIVE_INCOME,
            ]
            discouraged = [PortfolioSleeve.PRODUCTIVE_RISK]
        elif regime is PortfolioRegime.RISK_OFF_RECESSION:
            preferred = [
                PortfolioSleeve.DEFENSIVE_INCOME,
                PortfolioSleeve.DOLLAR_LIQUIDITY,
                PortfolioSleeve.DIVERSIFIERS,
            ]
            discouraged = []
        else:
            preferred = [
                PortfolioSleeve.PRODUCTIVE_RISK,
                PortfolioSleeve.DEFENSIVE_INCOME,
                PortfolioSleeve.DOLLAR_LIQUIDITY,
            ]
            discouraged = []
        if strong_dollar and PortfolioSleeve.DOLLAR_LIQUIDITY not in preferred:
            preferred.append(PortfolioSleeve.DOLLAR_LIQUIDITY)
        return tuple(preferred), tuple(discouraged)

    @staticmethod
    def _transitions(
        regime: PortfolioRegime,
        *,
        confidence: float,
        inflation: bool,
        recession: bool,
        funding: bool,
    ) -> tuple[RegimeTransition, ...]:
        persist = _clamp(0.45 + 0.35 * confidence, 0.45, 0.80)
        residual = 1.0 - persist
        if regime in {PortfolioRegime.RISK_ON_GROWTH, PortfolioRegime.RISK_ON_DISINFLATION}:
            adverse = (
                PortfolioRegime.RISK_OFF_INFLATION
                if inflation
                else PortfolioRegime.RISK_OFF_RECESSION
            )
            alternate = (
                PortfolioRegime.RISK_ON_DISINFLATION
                if regime is PortfolioRegime.RISK_ON_GROWTH
                else PortfolioRegime.RISK_ON_GROWTH
            )
        elif regime is PortfolioRegime.RISK_OFF_INFLATION:
            adverse = PortfolioRegime.RISK_OFF_FUNDING_STRESS
            alternate = PortfolioRegime.BALANCED_TRANSITION
        elif regime is PortfolioRegime.RISK_OFF_FUNDING_STRESS:
            adverse = PortfolioRegime.RISK_OFF_RECESSION
            alternate = PortfolioRegime.BALANCED_TRANSITION
        elif regime is PortfolioRegime.RISK_OFF_RECESSION:
            adverse = (
                PortfolioRegime.RISK_OFF_FUNDING_STRESS
                if funding
                else PortfolioRegime.RISK_OFF_INFLATION
            )
            alternate = PortfolioRegime.BALANCED_TRANSITION
        else:
            adverse = (
                PortfolioRegime.RISK_OFF_RECESSION
                if recession
                else PortfolioRegime.RISK_OFF_INFLATION
            )
            alternate = PortfolioRegime.RISK_ON_DISINFLATION
        first = round(residual * 0.55, 8)
        second = round(1.0 - persist - first, 8)
        return (
            RegimeTransition(
                regime=regime,
                probability=persist,
                rationale="Current macro, market, breadth, liquidity, and positioning evidence remains the highest-probability state.",
                leading_indicators=("growth", "inflation", "liquidity", "breadth"),
            ),
            RegimeTransition(
                regime=alternate,
                probability=first,
                rationale="A change in inflation, growth, liquidity, or market breadth could improve the capital-allocation backdrop.",
                leading_indicators=("real yields", "credit spreads", "earnings revisions"),
            ),
            RegimeTransition(
                regime=adverse,
                probability=second,
                rationale="The principal adverse transition remains represented rather than hidden inside a single regime label.",
                leading_indicators=("financial stress", "funding", "volatility", "correlation"),
            ),
        )

    def directives(
        self,
        candidates: Sequence[object],
        posture: PortfolioPosture,
    ) -> tuple[CandidateAllocationDirective, ...]:
        values: list[CandidateAllocationDirective] = []
        for candidate in candidates:
            sleeve = classify_candidate_sleeve(candidate)
            preferred = sleeve in posture.preferred_sleeves
            discouraged = sleeve in posture.discouraged_sleeves
            alignment = (
                0.65 + 0.25 * posture.confidence
                if preferred
                else (-0.65 if discouraged else 0.10 * posture.risk_score)
            )
            maximum = min(
                float(getattr(candidate, "maximum_position_weight", 0.0)),
                0.01,
                max(0.0025, posture.range_for(sleeve).maximum),
            )
            values.append(
                CandidateAllocationDirective(
                    candidate_identifier=str(getattr(candidate, "identifier")),
                    sleeve=sleeve,
                    posture_alignment=_clamp(alignment, -1.0, 1.0),
                    preferred=preferred,
                    discouraged=discouraged,
                    maximum_staged_weight=max(0.0, maximum),
                    rationale=(
                        f"Candidate maps to {sleeve.value}; current posture is {posture.regime.value}; "
                        f"preferred={preferred}; discouraged={discouraged}."
                    ),
                )
            )
        return tuple(values)


def classify_candidate_sleeve(candidate: object) -> PortfolioSleeve:
    instrument = getattr(candidate, "instrument", candidate)
    asset_class = getattr(instrument, "economic_exposure_class", None) or getattr(
        instrument, "asset_class", CandidateAssetClass.OTHER
    )
    if asset_class in {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.REAL_ESTATE,
    }:
        return PortfolioSleeve.PRODUCTIVE_RISK
    if asset_class is CandidateAssetClass.US_ETF:
        name = str(getattr(instrument, "name", "")).lower()
        if any(item in name for item in ("treasury", "bond", "income", "credit")):
            return PortfolioSleeve.DEFENSIVE_INCOME
        if any(item in name for item in ("gold", "commodity", "inflation")):
            return PortfolioSleeve.INFLATION_REAL_ASSETS
        return PortfolioSleeve.PRODUCTIVE_RISK
    if asset_class is CandidateAssetClass.FIXED_INCOME:
        if bool(getattr(instrument, "is_us_treasury", False)):
            return PortfolioSleeve.DEFENSIVE_INCOME
        return PortfolioSleeve.DEFENSIVE_INCOME
    if asset_class in {CandidateAssetClass.CASH_EQUIVALENT, CandidateAssetClass.FX}:
        return PortfolioSleeve.DOLLAR_LIQUIDITY
    if asset_class is CandidateAssetClass.COMMODITY:
        return PortfolioSleeve.INFLATION_REAL_ASSETS
    if asset_class in {CandidateAssetClass.VOLATILITY, CandidateAssetClass.OPTION}:
        return PortfolioSleeve.DIVERSIFIERS
    if asset_class in {
        CandidateAssetClass.CRYPTO,
        CandidateAssetClass.ALTERNATIVE,
        CandidateAssetClass.FUTURE,
    }:
        return PortfolioSleeve.ALTERNATIVES
    return PortfolioSleeve.DIVERSIFIERS


class CompoundingPortfolioAlternativeEngine:
    version = "compounding-portfolio-alternative-engine.v1"

    @staticmethod
    def _annualized_return(candidate: object) -> float:
        value = float(getattr(candidate, "net_expected_return", 0.0))
        horizon = max(1, int(getattr(candidate, "decision_horizon_days", 365)))
        if value <= -1.0:
            return -1.0
        return _clamp((1.0 + value) ** (365.0 / horizon) - 1.0, -1.0, 10.0)

    @staticmethod
    def _compound_estimate(
        weights: Mapping[str, float],
        candidates_by_symbol: Mapping[str, object],
        *,
        cash_weight: float,
        cash_return: float,
    ) -> float:
        log_growth = cash_weight * log1p(max(-0.999999, cash_return))
        for symbol, weight in weights.items():
            candidate = candidates_by_symbol.get(symbol)
            if candidate is None:
                continue
            log_growth += weight * log1p(
                max(-0.999999, CompoundingPortfolioAlternativeEngine._annualized_return(candidate))
            )
        return _clamp(exp(log_growth) - 1.0, -1.0, 10.0)

    @staticmethod
    def _estimated_return(
        weights: Mapping[str, float],
        candidates_by_symbol: Mapping[str, object],
        *,
        cash_weight: float,
        cash_return: float,
    ) -> float:
        value = cash_weight * cash_return
        for symbol, weight in weights.items():
            candidate = candidates_by_symbol.get(symbol)
            if candidate is None:
                continue
            annualized = CompoundingPortfolioAlternativeEngine._annualized_return(candidate)
            cost = float(getattr(candidate, "implementation_cost_return", 0.0))
            value += weight * (annualized - cost)
        return _clamp(value, -1.0, 10.0)

    @staticmethod
    def _normalize(weights: Mapping[str, float], *, cash_floor: float) -> tuple[dict[str, float], float]:
        positive = {symbol: max(0.0, float(weight)) for symbol, weight in weights.items()}
        total = sum(positive.values())
        investable = max(0.0, 1.0 - cash_floor)
        if total > investable and total > 0.0:
            scale = investable / total
            positive = {symbol: weight * scale for symbol, weight in positive.items()}
        cash = max(cash_floor, 1.0 - sum(positive.values()))
        residual = 1.0 - cash - sum(positive.values())
        if abs(residual) > 1e-10:
            cash += residual
        return (
            {symbol: round(weight, 8) for symbol, weight in positive.items() if weight > _EPSILON},
            round(cash, 8),
        )

    @staticmethod
    def _sleeve_weights(
        weights: Mapping[str, float],
        candidates_by_symbol: Mapping[str, object],
        *,
        cash_weight: float,
    ) -> tuple[tuple[str, float], ...]:
        values: dict[str, float] = {PortfolioSleeve.DOLLAR_LIQUIDITY.value: cash_weight}
        for symbol, weight in weights.items():
            candidate = candidates_by_symbol.get(symbol)
            if candidate is None:
                continue
            sleeve = classify_candidate_sleeve(candidate).value
            values[sleeve] = values.get(sleeve, 0.0) + weight
        return tuple(sorted((name, round(weight, 8)) for name, weight in values.items()))

    def build(
        self,
        *,
        cycle_identifier: str,
        posture: PortfolioPosture,
        candidates: Sequence[object],
        directives: Sequence[CandidateAllocationDirective],
        portfolio: object,
        construction: object | None,
    ) -> CompoundingPortfolioAlternativeSet:
        candidate_by_identifier = {
            str(getattr(item, "identifier")): item for item in candidates
        }
        candidate_by_symbol = {
            str(getattr(getattr(item, "instrument"), "symbol")).upper(): item
            for item in candidates
        }
        directive_map = {item.candidate_identifier: item for item in directives}
        current = {
            str(getattr(item, "symbol")).upper(): float(getattr(item, "current_weight"))
            for item in tuple(getattr(portfolio, "positions", ()) or ())
        }
        current_cash = float(getattr(portfolio, "cash_weight"))
        cash_return = float(getattr(portfolio, "cash_expected_return"))
        alternatives: list[CompoundingPortfolioAlternative] = []

        def add(
            kind: PortfolioAlternativeKind,
            weights: Mapping[str, float],
            cash_weight: float,
            candidate_ids: Sequence[str],
            rationale: str,
            limitations: tuple[str, ...],
        ) -> None:
            normalized, cash = self._normalize(weights, cash_floor=cash_weight)
            alternatives.append(
                CompoundingPortfolioAlternative(
                    identifier=f"portfolio-alternative:{cycle_identifier}:{kind.value}",
                    kind=kind,
                    as_of=posture.as_of,
                    target_weights=tuple(sorted(normalized.items())),
                    cash_weight=cash,
                    estimated_annualized_return_after_cost=self._estimated_return(
                        normalized,
                        candidate_by_symbol,
                        cash_weight=cash,
                        cash_return=cash_return,
                    ),
                    estimated_compound_return=self._compound_estimate(
                        normalized,
                        candidate_by_symbol,
                        cash_weight=cash,
                        cash_return=cash_return,
                    ),
                    sleeve_weights=self._sleeve_weights(
                        normalized,
                        candidate_by_symbol,
                        cash_weight=cash,
                    ),
                    candidate_identifiers=tuple(dict.fromkeys(str(item) for item in candidate_ids)),
                    rationale=rationale,
                    limitations=limitations,
                )
            )

        add(
            PortfolioAlternativeKind.CURRENT,
            current,
            current_cash,
            (),
            "Preserve the current canonical portfolio without assuming any new trade.",
            ("Current holdings without a same-cycle candidate record use no new return estimate",),
        )
        add(
            PortfolioAlternativeKind.ALL_CASH,
            {},
            1.0,
            (),
            "Hold all capital in the recorded cash alternative.",
            ("Cash is an active competitor, not the automatic default",),
        )

        ranked_candidates = sorted(
            candidates,
            key=lambda item: (
                directive_map.get(str(getattr(item, "identifier"))).posture_alignment
                if directive_map.get(str(getattr(item, "identifier"))) is not None
                else -1.0,
                self._annualized_return(item),
                float(getattr(getattr(item, "evidence_quality", None), "score", 0.0)),
            ),
            reverse=True,
        )

        def portfolio_for(
            sleeves: set[PortfolioSleeve],
            *,
            cash_floor: float,
            exploratory: bool = False,
        ) -> tuple[dict[str, float], tuple[str, ...]]:
            eligible = []
            for candidate in ranked_candidates:
                identifier = str(getattr(candidate, "identifier"))
                directive = directive_map.get(identifier)
                if directive is None or directive.sleeve not in sleeves:
                    continue
                if directive.discouraged:
                    continue
                quality = getattr(candidate, "evidence_quality", None)
                if float(getattr(quality, "score", 0.0)) < 0.70:
                    continue
                if float(getattr(quality, "ceiling", 0.0)) < 0.50:
                    continue
                if self._annualized_return(candidate) <= cash_return:
                    continue
                eligible.append(candidate)
            if not eligible:
                return {}, ()
            target_budget = max(0.0, 1.0 - cash_floor)
            scores = [
                max(
                    0.0001,
                    self._annualized_return(item) - cash_return
                    + max(
                        0.0,
                        directive_map[str(getattr(item, "identifier"))].posture_alignment,
                    )
                    * 0.02,
                )
                for item in eligible
            ]
            total_score = sum(scores)
            weights: dict[str, float] = {}
            identifiers: list[str] = []
            for candidate, score in zip(eligible, scores, strict=True):
                identifier = str(getattr(candidate, "identifier"))
                symbol = str(getattr(getattr(candidate, "instrument"), "symbol")).upper()
                cap = min(
                    float(getattr(candidate, "maximum_position_weight", 0.0)),
                    0.01 if exploratory else 0.20,
                )
                proposed = target_budget * score / total_score
                weights[symbol] = min(cap, proposed)
                identifiers.append(identifier)
            return weights, tuple(identifiers)

        posture_sleeves = set(posture.preferred_sleeves)
        posture_weights, posture_ids = portfolio_for(
            posture_sleeves,
            cash_floor=posture.dollar_liquidity.minimum,
        )
        add(
            PortfolioAlternativeKind.POSTURE_CONSISTENT,
            posture_weights,
            posture.dollar_liquidity.minimum,
            posture_ids,
            "Allocate only to complete-evidence candidates inside sleeves preferred by the current posture.",
            (
                "This is an advisory comparison and cannot bypass committee, CIO, or construction controls",
            ),
        )

        productive_weights, productive_ids = portfolio_for(
            {PortfolioSleeve.PRODUCTIVE_RISK, PortfolioSleeve.ALTERNATIVES},
            cash_floor=max(0.05, posture.dollar_liquidity.minimum),
        )
        add(
            PortfolioAlternativeKind.PRODUCTIVE_RISK,
            productive_weights,
            max(0.05, posture.dollar_liquidity.minimum),
            productive_ids,
            "Compare the strongest qualified productive-risk expressions against cash and defensive capital.",
            ("Alternative and crypto exposures remain bounded by certified capability and candidate caps",),
        )

        defensive_weights, defensive_ids = portfolio_for(
            {
                PortfolioSleeve.DEFENSIVE_INCOME,
                PortfolioSleeve.DOLLAR_LIQUIDITY,
                PortfolioSleeve.DIVERSIFIERS,
                PortfolioSleeve.INFLATION_REAL_ASSETS,
            },
            cash_floor=posture.dollar_liquidity.minimum,
        )
        add(
            PortfolioAlternativeKind.DEFENSIVE,
            defensive_weights,
            posture.dollar_liquidity.minimum,
            defensive_ids,
            "Compare defensive income, dollar liquidity, real assets, and diversifiers instead of treating risk-off as inactivity.",
            ("The correct defensive mix depends on whether risk-off is recessionary, inflationary, or funding-driven",),
        )

        exploratory_weights, exploratory_ids = portfolio_for(
            set(PortfolioSleeve),
            cash_floor=max(0.10, posture.dollar_liquidity.minimum),
            exploratory=True,
        )
        add(
            PortfolioAlternativeKind.DIVERSIFIED_EXPLORATORY,
            exploratory_weights,
            max(0.10, posture.dollar_liquidity.minimum),
            exploratory_ids,
            "Diversify small staged positions across independently attractive sleeves rather than requiring one concentrated perfect candidate.",
            ("Every exploratory component still requires a positive CIO action before construction",),
        )

        selected_identifier = None
        if construction is not None:
            target_weights = dict(tuple(getattr(construction, "target_weights", ()) or ()))
            target_cash = float(getattr(construction, "target_cash_weight", 1.0))
            candidate_ids = tuple(
                identifier
                for identifier, candidate in candidate_by_identifier.items()
                if str(getattr(getattr(candidate, "instrument"), "symbol")).upper()
                in target_weights
            )
            add(
                PortfolioAlternativeKind.SELECTED_CONSTRUCTION,
                target_weights,
                target_cash,
                candidate_ids,
                "The independently constructed feasible portfolio produced from the CIO's actual decisions.",
                ("Construction remains authoritative over final feasible targets",),
            )
            selected_identifier = alternatives[-1].identifier

        cash_alternative = next(
            item for item in alternatives if item.kind is PortfolioAlternativeKind.ALL_CASH
        )
        best = max(
            alternatives,
            key=lambda item: (
                item.estimated_compound_return,
                item.estimated_annualized_return_after_cost,
                -item.cash_weight,
            ),
        )
        return CompoundingPortfolioAlternativeSet(
            identifier=f"portfolio-alternative-set:{cycle_identifier}",
            as_of=posture.as_of,
            posture_identifier=posture.identifier,
            alternatives=tuple(alternatives),
            selected_alternative_identifier=selected_identifier,
            cash_is_best_estimate=best.identifier == cash_alternative.identifier,
            explanation=(
                f"Advisory comparison estimates {best.kind.value} as the strongest compound-return alternative before authoritative CIO and construction controls. "
                "Cash remains valid only when it wins this comparison or hard evidence and implementation controls prohibit deployment."
            ),
            model_version=self.version,
        )


class SQLiteCompoundingAllocationStore:
    """Separate append-only chain for posture and portfolio alternatives."""

    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS compounding_allocation_events (
                    sequence INTEGER PRIMARY KEY,
                    event_identifier TEXT NOT NULL UNIQUE,
                    cycle_identifier TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS compounding_allocation_prevent_update
                BEFORE UPDATE ON compounding_allocation_events
                BEGIN
                    SELECT RAISE(ABORT, 'compounding allocation store is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS compounding_allocation_prevent_delete
                BEFORE DELETE ON compounding_allocation_events
                BEGIN
                    SELECT RAISE(ABORT, 'compounding allocation store is append-only');
                END;
                """
            )

    def append(
        self,
        *,
        cycle_identifier: str,
        posture: PortfolioPosture,
        alternatives: CompoundingPortfolioAlternativeSet,
        code_version: str,
    ) -> str:
        cycle = _text(cycle_identifier, field_name="cycle_identifier")
        version = _text(code_version, field_name="code_version")
        if alternatives.posture_identifier != posture.identifier:
            raise ValueError("portfolio alternatives do not belong to the posture")
        payload = {
            "schema_version": "compounding-allocation-event.v1",
            "cycle_identifier": cycle,
            "code_version": version,
            "posture": posture.to_dict(),
            "portfolio_alternatives": alternatives.to_dict(),
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        event_identifier = f"compounding-allocation:{cycle}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json, content_hash FROM compounding_allocation_events WHERE event_identifier = ?",
                (event_identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError("compounding allocation event already exists with different content")
                connection.rollback()
                return str(existing["content_hash"])
            previous = connection.execute(
                "SELECT sequence, content_hash FROM compounding_allocation_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous is not None else 1
            previous_hash = str(previous["content_hash"]) if previous is not None else self._GENESIS
            content_hash = hashlib.sha256(
                json.dumps(
                    {
                        "sequence": sequence,
                        "event_identifier": event_identifier,
                        "cycle_identifier": cycle,
                        "occurred_at": posture.as_of.isoformat(),
                        "payload_json": payload_json,
                        "previous_hash": previous_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO compounding_allocation_events (
                    sequence, event_identifier, cycle_identifier, occurred_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event_identifier,
                    cycle,
                    posture.as_of.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            connection.commit()
            return content_hash

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM compounding_allocation_events ORDER BY sequence"
            ).fetchall()
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                return False
            if str(row["previous_hash"]) != previous:
                return False
            expected = hashlib.sha256(
                json.dumps(
                    {
                        "sequence": int(row["sequence"]),
                        "event_identifier": str(row["event_identifier"]),
                        "cycle_identifier": str(row["cycle_identifier"]),
                        "occurred_at": str(row["occurred_at"]),
                        "payload_json": str(row["payload_json"]),
                        "previous_hash": str(row["previous_hash"]),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if expected != str(row["content_hash"]):
                return False
            previous = expected
        return True


__all__ = [
    "AllocationRange",
    "CandidateAllocationDirective",
    "CompoundingParticipationPolicy",
    "CompoundingPortfolioAlternative",
    "CompoundingPortfolioAlternativeEngine",
    "CompoundingPortfolioAlternativeSet",
    "PortfolioAlternativeKind",
    "PortfolioPosture",
    "PortfolioPostureEngine",
    "PortfolioRegime",
    "PortfolioSleeve",
    "RegimeTransition",
    "SQLiteCompoundingAllocationStore",
    "StagedParticipationDecision",
    "classify_candidate_sleeve",
]
