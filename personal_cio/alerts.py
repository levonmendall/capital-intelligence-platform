"""Objective-aware wrapper around the governed selective-alert planner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from api.repositories import DailySnapshotRepository, PortfolioRepository
from delivery import (
    AlertPlanningResult,
    AlertSnapshot,
    AlertTopic,
    DeliveryPreference,
    SelectiveAlertPlanner,
)
from personal_cio.brief_store import SQLitePersonalCIOBriefStore
from personal_cio.models import ActionStatus
from personal_cio.service import build_personal_cio_brief
from personal_cio.store import SQLiteInvestmentPolicyStore
from security import UserRole


class PersonalCIOAlertPlanner:
    """Add objective relevance without replacing material-change governance."""

    def __init__(
        self,
        *,
        identity_store: Any,
        snapshot_database: str | Path,
        portfolio_database: str | Path,
        policy_database: str | Path,
        base_planner: SelectiveAlertPlanner | None = None,
    ) -> None:
        self.identity_store = identity_store
        self.snapshots = DailySnapshotRepository(Path(snapshot_database))
        self.portfolios = PortfolioRepository(Path(portfolio_database))
        self.policy_store = SQLiteInvestmentPolicyStore(policy_database)
        self.brief_store = SQLitePersonalCIOBriefStore(policy_database)
        self.base_planner = base_planner or SelectiveAlertPlanner()

    def plan(
        self,
        snapshot: AlertSnapshot,
        preference: DeliveryPreference,
    ) -> AlertPlanningResult:
        result = self.base_planner.plan(snapshot, preference)
        account = self.identity_store.get_user(preference.user_id)
        daily_payload = self.snapshots.latest_payload()
        if daily_payload is None:
            return result
        investor_identifier = account.investor_identifier or account.user_id
        profile = self.policy_store.latest_profile(investor_identifier)
        goals = self.policy_store.goals(investor_identifier)
        allowed_codes = {
            grant.mandate_code for grant in account.mandate_grants
        }
        can_read_all = any(
            role in {UserRole.ADMINISTRATOR, UserRole.AUDITOR}
            for role in account.roles
        )
        authorized_portfolios: list[dict[str, object]] = []
        for item in self.portfolios.list():
            code = str(item["code"])
            if not can_read_all and code not in allowed_codes:
                continue
            authorized_portfolios.append(self.portfolios.get(code) or item)
        brief = build_personal_cio_brief(
            investor_identifier,
            daily_snapshot=daily_payload,
            profile=profile,
            goals=goals,
            portfolios=tuple(authorized_portfolios),
            generated_at=snapshot.as_of,
        )
        replay_values = daily_payload.get("decision_replays", [])
        replay_identifiers = (
            tuple(
                str(value)
                for value in replay_values
                if str(value).strip()
            )
            if isinstance(replay_values, list)
            else ()
        )
        self.brief_store.append(
            brief,
            replay_identifiers=replay_identifiers,
        )
        if result.message is None:
            return result
        selected = set(result.message.topics)
        if (
            brief.action_status is ActionStatus.NO_ACTION
            and selected
            and selected.issubset({AlertTopic.PORTFOLIO_REVIEW})
        ):
            return AlertPlanningResult(
                message=None,
                suppression_reason=(
                    "The market change was reviewed against this investor's "
                    "recorded objectives and resolved to a formal no-action "
                    "decision."
                ),
            )
        action_label = brief.action_status.value.replace("_", " ").title()
        personalized = (
            result.message.body
            + "\n\nWhy it matters: "
            + brief.why_it_matters
            + "\nHow it affects your portfolio: "
            + brief.portfolio_effect
            + f"\nRecommended response ({action_label}): "
            + brief.recommended_action
        )
        return AlertPlanningResult(
            message=replace(result.message, body=personalized),
            suppression_reason=None,
        )


__all__ = ["PersonalCIOAlertPlanner"]
