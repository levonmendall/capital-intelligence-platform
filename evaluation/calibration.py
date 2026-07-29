"""Separate calibration for forecasts, actions, abstentions, and controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite

from cio import CIOAction
from evaluation.point_in_time import (
    DecisionEvidenceSnapshot,
    EvaluationOutcome,
    PointInTimeDecisionEvaluation,
)


class CalibrationDimension(str, Enum):
    FORECAST = "forecast"
    POSITIVE_ACTION = "positive_action"
    ABSTENTION = "abstention"
    EVIDENCE_VETO = "evidence_veto"
    IMPLEMENTATION_BLOCK = "implementation_block"


@dataclass(frozen=True, slots=True)
class CalibrationMetric:
    dimension: CalibrationDimension
    count: int
    mean_probability: float
    observed_success_rate: float
    mean_brier_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, CalibrationDimension):
            raise TypeError("dimension must be CalibrationDimension")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("count must be an integer")
        if self.count < 1:
            raise ValueError("calibration metric count must be positive")
        for name in ("mean_probability", "observed_success_rate", "mean_brier_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class DecisionCalibrationSuite:
    as_of: datetime
    metrics: tuple[CalibrationMetric, ...]
    policy_version: str = "decision-calibration-suite.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.as_of, datetime) or self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if not isinstance(self.metrics, tuple) or not all(isinstance(item, CalibrationMetric) for item in self.metrics):
            raise TypeError("metrics must contain CalibrationMetric values")
        dimensions = tuple(item.dimension for item in self.metrics)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("calibration dimensions must be unique")


class DecisionCalibrationSuiteBuilder:
    """Do not score correct inaction as a failed positive action."""

    _POSITIVE = {CIOAction.BUY, CIOAction.INCREASE, CIOAction.HOLD}
    _CORRECT_INACTION = {
        EvaluationOutcome.CORRECT_ABSTENTION,
        EvaluationOutcome.AVOIDED_LOSS,
        EvaluationOutcome.INSUFFICIENT_EVIDENCE_CONFIRMED,
    }

    def build(
        self,
        pairs: tuple[tuple[DecisionEvidenceSnapshot, PointInTimeDecisionEvaluation], ...],
        *,
        as_of: datetime,
    ) -> DecisionCalibrationSuite:
        if not isinstance(pairs, tuple) or not pairs:
            raise ValueError("calibration requires snapshot/evaluation pairs")
        grouped: dict[CalibrationDimension, list[tuple[float, float]]] = {}
        for snapshot, evaluation in pairs:
            if evaluation.snapshot_identifier != snapshot.identifier:
                raise ValueError("calibration pair identifiers do not match")
            forecast_success = evaluation.candidate_return > evaluation.best_original_alternative_return
            grouped.setdefault(CalibrationDimension.FORECAST, []).append(
                (snapshot.probability_of_success, 1.0 if forecast_success else 0.0)
            )
            if snapshot.action in self._POSITIVE:
                grouped.setdefault(CalibrationDimension.POSITIVE_ACTION, []).append(
                    (
                        snapshot.final_confidence,
                        1.0 if evaluation.outcome in {EvaluationOutcome.VALUE_ADDED, EvaluationOutcome.MATCHED_ALTERNATIVE} else 0.0,
                    )
                )
            else:
                grouped.setdefault(CalibrationDimension.ABSTENTION, []).append(
                    (
                        snapshot.final_confidence,
                        1.0 if evaluation.outcome in self._CORRECT_INACTION else 0.0,
                    )
                )
            if snapshot.evidence_vetoes:
                grouped.setdefault(CalibrationDimension.EVIDENCE_VETO, []).append(
                    (
                        snapshot.final_confidence,
                        1.0 if evaluation.outcome in {EvaluationOutcome.INSUFFICIENT_EVIDENCE_CONFIRMED, EvaluationOutcome.AVOIDED_LOSS} else 0.0,
                    )
                )
            if snapshot.implementation_blocks:
                grouped.setdefault(CalibrationDimension.IMPLEMENTATION_BLOCK, []).append(
                    (
                        1.0 - snapshot.final_confidence,
                        1.0 if evaluation.outcome is not EvaluationOutcome.IMPLEMENTATION_BLOCK_COSTLY else 0.0,
                    )
                )
        metrics: list[CalibrationMetric] = []
        for dimension in CalibrationDimension:
            values = grouped.get(dimension)
            if not values:
                continue
            count = len(values)
            mean_probability = sum(item[0] for item in values) / count
            success_rate = sum(item[1] for item in values) / count
            brier = sum((probability - target) ** 2 for probability, target in values) / count
            metrics.append(
                CalibrationMetric(
                    dimension=dimension,
                    count=count,
                    mean_probability=mean_probability,
                    observed_success_rate=success_rate,
                    mean_brier_score=brier,
                )
            )
        return DecisionCalibrationSuite(as_of=as_of, metrics=tuple(metrics))


__all__ = [
    "CalibrationDimension",
    "CalibrationMetric",
    "DecisionCalibrationSuite",
    "DecisionCalibrationSuiteBuilder",
]
