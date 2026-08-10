"""Point-in-time forecast and specialist calibration research.

Calibration reports are advisory evidence only.  They may lower future confidence
through existing governed learning paths but cannot automatically raise expected
return, increase position size, promote thresholds, or authorize execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean


@dataclass(frozen=True, slots=True)
class ForecastCalibrationObservation:
    identifier: str
    predicted_at: datetime
    resolved_at: datetime
    predicted_success_probability: float
    realized_success: bool
    predicted_return: float
    realized_return: float
    predicted_drawdown: float
    realized_drawdown: float
    regime: str
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.predicted_at.tzinfo is None or self.predicted_at.utcoffset() is None:
            raise ValueError("predicted_at must be timezone-aware")
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be timezone-aware")
        if self.resolved_at < self.predicted_at:
            raise ValueError("forecast cannot resolve before prediction")
        if not 0.0 <= float(self.predicted_success_probability) <= 1.0:
            raise ValueError("predicted probability must be between zero and one")
        for name in (
            "predicted_return",
            "realized_return",
            "predicted_drawdown",
            "realized_drawdown",
        ):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if not self.evidence_identifiers:
            raise ValueError("calibration observation requires evidence identifiers")


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    lower_probability: float
    upper_probability: float
    sample_size: int
    mean_predicted_probability: float
    realized_success_rate: float


@dataclass(frozen=True, slots=True)
class ForecastCalibrationReport:
    sample_size: int
    brier_score: float
    return_mean_absolute_error: float
    return_bias: float
    drawdown_mean_absolute_error: float
    worst_tail_underestimate: float
    buckets: tuple[CalibrationBucket, ...]
    evidence_identifiers: tuple[str, ...]
    policy_promotion_authorized: bool = False
    may_increase_confidence: bool = False
    may_increase_position_size: bool = False
    schema_version: str = "forecast-calibration-report.v1"


@dataclass(frozen=True, slots=True)
class SpecialistCalibrationObservation:
    role: str
    confidence: float
    signed_expected_impact: float
    realized_return: float


@dataclass(frozen=True, slots=True)
class SpecialistCalibrationReport:
    role: str
    sample_size: int
    mean_confidence: float
    directional_hit_rate: float
    impact_bias: float
    confidence_ceiling: float
    policy_promotion_authorized: bool = False


class ForecastCalibrationEngine:
    version = "forecast-calibration.v1"

    def evaluate(
        self,
        observations: tuple[ForecastCalibrationObservation, ...],
        *,
        bucket_width: float = 0.10,
    ) -> ForecastCalibrationReport:
        if not observations:
            raise ValueError("forecast calibration requires observations")
        if not 0.05 <= bucket_width <= 0.50:
            raise ValueError("bucket_width must be between 0.05 and 0.50")
        brier = fmean(
            (item.predicted_success_probability - float(item.realized_success)) ** 2
            for item in observations
        )
        return_errors = tuple(
            item.realized_return - item.predicted_return for item in observations
        )
        drawdown_errors = tuple(
            item.realized_drawdown - item.predicted_drawdown for item in observations
        )
        bucket_count = int(round(1.0 / bucket_width))
        buckets = []
        for index in range(bucket_count):
            low = index * bucket_width
            high = 1.0 if index == bucket_count - 1 else (index + 1) * bucket_width
            values = tuple(
                item
                for item in observations
                if low <= item.predicted_success_probability <= high
                and (index == bucket_count - 1 or item.predicted_success_probability < high)
            )
            if not values:
                continue
            buckets.append(
                CalibrationBucket(
                    lower_probability=round(low, 8),
                    upper_probability=round(high, 8),
                    sample_size=len(values),
                    mean_predicted_probability=round(
                        fmean(item.predicted_success_probability for item in values), 8
                    ),
                    realized_success_rate=round(
                        fmean(float(item.realized_success) for item in values), 8
                    ),
                )
            )
        evidence = tuple(
            dict.fromkeys(
                identifier
                for item in observations
                for identifier in item.evidence_identifiers
            )
        )
        return ForecastCalibrationReport(
            sample_size=len(observations),
            brier_score=round(brier, 8),
            return_mean_absolute_error=round(fmean(abs(item) for item in return_errors), 8),
            return_bias=round(fmean(return_errors), 8),
            drawdown_mean_absolute_error=round(
                fmean(abs(item) for item in drawdown_errors), 8
            ),
            worst_tail_underestimate=round(min(0.0, min(drawdown_errors)), 8),
            buckets=tuple(buckets),
            evidence_identifiers=evidence,
        )

    def evaluate_specialists(
        self,
        observations: tuple[SpecialistCalibrationObservation, ...],
    ) -> tuple[SpecialistCalibrationReport, ...]:
        grouped: dict[str, list[SpecialistCalibrationObservation]] = {}
        for item in observations:
            if not 0.0 <= float(item.confidence) <= 1.0:
                raise ValueError("specialist confidence must be between zero and one")
            grouped.setdefault(item.role, []).append(item)
        reports = []
        for role, values in sorted(grouped.items()):
            hit_rate = fmean(
                float(
                    (item.signed_expected_impact >= 0.0 and item.realized_return >= 0.0)
                    or (item.signed_expected_impact < 0.0 and item.realized_return < 0.0)
                )
                for item in values
            )
            mean_confidence = fmean(item.confidence for item in values)
            bias = fmean(
                item.realized_return - item.signed_expected_impact for item in values
            )
            calibration_penalty = abs(mean_confidence - hit_rate)
            reports.append(
                SpecialistCalibrationReport(
                    role=role,
                    sample_size=len(values),
                    mean_confidence=round(mean_confidence, 8),
                    directional_hit_rate=round(hit_rate, 8),
                    impact_bias=round(bias, 8),
                    confidence_ceiling=round(
                        max(0.25, min(1.0, mean_confidence - calibration_penalty)), 8
                    ),
                )
            )
        return tuple(reports)


__all__ = [
    "CalibrationBucket",
    "ForecastCalibrationEngine",
    "ForecastCalibrationObservation",
    "ForecastCalibrationReport",
    "SpecialistCalibrationObservation",
    "SpecialistCalibrationReport",
]
