"""Deterministic resolution of immutable claim-level forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import log
from typing import Any

from evaluation.forecast_registry import ForecastDirection, ForecastRecord


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True, slots=True)
class ForecastResolution:
    forecast_identifier: str
    resolved_at: datetime
    state: ResolutionState
    observed_value: float | bool | None
    outcome: bool | None
    brier_score: float | None
    logarithmic_score: float | None
    resolution_source_identifier: str | None
    detail: str
    schema_version: str = "forecast-resolution.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_identifier": self.forecast_identifier,
            "resolved_at": self.resolved_at.isoformat(),
            "state": self.state.value,
            "observed_value": self.observed_value,
            "outcome": self.outcome,
            "brier_score": self.brier_score,
            "logarithmic_score": self.logarithmic_score,
            "resolution_source_identifier": self.resolution_source_identifier,
            "detail": self.detail,
        }


class ForecastResolver:
    def resolve(
        self,
        forecast: ForecastRecord,
        *,
        resolved_at: datetime,
        observed_value: float | bool | None,
        resolution_source_identifier: str | None,
        source_available: bool = True,
    ) -> ForecastResolution:
        if resolved_at.tzinfo is None or resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be timezone-aware")
        if resolved_at < forecast.resolution_date:
            return ForecastResolution(
                forecast.identifier,
                resolved_at,
                ResolutionState.UNRESOLVED,
                observed_value,
                None,
                None,
                None,
                resolution_source_identifier,
                "Resolution date has not arrived.",
            )
        if not source_available or observed_value is None:
            return ForecastResolution(
                forecast.identifier,
                resolved_at,
                ResolutionState.UNRESOLVABLE,
                observed_value,
                None,
                None,
                None,
                resolution_source_identifier,
                "The fixed resolution source is unavailable; the forecast remains visible.",
            )
        if forecast.direction is ForecastDirection.OCCURS:
            outcome = bool(observed_value)
        elif forecast.direction is ForecastDirection.DOES_NOT_OCCUR:
            outcome = not bool(observed_value)
        elif forecast.direction is ForecastDirection.ABOVE:
            if forecast.range_high is None:
                raise ValueError("above forecast requires range_high threshold")
            outcome = float(observed_value) > float(forecast.range_high)
        elif forecast.direction is ForecastDirection.BELOW:
            if forecast.range_low is None:
                raise ValueError("below forecast requires range_low threshold")
            outcome = float(observed_value) < float(forecast.range_low)
        else:
            if forecast.range_low is None or forecast.range_high is None:
                raise ValueError("between forecast requires range")
            outcome = float(forecast.range_low) <= float(observed_value) <= float(forecast.range_high)
        target = 1.0 if outcome else 0.0
        probability = min(1.0 - 1e-12, max(1e-12, float(forecast.probability)))
        brier = round((probability - target) ** 2, 8)
        log_score = round(-(log(probability) if outcome else log(1.0 - probability)), 8)
        return ForecastResolution(
            forecast.identifier,
            resolved_at,
            ResolutionState.RESOLVED,
            observed_value,
            outcome,
            brier,
            log_score,
            resolution_source_identifier,
            "Resolved using the rule and source fixed at forecast creation.",
        )


__all__ = ["ForecastResolution", "ForecastResolver", "ResolutionState"]
