from institutional_market.score_v2 import ScoreV2Status, activate_score_v2


def _decision(**overrides):
    value = {
        "outcome": "approve",
        "stance": "constructive",
        "opportunity_score": 75,
        "risk_score": 35,
        "confidence_score": 80,
        "data_quality_score": 90,
    }
    value.update(overrides)
    return value


APPROVED = {"status": "approved", "score_activation_authorized": True}
AUTHORITATIVE = {"status": "authoritative"}


def test_score_v2_activates_only_after_both_gates_and_preserves_v1():
    result = activate_score_v2(_decision(), APPROVED, AUTHORITATIVE)
    assert result.status is ScoreV2Status.ACTIVE
    assert result.score == 74
    assert result.preserved_prior_policy_version == "capital-intelligence-score.v1"
    assert result.personal_cio_action_affected is False
    assert result.transaction_authority is False


def test_non_authoritative_data_or_unapproved_shadow_withholds_score():
    data_blocked = activate_score_v2(_decision(), APPROVED, {"status": "partial"})
    approval_blocked = activate_score_v2(
        _decision(),
        {"status": "extend_shadow", "score_activation_authorized": False},
        AUTHORITATIVE,
    )
    assert data_blocked.status is ScoreV2Status.UNAVAILABLE
    assert approval_blocked.status is ScoreV2Status.UNAVAILABLE


def test_stance_and_veto_ceiling_prevents_false_precision():
    defensive = activate_score_v2(
        _decision(stance="defensive", opportunity_score=95, risk_score=10),
        APPROVED,
        AUTHORITATIVE,
    )
    vetoed = activate_score_v2(
        _decision(
            outcome="vetoed",
            stance="constructive",
            opportunity_score=95,
            risk_score=10,
        ),
        APPROVED,
        AUTHORITATIVE,
    )
    assert defensive.score == 49
    assert vetoed.score == 49


def test_incomplete_committee_dimensions_withhold_score():
    result = activate_score_v2(
        _decision(confidence_score=None),
        APPROVED,
        AUTHORITATIVE,
    )
    assert result.status is ScoreV2Status.UNAVAILABLE
    assert result.score is None
