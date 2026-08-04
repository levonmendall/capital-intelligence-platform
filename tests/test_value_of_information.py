from datetime import datetime, timedelta, timezone

from research.value_of_information import (
    ResearchStatus,
    UnresolvedAssumption,
    ValueOfInformationPlanner,
)


def _assumption(identifier, *, approved=True, cost=0.05, sensitivity=0.8):
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    return UnresolvedAssumption(
        identifier=identifier,
        question="Is the margin decline cyclical or structural?",
        current_uncertainty=0.9,
        decision_identifier="candidate-1",
        potential_action_change="BUY to WATCH",
        decision_sensitivity=sensitivity,
        resolution_probability=0.8,
        required_source="licensed-consensus",
        provider_approved=approved,
        collection_cost=cost,
        deadline=now + timedelta(days=3),
        resolution_criteria="Two independent quarters separate the alternatives.",
    )


def test_questions_rank_by_decision_value_and_deduplicate():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    plans = ValueOfInformationPlanner().plan(
        (_assumption("high"), _assumption("duplicate", sensitivity=0.2)),
        created_at=now,
    )
    assert len(plans[0].questions) == 1
    assert plans[0].questions[0].expected_information_value > 0


def test_unapproved_provider_is_blocked_not_collected():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    question = ValueOfInformationPlanner().plan(
        (_assumption("blocked", approved=False),), created_at=now
    )[0].questions[0]
    assert question.status is ResearchStatus.BLOCKED_PROVIDER
    assert question.to_dict()["bypasses_provider_governance"] is False
