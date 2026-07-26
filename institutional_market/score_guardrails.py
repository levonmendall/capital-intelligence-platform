"""Production guardrails for Capital Intelligence Score v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ScoreSnapshot:
    as_of: datetime
    score: int | None
    policy_version: str
    status: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.score is not None and not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class ScoreGuardrailPolicy:
    version: str = "score-v2-guardrails.v1"
    expected_score_policy: str = "capital-intelligence-score.v2"
    maximum_daily_change: int = 20
    maximum_unavailable_streak: int = 3
    maximum_recent_mean_shift: float = 15.0
    recent_window: int = 5
    baseline_window: int = 20


@dataclass(frozen=True, slots=True)
class ScoreGuardrailAssessment:
    policy_version: str
    healthy: bool
    violations: tuple[str, ...]
    suspend_v2: bool
    rollback_to_policy: str | None
    manual_review_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "score-v2-guardrail-assessment.v1",
            "policy_version": self.policy_version,
            "healthy": self.healthy,
            "violations": list(self.violations),
            "suspend_v2": self.suspend_v2,
            "rollback_to_policy": self.rollback_to_policy,
            "manual_review_required": self.manual_review_required,
        }


def assess_score_guardrails(
    snapshots: Iterable[ScoreSnapshot],
    policy: ScoreGuardrailPolicy = ScoreGuardrailPolicy(),
) -> ScoreGuardrailAssessment:
    values = tuple(sorted(snapshots, key=lambda item: item.as_of))
    violations: list[str] = []
    if not values:
        violations.append("score history is unavailable")
    if len({item.as_of for item in values}) != len(values):
        raise ValueError("duplicate score timestamps are not allowed")
    if any(item.policy_version != policy.expected_score_policy for item in values):
        violations.append("unexpected score policy version observed")

    available = tuple(item for item in values if item.score is not None and item.status == "active")
    for previous, current in zip(available, available[1:]):
        assert previous.score is not None and current.score is not None
        if abs(current.score - previous.score) > policy.maximum_daily_change:
            violations.append("unexpected score change exceeds the daily threshold")
            break

    unavailable_streak = 0
    maximum_streak = 0
    for item in values:
        if item.score is None or item.status != "active":
            unavailable_streak += 1
            maximum_streak = max(maximum_streak, unavailable_streak)
        else:
            unavailable_streak = 0
    if maximum_streak > policy.maximum_unavailable_streak:
        violations.append("score unavailable streak exceeds the policy maximum")

    scores = [item.score for item in available if item.score is not None]
    if len(scores) >= policy.baseline_window + policy.recent_window:
        baseline = scores[-(policy.baseline_window + policy.recent_window):-policy.recent_window]
        recent = scores[-policy.recent_window:]
        baseline_mean = sum(baseline) / len(baseline)
        recent_mean = sum(recent) / len(recent)
        if abs(recent_mean - baseline_mean) > policy.maximum_recent_mean_shift:
            violations.append("recent score distribution shifted beyond the policy threshold")

    unique = tuple(dict.fromkeys(violations))
    suspend = bool(unique)
    return ScoreGuardrailAssessment(
        policy_version=policy.version,
        healthy=not unique,
        violations=unique,
        suspend_v2=suspend,
        rollback_to_policy="capital-intelligence-score.v1" if suspend else None,
        manual_review_required=suspend,
    )
