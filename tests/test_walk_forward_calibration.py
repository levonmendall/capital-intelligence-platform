from datetime import datetime, timedelta, timezone

import pytest

from institutional_market.walk_forward import (
    ShadowDecisionObservation,
    evaluate_walk_forward,
)


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _observation(day: int, stance: str, **overrides):
    values = {
        "as_of": START + timedelta(days=day),
        "stance": stance,
        "outcome": "monitor",
        "confidence": 70,
        "data_quality": 85,
        "veto_active": False,
        "subsequent_stress": False,
        "used_future_data": False,
    }
    values.update(overrides)
    return ShadowDecisionObservation(**values)


def test_walk_forward_reports_stability_detection_and_no_return_optimization():
    report = evaluate_walk_forward(
        (
            _observation(0, "constructive"),
            _observation(1, "constructive"),
            _observation(2, "neutral", subsequent_stress=True),
            _observation(3, "defensive", subsequent_stress=True, veto_active=True),
        )
    )
    assert report.observation_count == 4
    assert report.stance_change_count == 2
    assert report.timely_deterioration_count == 2
    assert report.missed_deterioration_count == 0
    assert report.weights_optimized_for_return is False
    assert report.leakage_free is True


def test_unavailable_decisions_are_disclosed_not_treated_as_stances():
    report = evaluate_walk_forward(
        (
            _observation(0, "decision_unavailable", confidence=None, data_quality=None),
            _observation(1, "neutral"),
        )
    )
    assert report.available_count == 1
    assert report.unavailable_count == 1
    assert report.turnover_rate == 0


def test_future_data_violation_is_counted():
    report = evaluate_walk_forward(
        (_observation(0, "constructive", used_future_data=True),)
    )
    assert report.look_ahead_violation_count == 1
    assert report.leakage_free is False


def test_duplicate_timestamps_and_empty_input_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        evaluate_walk_forward(())
    item = _observation(0, "neutral")
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_walk_forward((item, item))
