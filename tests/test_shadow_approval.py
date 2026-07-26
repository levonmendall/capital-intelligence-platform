from institutional_market.shadow_approval import (
    ShadowApprovalStatus,
    review_shadow_mode,
)


def _report(**overrides):
    report = {
        "observation_count": 30,
        "available_count": 30,
        "turnover_rate": 0.2,
        "timely_deterioration_count": 4,
        "missed_deterioration_count": 0,
        "false_alarm_count": 2,
        "median_confidence": 70,
        "minimum_data_quality": 75,
        "leakage_free": True,
        "weights_optimized_for_return": False,
    }
    report.update(overrides)
    return report


def test_clean_shadow_review_authorizes_score_activation_without_policy_changes():
    decision = review_shadow_mode(_report(), production_data_authoritative=True)
    assert decision.status is ShadowApprovalStatus.APPROVED
    assert decision.score_activation_authorized is True
    assert decision.weights_changed is False
    assert decision.committee_policy_changed is False


def test_short_or_low_quality_history_extends_shadow_mode():
    decision = review_shadow_mode(
        _report(observation_count=10, available_count=10, minimum_data_quality=45),
        production_data_authoritative=True,
    )
    assert decision.status is ShadowApprovalStatus.EXTEND_SHADOW
    assert decision.score_activation_authorized is False
    assert len(decision.reasons) >= 2


def test_non_authoritative_data_blocks_activation():
    decision = review_shadow_mode(_report(), production_data_authoritative=False)
    assert decision.status is ShadowApprovalStatus.EXTEND_SHADOW
    assert "authoritative" in decision.reasons[0]


def test_leakage_or_return_optimized_weights_rejects_review():
    leakage = review_shadow_mode(
        _report(leakage_free=False),
        production_data_authoritative=True,
    )
    optimized = review_shadow_mode(
        _report(weights_optimized_for_return=True),
        production_data_authoritative=True,
    )
    assert leakage.status is ShadowApprovalStatus.REJECTED
    assert optimized.status is ShadowApprovalStatus.REJECTED
