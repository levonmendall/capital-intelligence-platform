"""Contract tests for investor objectives and the Personal CIO Brief."""

from datetime import date, datetime, timezone

import pytest

from personal_cio import (
    ActionStatus,
    GoalPriority,
    GoalType,
    InvestmentPolicyProfile,
    InvestorGoal,
    RiskCapacity,
    RiskPreference,
    SQLiteInvestmentPolicyStore,
    brief_to_dict,
    build_personal_cio_brief,
)

NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def _profile(identifier: str = "policy:1") -> InvestmentPolicyProfile:
    return InvestmentPolicyProfile(
        identifier=identifier,
        investor_identifier="investor:1",
        version="investment-policy.v1",
        effective_at=NOW,
        primary_objective="long_term_growth",
        time_horizon_years=15,
        risk_capacity=RiskCapacity.HIGH,
        risk_preference=RiskPreference.MODERATE,
        required_return=0.06,
        maximum_tolerable_drawdown=0.2,
        minimum_liquidity_months=12,
    )


def _goal(identifier: str = "goal:1") -> InvestorGoal:
    return InvestorGoal(
        identifier=identifier,
        goal_key="retirement",
        investor_identifier="investor:1",
        version="investor-goal.v1",
        name="Retirement",
        goal_type=GoalType.RETIREMENT,
        priority=GoalPriority.ESSENTIAL,
        effective_at=NOW,
        target_date=date(2041, 7, 25),
        target_amount=1_000_000,
        funded_amount=300_000,
        portfolio_codes=("GROWTH",),
    )


def _snapshot(*, should_alert: bool = False) -> dict:
    return {
        "identifier": "daily:1",
        "as_of": NOW.isoformat(),
        "status": "current",
        "score": {
            "confidence": 0.82,
            "portfolio_impact": "Maintain diversified risk.",
        },
        "environment": {
            "summary": "Liquidity remains supportive.",
            "review_conditions": [
                "Review if credit weakens materially."
            ],
        },
        "decision_card": {
            "portfolio_impact": "Maintain diversified risk."
        },
        "change": {
            "explanation": "Credit conditions weakened modestly."
        },
        "change_summary": "Credit conditions weakened modestly.",
        "should_alert": should_alert,
        "sources": {
            "regime_run": "run:1",
            "decision": "decision:1",
        },
    }


def test_store_is_append_only_and_returns_latest_versions(tmp_path) -> None:
    store = SQLiteInvestmentPolicyStore(tmp_path / "policy.db")
    store.append_profile(_profile())
    store.append_goal(_goal())

    assert store.latest_profile("investor:1").identifier == "policy:1"
    assert store.goals("investor:1")[0].identifier == "goal:1"

    import sqlite3

    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE investment_policy_profiles "
                "SET investor_identifier = 'changed'"
            )


def test_missing_policy_is_disclosed_not_inferred() -> None:
    brief = build_personal_cio_brief(
        "investor:1",
        daily_snapshot=_snapshot(),
        profile=None,
        goals=(),
        portfolios=(),
        generated_at=NOW,
    )

    assert brief.action_status is ActionStatus.MONITOR
    assert brief.portfolio_alignment.score is None
    assert "No objective" in brief.portfolio_alignment.explanation


def test_no_action_is_a_formal_successful_outcome() -> None:
    brief = build_personal_cio_brief(
        "investor:1",
        daily_snapshot=_snapshot(),
        profile=_profile(),
        goals=(_goal(),),
        portfolios=(
            {
                "code": "GROWTH",
                "risk": "moderate",
                "nav": 500_000,
                "cash": 100_000,
            },
        ),
        generated_at=NOW,
    )
    payload = brief_to_dict(brief)

    assert brief.action_status is ActionStatus.NO_ACTION
    assert payload["portfolio_alignment"][
        "is_goal_success_probability"
    ] is False
    assert payload["what_changed"]
    assert payload["why_it_matters"]
    assert payload["portfolio_effect"]
    assert payload["recommended_action"]


def test_near_term_liquidity_conflict_requires_review() -> None:
    liquidity_goal = InvestorGoal(
        identifier="goal:home:1",
        goal_key="home",
        investor_identifier="investor:1",
        version="investor-goal.v1",
        name="Home purchase",
        goal_type=GoalType.PURCHASE,
        priority=GoalPriority.ESSENTIAL,
        effective_at=NOW,
        target_date=date(2028, 7, 25),
        target_amount=200_000,
        funded_amount=0,
        portfolio_codes=("GROWTH",),
        liquidity_required=True,
    )
    brief = build_personal_cio_brief(
        "investor:1",
        daily_snapshot=_snapshot(),
        profile=_profile(),
        goals=(liquidity_goal,),
        portfolios=(
            {
                "code": "GROWTH",
                "risk": "growth",
                "nav": 500_000,
                "cash": 10_000,
            },
        ),
        generated_at=NOW,
    )

    assert brief.action_status in {
        ActionStatus.REVIEW,
        ActionStatus.CONSIDER_CHANGE,
    }
    assert brief.portfolio_alignment.conflicts
