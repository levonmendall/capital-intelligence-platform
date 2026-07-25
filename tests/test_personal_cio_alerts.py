"""Contract tests for objective-aware alert wording and brief history."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone

from delivery import (
    AlertChannel,
    AlertSnapshot,
    AlertTopic,
    DeliveryPreference,
)
from personal_cio import (
    GoalPriority,
    GoalType,
    InvestmentPolicyProfile,
    InvestorGoal,
    PersonalCIOAlertPlanner,
    RiskCapacity,
    RiskPreference,
    SQLiteInvestmentPolicyStore,
    SQLitePersonalCIOBriefStore,
)
from security import MandatePermission, SQLiteIdentityStore, UserRole
from tests.test_api import _create_portfolio_database


NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
PASSWORD = "Investor-Password-42!"


def _daily_database(path) -> None:
    payload = {
        "identifier": "daily:1",
        "as_of": NOW.isoformat(),
        "status": "current",
        "score": {
            "confidence": 0.82,
            "portfolio_impact": "Maintain diversified risk.",
        },
        "environment": {
            "summary": "Liquidity remains supportive.",
            "portfolio_impact": "Maintain diversified risk.",
            "review_conditions": [
                "Review if credit conditions deteriorate materially."
            ],
        },
        "decision_card": {
            "portfolio_impact": "Maintain diversified risk."
        },
        "change": {
            "explanation": "Credit conditions weakened modestly."
        },
        "change_summary": "Credit conditions weakened modestly.",
        "should_alert": True,
        "decision_replays": ["replay:decision:1"],
        "sources": {
            "regime_run": "run:1",
            "decision": "decision:1",
        },
    }
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE daily_intelligence_snapshots (
                identifier TEXT PRIMARY KEY,
                as_of TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO daily_intelligence_snapshots VALUES (?, ?, ?)",
            (payload["identifier"], payload["as_of"], json.dumps(payload)),
        )


def _planner(tmp_path):
    daily = tmp_path / "daily.db"
    portfolio = tmp_path / "portfolio.db"
    identity = tmp_path / "identity.db"
    policy = tmp_path / "investment_policy.db"
    _daily_database(daily)
    _create_portfolio_database(portfolio)
    with sqlite3.connect(portfolio) as connection:
        connection.execute(
            "UPDATE mandates SET risk = 'moderate', cash = 100000, nav = 500000 "
            "WHERE code = 'GROWTH'"
        )
    identities = SQLiteIdentityStore(identity)
    account = identities.create_user(
        email="investor@example.com",
        display_name="Investor",
        password=PASSWORD,
        investor_identifier="investor:1",
        roles=(UserRole.INVESTOR,),
    )
    identities.assign_mandate(
        account.user_id,
        "GROWTH",
        MandatePermission.VIEW,
    )
    policies = SQLiteInvestmentPolicyStore(policy)
    policies.append_profile(
        InvestmentPolicyProfile(
            identifier="policy:1",
            investor_identifier="investor:1",
            version="investment-policy.v1",
            effective_at=NOW,
            primary_objective="long_term_growth",
            time_horizon_years=15,
            risk_capacity=RiskCapacity.HIGH,
            risk_preference=RiskPreference.MODERATE,
        )
    )
    policies.append_goal(
        InvestorGoal(
            identifier="goal:1",
            goal_key="retirement",
            investor_identifier="investor:1",
            version="investor-goal.v1",
            name="Retirement",
            goal_type=GoalType.RETIREMENT,
            priority=GoalPriority.ESSENTIAL,
            effective_at=NOW,
            target_date=date(2041, 7, 25),
            portfolio_codes=("GROWTH",),
        )
    )
    return (
        PersonalCIOAlertPlanner(
            identity_store=identities,
            snapshot_database=daily,
            portfolio_database=portfolio,
            policy_database=policy,
        ),
        account,
        policy,
    )


def _snapshot(*, category: str) -> AlertSnapshot:
    return AlertSnapshot(
        snapshot_identifier="daily:1",
        as_of=NOW,
        status="current",
        score=82,
        score_delta=4,
        environment="Constructive",
        risk="Moderate",
        committee="6–0 Favor Risk Assets",
        portfolio_impact="Maintain diversified risk.",
        change_summary="Credit conditions weakened modestly.",
        should_alert=True,
        alert_level="notify",
        change_categories=(category,),
    )


def test_no_action_suppresses_portfolio_review_and_records_history(tmp_path) -> None:
    planner, account, policy_path = _planner(tmp_path)
    preference = DeliveryPreference(
        user_id=account.user_id,
        channels=(AlertChannel.IN_APP,),
        topics=(AlertTopic.PORTFOLIO_REVIEW,),
    )

    result = planner.plan(_snapshot(category="signal"), preference)
    history = SQLitePersonalCIOBriefStore(
        policy_path,
        read_only=True,
    ).history("investor:1")

    assert result.message is None
    assert "no-action" in result.suppression_reason
    assert history[0]["action_status"] == "no_action"
    assert history[0]["decision_replays"] == ["replay:decision:1"]


def test_broader_market_alert_includes_personal_cio_guidance(tmp_path) -> None:
    planner, account, _ = _planner(tmp_path)
    preference = DeliveryPreference(
        user_id=account.user_id,
        channels=(AlertChannel.IN_APP,),
        topics=(AlertTopic.ENVIRONMENT_TRANSITION,),
    )

    result = planner.plan(_snapshot(category="regime"), preference)

    assert result.message is not None
    assert "Why it matters:" in result.message.body
    assert "How it affects your portfolio:" in result.message.body
    assert "Recommended response (No Action):" in result.message.body
