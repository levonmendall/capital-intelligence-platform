from datetime import datetime, timedelta, timezone

import pytest

from institutional_market.score_guardrails import ScoreSnapshot, assess_score_guardrails


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _snapshot(day: int, score=70, status="active", policy="capital-intelligence-score.v2"):
    return ScoreSnapshot(
        as_of=START + timedelta(days=day),
        score=score,
        policy_version=policy,
        status=status,
    )


def test_healthy_score_history_does_not_suspend_v2():
    assessment = assess_score_guardrails(
        (_snapshot(0, 65), _snapshot(1, 68), _snapshot(2, 66))
    )
    assert assessment.healthy is True
    assert assessment.suspend_v2 is False
    assert assessment.rollback_to_policy is None


def test_large_score_jump_recommends_suspension_and_v1_rollback():
    assessment = assess_score_guardrails((_snapshot(0, 40), _snapshot(1, 80)))
    assert assessment.healthy is False
    assert assessment.suspend_v2 is True
    assert assessment.rollback_to_policy == "capital-intelligence-score.v1"


def test_unavailable_streak_and_policy_mismatch_are_detected():
    assessment = assess_score_guardrails(
        (
            _snapshot(0, policy="capital-intelligence-score.v3"),
            _snapshot(1, None, "unavailable"),
            _snapshot(2, None, "unavailable"),
            _snapshot(3, None, "unavailable"),
            _snapshot(4, None, "unavailable"),
        )
    )
    assert len(assessment.violations) == 2


def test_duplicate_timestamps_are_rejected():
    item = _snapshot(0)
    with pytest.raises(ValueError, match="duplicate"):
        assess_score_guardrails((item, item))
