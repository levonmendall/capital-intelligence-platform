"""Product-level action policy for the canonical Personal CIO Brief."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from personal_cio.models import (
    ActionStatus,
    InvestmentPolicyProfile,
    InvestorGoal,
    PersonalCIOBrief,
)
from personal_cio.service import build_personal_cio_brief as _build_base_brief


def build_personal_cio_brief(
    investor_identifier: str,
    *,
    daily_snapshot: dict[str, Any],
    profile: InvestmentPolicyProfile | None,
    goals: tuple[InvestorGoal, ...],
    portfolios: tuple[dict[str, Any], ...],
    generated_at: datetime | None = None,
) -> PersonalCIOBrief:
    """Permit material market changes to produce a disciplined no-action result."""

    brief = _build_base_brief(
        investor_identifier,
        daily_snapshot=daily_snapshot,
        profile=profile,
        goals=goals,
        portfolios=portfolios,
        generated_at=generated_at,
    )
    if (
        bool(daily_snapshot.get("should_alert"))
        and brief.action_status is ActionStatus.REVIEW
        and brief.portfolio_alignment.score is not None
        and brief.portfolio_alignment.score >= 80
        and not brief.portfolio_alignment.conflicts
    ):
        return replace(
            brief,
            action_status=ActionStatus.NO_ACTION,
            recommended_action=(
                "No action is necessary. The material market change was reviewed "
                "against the recorded objectives, and the current portfolio "
                "remains appropriately positioned."
            ),
        )
    return brief


__all__ = ["build_personal_cio_brief"]
