from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from evaluation.forecast_calibration import ForecastCalibrationEngine
from evaluation.forecast_registry import (
    ForecastClass,
    ForecastDirection,
    ForecastRecord,
    ForecastRegistryIntegrityError,
    SQLiteForecastRegistry,
)
from evaluation.forecast_resolution import ForecastResolver, ResolutionState


CREATED = datetime(2026, 8, 3, tzinfo=UTC)


def _forecast(identifier: str = "forecast:1", probability: float = 0.7) -> ForecastRecord:
    return ForecastRecord(
        identifier=identifier,
        claim="Inflation is between 2 and 3 percent.",
        forecast_class=ForecastClass.INFLATION,
        target_variable="CPI year over year",
        direction=ForecastDirection.BETWEEN,
        range_low=0.02,
        range_high=0.03,
        probability=probability,
        created_at=CREATED,
        horizon_end=CREATED + timedelta(days=30),
        resolution_date=CREATED + timedelta(days=31),
        resolution_source="official CPI release",
        resolution_rule="Use first published year-over-year CPI for the target month.",
        evidence_cutoff=CREATED,
        model_version="forecast-model.v1",
        engine_identifier="macro-specialist",
        base_rate=0.55,
    )


def test_registry_preserves_revisions_and_resolution_rules(tmp_path):
    registry = SQLiteForecastRegistry(tmp_path / "forecasts.sqlite")
    original = _forecast()
    registry.append(original)
    revision = replace(
        original,
        identifier="forecast:1:revision:1",
        probability=0.6,
        parent_identifier=original.identifier,
        model_version="forecast-model.v2",
    )
    registry.append(revision)
    assert len(registry.records()) == 2
    registry.verify()
    with pytest.raises(ForecastRegistryIntegrityError):
        registry.append(replace(revision, identifier="bad", resolution_rule="Changed later"))


def test_resolution_and_calibration_are_measurable():
    resolver = ForecastResolver()
    forecasts = tuple(
        _forecast(f"f:{index}", probability)
        for index, probability in enumerate((0.8, 0.7, 0.4), start=1)
    )
    resolutions = tuple(
        resolver.resolve(
            forecast,
            resolved_at=forecast.resolution_date,
            observed_value=value,
            resolution_source_identifier="cpi:release",
        )
        for forecast, value in zip(forecasts, (0.025, 0.028, 0.04), strict=True)
    )
    assert all(item.state is ResolutionState.RESOLVED for item in resolutions)
    report = ForecastCalibrationEngine().build(
        tuple(zip(forecasts, resolutions, strict=True)),
        as_of=CREATED + timedelta(days=32),
    )
    assert report.count == 3
    assert report.brier_score >= 0.0
    assert not report.policy_change_authorized
