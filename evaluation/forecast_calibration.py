"""Calibration and skill reporting for claim-level forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from evaluation.forecast_registry import ForecastRecord
from evaluation.forecast_resolution import ForecastResolution, ResolutionState


@dataclass(frozen=True, slots=True)
class ProbabilityBucket:
    lower: float
    upper: float
    count: int
    mean_probability: float
    observed_rate: float
    mean_brier_score: float


@dataclass(frozen=True, slots=True)
class ForecastCalibrationReport:
    as_of: datetime
    count: int
    brier_score: float
    logarithmic_score: float
    base_rate_brier_score: float
    improvement_over_base_rate: float
    hit_rate: float
    buckets: tuple[ProbabilityBucket, ...]
    confidence_cap: float | None
    policy_change_authorized: bool = False
    schema_version: str = "forecast-calibration-report.v1"


class ForecastCalibrationEngine:
    def build(
        self,
        pairs: tuple[tuple[ForecastRecord, ForecastResolution], ...],
        *,
        as_of: datetime,
    ) -> ForecastCalibrationReport:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        resolved = tuple(
            (forecast, resolution)
            for forecast, resolution in pairs
            if resolution.state is ResolutionState.RESOLVED
            and resolution.outcome is not None
            and resolution.brier_score is not None
            and resolution.logarithmic_score is not None
        )
        if not resolved:
            raise ValueError("at least one resolved forecast is required")
        for forecast, resolution in resolved:
            if forecast.identifier != resolution.forecast_identifier:
                raise ValueError("forecast and resolution identifiers do not match")
        count = len(resolved)
        brier = sum(float(item[1].brier_score) for item in resolved) / count
        log_score = sum(float(item[1].logarithmic_score) for item in resolved) / count
        base_brier = sum(
            (float(forecast.base_rate) - (1.0 if resolution.outcome else 0.0)) ** 2
            for forecast, resolution in resolved
        ) / count
        hit_rate = sum(
            1
            for forecast, resolution in resolved
            if (forecast.probability >= 0.5) == resolution.outcome
        ) / count
        buckets: list[ProbabilityBucket] = []
        for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
            upper = lower + 0.2
            members = tuple(
                (forecast, resolution)
                for forecast, resolution in resolved
                if lower <= forecast.probability <= upper
                and (upper == 1.0 or forecast.probability < upper)
            )
            if not members:
                continue
            buckets.append(
                ProbabilityBucket(
                    lower=lower,
                    upper=upper,
                    count=len(members),
                    mean_probability=round(
                        sum(item[0].probability for item in members) / len(members), 8
                    ),
                    observed_rate=round(
                        sum(1.0 if item[1].outcome else 0.0 for item in members)
                        / len(members),
                        8,
                    ),
                    mean_brier_score=round(
                        sum(float(item[1].brier_score) for item in members)
                        / len(members),
                        8,
                    ),
                )
            )
        confidence_cap = None
        if count >= 20 and brier > base_brier:
            confidence_cap = 0.65
        elif count >= 50 and brier > 0.25:
            confidence_cap = 0.55
        return ForecastCalibrationReport(
            as_of=as_of,
            count=count,
            brier_score=round(brier, 8),
            logarithmic_score=round(log_score, 8),
            base_rate_brier_score=round(base_brier, 8),
            improvement_over_base_rate=round(base_brier - brier, 8),
            hit_rate=round(hit_rate, 8),
            buckets=tuple(buckets),
            confidence_cap=confidence_cap,
        )


__all__ = [
    "ForecastCalibrationEngine",
    "ForecastCalibrationReport",
    "ProbabilityBucket",
]
