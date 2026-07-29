"""Machine-testable thesis and invalidation conditions.

Structured conditions replace prose-keyword scoring. Each condition identifies
what is measured, how it is compared, where it comes from, how long it must
persist, and what the review consequence is when it triggers or is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class ThesisConditionOperator(str, Enum):
    ABOVE = "above"
    AT_OR_ABOVE = "at_or_above"
    BELOW = "below"
    AT_OR_BELOW = "at_or_below"
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"


class MissingDataBehavior(str, Enum):
    FAIL_CLOSED = "fail_closed"
    REQUIRE_REVIEW = "require_review"
    PRESERVE_PRIOR_STATE = "preserve_prior_state"


class ThesisConditionConsequence(str, Enum):
    SUPPORT = "support"
    REVIEW_INCREASE = "review_increase"
    REVIEW_REDUCE = "review_reduce"
    REVIEW_EXIT = "review_exit"
    INVALIDATE = "invalidate"


def _text(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ThesisCondition:
    identifier: str
    metric_identifier: str
    operator: ThesisConditionOperator
    threshold: float
    observation_window_days: int
    required_persistence: int
    source_identifier: str
    missing_data_behavior: MissingDataBehavior
    consequence: ThesisConditionConsequence

    def __post_init__(self) -> None:
        for name in ("identifier", "metric_identifier", "source_identifier"):
            object.__setattr__(self, name, _text(getattr(self, name), name=name))
        if not isinstance(self.operator, ThesisConditionOperator):
            raise TypeError("operator must be ThesisConditionOperator")
        if not isinstance(self.missing_data_behavior, MissingDataBehavior):
            raise TypeError("missing_data_behavior must be MissingDataBehavior")
        if not isinstance(self.consequence, ThesisConditionConsequence):
            raise TypeError("consequence must be ThesisConditionConsequence")
        if isinstance(self.threshold, bool) or not isinstance(self.threshold, (int, float)):
            raise TypeError("threshold must be numeric")
        normalized = float(self.threshold)
        if not isfinite(normalized):
            raise ValueError("threshold must be finite")
        object.__setattr__(self, "threshold", normalized)
        for name in ("observation_window_days", "required_persistence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1:
                raise ValueError(f"{name} must be positive")

    def evaluate(self, value: float) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("condition observation must be numeric")
        observation = float(value)
        if not isfinite(observation):
            raise ValueError("condition observation must be finite")
        if self.operator is ThesisConditionOperator.ABOVE:
            return observation > self.threshold
        if self.operator is ThesisConditionOperator.AT_OR_ABOVE:
            return observation >= self.threshold
        if self.operator is ThesisConditionOperator.BELOW:
            return observation < self.threshold
        if self.operator is ThesisConditionOperator.AT_OR_BELOW:
            return observation <= self.threshold
        if self.operator is ThesisConditionOperator.EQUAL:
            return observation == self.threshold
        return observation != self.threshold


@dataclass(frozen=True, slots=True)
class StructuredThesisQuality:
    score: float
    complete_condition_count: int
    fail_closed_count: int
    source_count: int
    reasons: tuple[str, ...]


class StructuredThesisConditionScorer:
    version = "structured-thesis-condition-score.v1"

    def score(self, conditions: tuple[ThesisCondition, ...]) -> StructuredThesisQuality:
        if not isinstance(conditions, tuple) or not all(isinstance(item, ThesisCondition) for item in conditions):
            raise TypeError("conditions must contain ThesisCondition values")
        if not conditions:
            return StructuredThesisQuality(
                score=0.0,
                complete_condition_count=0,
                fail_closed_count=0,
                source_count=0,
                reasons=("no structured thesis conditions were supplied",),
            )
        identifiers = tuple(item.identifier for item in conditions)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("structured thesis condition identifiers must be unique")
        sources = {item.source_identifier for item in conditions}
        fail_closed = sum(
            item.missing_data_behavior is MissingDataBehavior.FAIL_CLOSED
            for item in conditions
        )
        consequence_coverage = len({item.consequence for item in conditions})
        persistence_quality = sum(min(1.0, item.required_persistence / 2.0) for item in conditions) / len(conditions)
        window_quality = sum(min(1.0, item.observation_window_days / 30.0) for item in conditions) / len(conditions)
        source_quality = min(1.0, len(sources) / len(conditions))
        fail_closed_quality = fail_closed / len(conditions)
        consequence_quality = min(1.0, consequence_coverage / 2.0)
        score = round(
            0.25 * persistence_quality
            + 0.20 * window_quality
            + 0.25 * source_quality
            + 0.20 * fail_closed_quality
            + 0.10 * consequence_quality,
            8,
        )
        return StructuredThesisQuality(
            score=score,
            complete_condition_count=len(conditions),
            fail_closed_count=fail_closed,
            source_count=len(sources),
            reasons=(
                f"{len(conditions)} machine-testable condition(s)",
                f"{len(sources)} independent source identifier(s)",
                f"{fail_closed} condition(s) fail closed on missing data",
            ),
        )


__all__ = [
    "MissingDataBehavior",
    "StructuredThesisConditionScorer",
    "StructuredThesisQuality",
    "ThesisCondition",
    "ThesisConditionConsequence",
    "ThesisConditionOperator",
]
