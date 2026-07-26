"""Walk-forward calibration and shadow-mode evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ShadowDecisionObservation:
    as_of: datetime
    stance: str
    outcome: str
    confidence: int | None
    data_quality: int | None
    veto_active: bool
    subsequent_stress: bool
    used_future_data: bool = False

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        for value in (self.confidence, self.data_quality):
            if value is not None and not 0 <= value <= 100:
                raise ValueError("scores must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class WalkForwardCalibrationReport:
    observation_count: int
    available_count: int
    unavailable_count: int
    stance_change_count: int
    turnover_rate: float
    veto_rate: float
    timely_deterioration_count: int
    missed_deterioration_count: int
    false_alarm_count: int
    look_ahead_violation_count: int
    median_confidence: int | None
    minimum_data_quality: int | None
    weights_optimized_for_return: bool = False

    @property
    def leakage_free(self) -> bool:
        return self.look_ahead_violation_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "walk-forward-calibration-report.v1",
            "observation_count": self.observation_count,
            "available_count": self.available_count,
            "unavailable_count": self.unavailable_count,
            "stance_change_count": self.stance_change_count,
            "turnover_rate": self.turnover_rate,
            "veto_rate": self.veto_rate,
            "timely_deterioration_count": self.timely_deterioration_count,
            "missed_deterioration_count": self.missed_deterioration_count,
            "false_alarm_count": self.false_alarm_count,
            "look_ahead_violation_count": self.look_ahead_violation_count,
            "leakage_free": self.leakage_free,
            "median_confidence": self.median_confidence,
            "minimum_data_quality": self.minimum_data_quality,
            "weights_optimized_for_return": self.weights_optimized_for_return,
        }


def evaluate_walk_forward(
    observations: Iterable[ShadowDecisionObservation],
) -> WalkForwardCalibrationReport:
    values = tuple(sorted(observations, key=lambda item: item.as_of))
    if not values:
        raise ValueError("at least one shadow observation is required")
    if len({item.as_of for item in values}) != len(values):
        raise ValueError("duplicate decision timestamps are not allowed")

    available = tuple(item for item in values if item.stance != "decision_unavailable")
    changes = sum(
        current.stance != previous.stance
        for previous, current in zip(available, available[1:])
    )
    defensive = {"defensive", "neutral"}
    timely = sum(item.subsequent_stress and item.stance in defensive for item in available)
    missed = sum(item.subsequent_stress and item.stance not in defensive for item in available)
    false_alarms = sum(
        not item.subsequent_stress and item.stance == "defensive" for item in available
    )
    confidences = sorted(
        item.confidence for item in available if item.confidence is not None
    )
    qualities = [item.data_quality for item in available if item.data_quality is not None]
    median = None
    if confidences:
        middle = len(confidences) // 2
        median = (
            confidences[middle]
            if len(confidences) % 2
            else round((confidences[middle - 1] + confidences[middle]) / 2)
        )
    denominator = max(1, len(available) - 1)
    return WalkForwardCalibrationReport(
        observation_count=len(values),
        available_count=len(available),
        unavailable_count=len(values) - len(available),
        stance_change_count=changes,
        turnover_rate=round(changes / denominator, 4),
        veto_rate=round(sum(item.veto_active for item in values) / len(values), 4),
        timely_deterioration_count=timely,
        missed_deterioration_count=missed,
        false_alarm_count=false_alarms,
        look_ahead_violation_count=sum(item.used_future_data for item in values),
        median_confidence=median,
        minimum_data_quality=min(qualities) if qualities else None,
    )
