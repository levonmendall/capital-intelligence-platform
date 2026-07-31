"""Point-in-time opportunity qualification and ranking contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from cio import (
    CapitalAlternativeComparison,
    CandidateDecisionRecord,
    UniverseAssessment,
)


class AlternativeKind(str, Enum):
    """Competing uses of capital available at the decision time."""

    CASH = "cash"
    CURRENT_HOLDING = "current_holding"
    QUALIFIED_CANDIDATE = "qualified_candidate"


class QualificationOutcome(str, Enum):
    """Whether a candidate deserves independent specialist attention."""

    QUALIFIED = "qualified"
    REJECTED = "rejected"


class AnalysisLane(str, Enum):
    """Why the candidate must reach specialist and CIO review."""

    ACQUISITION = "acquisition"
    PARTICIPATION = "participation"
    EXPLORATION = "exploration"
    HOLDING_REVIEW = "holding_review"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _finite(
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


@dataclass(frozen=True, slots=True)
class AlternativeUse:
    """One current or available use of portfolio capital."""

    identifier: str
    kind: AlternativeKind
    expected_return: float
    implementation_cost_return: float
    evidence_quality: float
    liquidity_score: float
    current_weight: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        if not isinstance(self.kind, AlternativeKind):
            raise TypeError("kind must be an AlternativeKind")
        object.__setattr__(
            self,
            "expected_return",
            _finite(self.expected_return, field_name="expected_return"),
        )
        object.__setattr__(
            self,
            "implementation_cost_return",
            _finite(
                self.implementation_cost_return,
                field_name="implementation_cost_return",
                minimum=0.0,
            ),
        )
        for field_name in (
            "evidence_quality",
            "liquidity_score",
            "current_weight",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if self.kind is AlternativeKind.CASH and self.current_weight <= 0.0:
            raise ValueError("cash alternative must record its current weight")

    @property
    def net_expected_return(self) -> float:
        return round(self.expected_return - self.implementation_cost_return, 8)


@dataclass(frozen=True, slots=True)
class OpportunityRankingInput:
    """Portfolio and thesis diagnostics used only to order qualified candidates."""

    candidate_identifier: str
    marginal_portfolio_contribution: float
    diversification_score: float
    thesis_clarity_score: float
    invalidation_clarity_score: float
    forecast_durability_score: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_identifier",
            _required_text(
                self.candidate_identifier, field_name="candidate_identifier"
            ),
        )
        object.__setattr__(
            self,
            "marginal_portfolio_contribution",
            _finite(
                self.marginal_portfolio_contribution,
                field_name="marginal_portfolio_contribution",
            ),
        )
        for field_name in (
            "diversification_score",
            "thesis_clarity_score",
            "invalidation_clarity_score",
            "forecast_durability_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )


@dataclass(frozen=True, slots=True)
class OpportunitySetContext:
    """Point-in-time current holdings, cash, and qualified alternatives."""

    identifier: str
    as_of: datetime
    alternatives: tuple[AlternativeUse, ...]
    ranking_inputs: tuple[OpportunityRankingInput, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.alternatives, tuple) or not all(
            isinstance(item, AlternativeUse) for item in self.alternatives
        ):
            raise TypeError("alternatives must contain AlternativeUse values")
        if not self.alternatives:
            raise ValueError("opportunity set must contain at least cash")
        identifiers = tuple(item.identifier for item in self.alternatives)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("alternative identifiers must be unique")
        if not any(item.kind is AlternativeKind.CASH for item in self.alternatives):
            raise ValueError("opportunity set must include a cash alternative")
        if sum(item.current_weight for item in self.alternatives) > 1.000001:
            raise ValueError("alternative current weights cannot exceed 1.0")
        if not isinstance(self.ranking_inputs, tuple) or not all(
            isinstance(item, OpportunityRankingInput) for item in self.ranking_inputs
        ):
            raise TypeError(
                "ranking_inputs must contain OpportunityRankingInput values"
            )
        ranking_ids = tuple(item.candidate_identifier for item in self.ranking_inputs)
        if len(ranking_ids) != len(set(ranking_ids)):
            raise ValueError("ranking inputs must be unique per candidate")

    def ranking_input(
        self, candidate_identifier: str
    ) -> OpportunityRankingInput | None:
        resolved = _required_text(
            candidate_identifier, field_name="candidate_identifier"
        )
        return next(
            (
                item
                for item in self.ranking_inputs
                if item.candidate_identifier == resolved
            ),
            None,
        )

    def best_alternative(self) -> AlternativeUse:
        """Return the strongest cost-adjusted current use of capital."""

        return max(
            self.alternatives,
            key=lambda item: (
                item.net_expected_return,
                item.evidence_quality,
                item.liquidity_score,
                item.identifier,
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateQualification:
    """Auditable pre-committee decision for one candidate."""

    candidate_identifier: str
    outcome: QualificationOutcome
    policy_version: str
    universe: UniverseAssessment
    effective_opportunity_cost: float
    opportunity_edge: float
    reasons: tuple[str, ...]
    analysis_lane: AnalysisLane = AnalysisLane.ACQUISITION
    best_alternative_identifier: str | None = None
    best_alternative_kind: AlternativeKind | None = None
    baseline_alternative_identifier: str | None = None
    baseline_opportunity_cost: float | None = None
    resolved_policy_profile: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("candidate_identifier", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.outcome, QualificationOutcome):
            raise TypeError("outcome must be a QualificationOutcome")
        if not isinstance(self.analysis_lane, AnalysisLane):
            raise TypeError("analysis_lane must be an AnalysisLane")
        if not isinstance(self.universe, UniverseAssessment):
            raise TypeError("universe must be a UniverseAssessment")
        for field_name in ("effective_opportunity_cost", "opportunity_edge"):
            object.__setattr__(
                self,
                field_name,
                _finite(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")
        if not self.reasons:
            raise ValueError("qualification must explain its outcome")
        for field_name in (
            "best_alternative_identifier",
            "baseline_alternative_identifier",
            "resolved_policy_profile",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _required_text(value, field_name=field_name),
                )
        if self.best_alternative_kind is not None and not isinstance(
            self.best_alternative_kind, AlternativeKind
        ):
            raise TypeError("best_alternative_kind must be AlternativeKind or None")
        if self.baseline_opportunity_cost is not None:
            object.__setattr__(
                self,
                "baseline_opportunity_cost",
                _finite(
                    self.baseline_opportunity_cost,
                    field_name="baseline_opportunity_cost",
                ),
            )

    @property
    def capital_comparison(self) -> CapitalAlternativeComparison:
        best_identifier = (
            self.best_alternative_identifier
            or self.baseline_alternative_identifier
            or "capital-alternative:unidentified"
        )
        baseline_identifier = (
            self.baseline_alternative_identifier
            or self.best_alternative_identifier
            or "capital-alternative:baseline"
        )
        return CapitalAlternativeComparison(
            candidate_identifier=self.candidate_identifier,
            best_alternative_identifier=best_identifier,
            best_alternative_kind=(
                "unknown"
                if self.best_alternative_kind is None
                else self.best_alternative_kind.value
            ),
            effective_opportunity_cost=self.effective_opportunity_cost,
            baseline_alternative_identifier=baseline_identifier,
            baseline_opportunity_cost=(
                self.effective_opportunity_cost
                if self.baseline_opportunity_cost is None
                else self.baseline_opportunity_cost
            ),
        )

    @property
    def qualified(self) -> bool:
        return self.outcome is QualificationOutcome.QUALIFIED

    @property
    def mandatory_holding_review(self) -> bool:
        return self.analysis_lane is AnalysisLane.HOLDING_REVIEW


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    """One disclosed opportunity-ranking component."""

    name: str
    raw_value: float
    normalized_score: float
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            _required_text(self.name, field_name="name"),
        )
        object.__setattr__(
            self,
            "raw_value",
            _finite(self.raw_value, field_name="raw_value"),
        )
        for field_name in ("normalized_score", "weight"):
            object.__setattr__(
                self,
                field_name,
                _finite(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )

    @property
    def contribution(self) -> float:
        return round(self.normalized_score * self.weight, 8)


@dataclass(frozen=True, slots=True)
class RankedOpportunity:
    """One qualified candidate in comparable committee-review order."""

    rank: int
    candidate: CandidateDecisionRecord
    qualification: CandidateQualification
    score: float
    components: tuple[ScoreComponent, ...]

    def __post_init__(self) -> None:
        if isinstance(self.rank, bool) or not isinstance(self.rank, int):
            raise TypeError("rank must be an integer")
        if self.rank < 1:
            raise ValueError("rank must be positive")
        if not isinstance(self.candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if not isinstance(self.qualification, CandidateQualification):
            raise TypeError("qualification must be CandidateQualification")
        if not self.qualification.qualified:
            raise ValueError("ranked opportunities must be qualified")
        if self.qualification.candidate_identifier != self.candidate.identifier:
            raise ValueError("qualification does not match candidate")
        object.__setattr__(
            self,
            "score",
            _finite(self.score, field_name="score", minimum=0.0, maximum=1.0),
        )
        if not isinstance(self.components, tuple) or not all(
            isinstance(item, ScoreComponent) for item in self.components
        ):
            raise TypeError("components must contain ScoreComponent values")
        if not self.components:
            raise ValueError("components cannot be empty")
        names = tuple(item.name for item in self.components)
        if len(names) != len(set(names)):
            raise ValueError("component names must be unique")
        if abs(sum(item.weight for item in self.components) - 1.0) > 0.000001:
            raise ValueError("component weights must sum to 1.0")
        if abs(sum(item.contribution for item in self.components) - self.score) > 0.00001:
            raise ValueError("score must equal disclosed component contributions")


@dataclass(frozen=True, slots=True)
class OpportunityQueue:
    """Qualified review queue plus explicit rejections."""

    context_identifier: str
    policy_version: str
    ranked: tuple[RankedOpportunity, ...]
    rejected: tuple[CandidateQualification, ...]

    def __post_init__(self) -> None:
        for field_name in ("context_identifier", "policy_version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.ranked, tuple) or not all(
            isinstance(item, RankedOpportunity) for item in self.ranked
        ):
            raise TypeError("ranked must contain RankedOpportunity values")
        if not isinstance(self.rejected, tuple) or not all(
            isinstance(item, CandidateQualification) for item in self.rejected
        ):
            raise TypeError("rejected must contain CandidateQualification values")
        if any(item.qualified for item in self.rejected):
            raise ValueError("rejected cannot contain qualified outcomes")
        expected_ranks = tuple(range(1, len(self.ranked) + 1))
        actual_ranks = tuple(item.rank for item in self.ranked)
        if actual_ranks != expected_ranks:
            raise ValueError("ranked opportunities must be contiguous and ordered")
        candidate_ids = tuple(item.candidate.identifier for item in self.ranked)
        candidate_ids += tuple(item.candidate_identifier for item in self.rejected)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("each candidate must appear exactly once")

    @property
    def has_qualified_opportunity(self) -> bool:
        return any(
            item.qualification.analysis_lane is AnalysisLane.ACQUISITION
            for item in self.ranked
        )

    @property
    def holding_reviews(self) -> tuple[RankedOpportunity, ...]:
        return tuple(
            item
            for item in self.ranked
            if item.qualification.analysis_lane is AnalysisLane.HOLDING_REVIEW
        )

    @property
    def top(self) -> RankedOpportunity | None:
        return self.ranked[0] if self.ranked else None


__all__ = [
    "AnalysisLane",
    "AlternativeKind",
    "AlternativeUse",
    "CandidateQualification",
    "OpportunityQueue",
    "OpportunityRankingInput",
    "OpportunitySetContext",
    "QualificationOutcome",
    "RankedOpportunity",
    "ScoreComponent",
]
