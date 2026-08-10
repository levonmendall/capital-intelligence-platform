from datetime import datetime, timedelta, timezone

from intelligence.forecast_calibration import (
    ForecastCalibrationEngine,
    ForecastCalibrationObservation,
    SpecialistCalibrationObservation,
)


def test_forecast_calibration_reports_brier_and_bias_without_promotion_authority() -> None:
    now = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    observations = (
        ForecastCalibrationObservation("a", now, now + timedelta(days=30), 0.8, True, 0.10, 0.08, -0.10, -0.12, "growth", ("a",)),
        ForecastCalibrationObservation("b", now, now + timedelta(days=30), 0.7, False, 0.05, -0.04, -0.08, -0.15, "growth", ("b",)),
    )
    report = ForecastCalibrationEngine().evaluate(observations)
    assert report.sample_size == 2
    assert report.brier_score > 0.0
    assert report.policy_promotion_authorized is False
    assert report.may_increase_confidence is False


def test_specialist_calibration_creates_conservative_confidence_ceiling() -> None:
    reports = ForecastCalibrationEngine().evaluate_specialists(
        (
            SpecialistCalibrationObservation("macro", 0.9, 0.05, -0.03),
            SpecialistCalibrationObservation("macro", 0.9, 0.05, 0.04),
        )
    )
    assert len(reports) == 1
    assert reports[0].confidence_ceiling <= reports[0].mean_confidence
    assert reports[0].policy_promotion_authorized is False
