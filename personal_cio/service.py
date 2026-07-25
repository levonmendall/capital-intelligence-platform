"""Objective-aware portfolio alignment and canonical four-question brief."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from personal_cio.models import (
    ActionStatus,
    GoalPriority,
    InvestmentPolicyProfile,
    InvestorGoal,
    PersonalCIOBrief,
    PortfolioAlignment,
    RiskCapacity,
)


_RISK_RANK = {
    "conservative": 1,
    "low": 1,
    "moderate": 2,
    "balanced": 2,
    "growth": 3,
    "high": 3,
    "aggressive": 4,
}


def _portfolio_summary(
    portfolios: Iterable[dict[str, Any]],
) -> tuple[float, float, int]:
    nav = 0.0
    cash = 0.0
    highest_risk = 0
    for portfolio in portfolios:
        nav += float(portfolio.get("nav", 0.0) or 0.0)
        cash += float(portfolio.get("cash", 0.0) or 0.0)
        risk = str(portfolio.get("risk", "")).strip().casefold()
        highest_risk = max(highest_risk, _RISK_RANK.get(risk, 0))
    return nav, cash, highest_risk


def build_portfolio_alignment(
    investor_identifier: str,
    *,
    as_of: datetime,
    profile: InvestmentPolicyProfile | None,
    goals: tuple[InvestorGoal, ...],
    portfolios: tuple[dict[str, Any], ...],
) -> PortfolioAlignment:
    """Assess objective fit without claiming a probability of goal success."""

    if profile is None:
        return PortfolioAlignment(
            investor_identifier=investor_identifier,
            as_of=as_of,
            score=None,
            status="incomplete",
            policy_identifier=None,
            goal_identifiers=tuple(goal.identifier for goal in goals),
            supports=(),
            conflicts=("Investment objectives have not been recorded.",),
            explanation=(
                "Portfolio Alignment is unavailable until the investor records "
                "an Investment Policy Profile. No objective or risk preference "
                "was assumed."
            ),
        )

    score = 100
    supports: list[str] = []
    conflicts: list[str] = []
    nav, cash, highest_risk = _portfolio_summary(portfolios)

    if not goals:
        score -= 20
        conflicts.append(
            "No specific financial goals are linked to the portfolio."
        )
    else:
        supports.append(
            f"The portfolio is evaluated against {len(goals)} recorded goal(s)."
        )

    preference_rank = _RISK_RANK[profile.risk_preference.value]
    capacity_limit = {
        RiskCapacity.LOW: 1,
        RiskCapacity.MEDIUM: 3,
        RiskCapacity.HIGH: 4,
    }[profile.risk_capacity]
    if highest_risk and highest_risk > preference_rank:
        score -= min(20, (highest_risk - preference_rank) * 10)
        conflicts.append(
            "At least one mandate carries more risk than the recorded risk "
            "preference."
        )
    else:
        supports.append(
            "Mandate risk is within the recorded risk preference."
        )
    if highest_risk and highest_risk > capacity_limit:
        score -= 20
        conflicts.append(
            "Portfolio risk exceeds the investor's recorded financial risk "
            "capacity."
        )

    today = as_of.date()
    near_term_essential = [
        goal
        for goal in goals
        if goal.priority is GoalPriority.ESSENTIAL
        and goal.target_date is not None
        and 0 <= (goal.target_date - today).days <= 1095
    ]
    required_liquidity = sum(
        max(
            0.0,
            (goal.target_amount or 0.0) - (goal.funded_amount or 0.0),
        )
        for goal in near_term_essential
        if goal.liquidity_required or goal.target_amount is not None
    )
    if required_liquidity > 0 and cash < required_liquidity:
        shortfall = required_liquidity - cash
        ratio = 1.0 if nav <= 0 else min(1.0, shortfall / nav)
        score -= max(10, min(30, round(ratio * 100)))
        conflicts.append(
            "Available cash does not fully cover the recorded gap for a "
            "near-term essential goal."
        )
    elif required_liquidity > 0:
        supports.append(
            "Available cash covers the recorded near-term essential goal gap."
        )

    if (
        profile.maximum_tolerable_drawdown is not None
        and profile.maximum_tolerable_drawdown <= 0.15
        and highest_risk >= 3
    ):
        score -= 15
        conflicts.append(
            "Growth-oriented mandate risk may be inconsistent with the recorded "
            "drawdown tolerance."
        )

    score = max(0, min(100, score))
    status = (
        "aligned"
        if score >= 80
        else "review"
        if score >= 50
        else "misaligned"
    )
    explanation = (
        f"Portfolio Alignment is {score}/100 based on recorded objectives, "
        "risk capacity, risk preference, mandate posture, and near-term "
        "liquidity needs. It is not a probability of achieving any goal."
    )
    return PortfolioAlignment(
        investor_identifier=investor_identifier,
        as_of=as_of,
        score=score,
        status=status,
        policy_identifier=profile.identifier,
        goal_identifiers=tuple(goal.identifier for goal in goals),
        supports=tuple(dict.fromkeys(supports)),
        conflicts=tuple(dict.fromkeys(conflicts)),
        explanation=explanation,
    )


def _text(payload: dict[str, Any], *path: str) -> str | None:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return (
        value.strip()
        if isinstance(value, str) and value.strip()
        else None
    )


def _confidence(payload: dict[str, Any]) -> int | None:
    value: Any = payload.get("score", {}).get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value) * 100 if value <= 1 else float(value)
        return max(0, min(100, round(numeric)))
    components = payload.get("score", {}).get("components", {})
    if isinstance(components, dict):
        values = [
            float(item)
            for item in components.values()
            if isinstance(item, (int, float)) and not isinstance(item, bool)
        ]
        if values:
            numeric = sum(values) / len(values)
            numeric = numeric * 100 if numeric <= 1 else numeric
            return max(0, min(100, round(numeric)))
    return None


def build_personal_cio_brief(
    investor_identifier: str,
    *,
    daily_snapshot: dict[str, Any],
    profile: InvestmentPolicyProfile | None,
    goals: tuple[InvestorGoal, ...],
    portfolios: tuple[dict[str, Any], ...],
    generated_at: datetime | None = None,
) -> PersonalCIOBrief:
    """Answer the four product questions from one governed daily snapshot."""

    as_of = datetime.fromisoformat(str(daily_snapshot["as_of"]))
    generated = generated_at or datetime.now(timezone.utc)
    alignment = build_portfolio_alignment(
        investor_identifier,
        as_of=as_of,
        profile=profile,
        goals=goals,
        portfolios=portfolios,
    )
    what_changed = str(
        daily_snapshot.get("change_summary")
        or "No material change was identified."
    )
    why = (
        _text(daily_snapshot, "change", "explanation")
        or _text(daily_snapshot, "environment", "summary")
        or "The governed evidence did not support a stronger economic conclusion."
    )
    market_effect = (
        _text(daily_snapshot, "decision_card", "portfolio_impact")
        or _text(daily_snapshot, "environment", "portfolio_impact")
        or _text(daily_snapshot, "score", "portfolio_impact")
        or "No material portfolio effect was identified."
    )
    if alignment.score is None:
        portfolio_effect = (
            market_effect
            + " Objective-aware impact is incomplete because investor goals "
            "and policy are missing."
        )
    elif alignment.conflicts:
        portfolio_effect = market_effect + " " + alignment.conflicts[0]
    else:
        portfolio_effect = (
            market_effect
            + " The current posture remains consistent with recorded objectives."
        )

    should_alert = bool(daily_snapshot.get("should_alert"))
    data_status = str(daily_snapshot.get("status", "unavailable"))
    if data_status in {"unavailable", "stale"}:
        action = ActionStatus.MONITOR
        recommended = (
            "Do not make a portfolio change from this brief until the evidence "
            "is refreshed."
        )
    elif alignment.score is None:
        action = ActionStatus.MONITOR
        recommended = (
            "Record investor objectives before relying on personalized "
            "portfolio guidance."
        )
    elif alignment.score < 50:
        action = (
            ActionStatus.URGENT_REVIEW
            if should_alert
            else ActionStatus.REVIEW
        )
        recommended = (
            "Review the portfolio against the recorded investment policy before "
            "adding risk."
        )
    elif should_alert and alignment.score < 80:
        action = ActionStatus.CONSIDER_CHANGE
        recommended = (
            "Consider a policy-consistent adjustment after reviewing the cited "
            "evidence and trade-offs."
        )
    elif should_alert:
        action = ActionStatus.REVIEW
        recommended = (
            "Review the affected exposures; no change should be made unless the "
            "policy fit remains sound."
        )
    elif alignment.score < 80:
        action = ActionStatus.REVIEW
        recommended = (
            "No immediate market action is required, but the portfolio-policy "
            "mismatch deserves review."
        )
    else:
        action = ActionStatus.NO_ACTION
        recommended = (
            "No action is necessary. The current portfolio remains aligned with "
            "recorded objectives."
        )

    conditions = list(alignment.conflicts)
    environment_conditions = daily_snapshot.get("environment", {}).get(
        "review_conditions",
        [],
    )
    if isinstance(environment_conditions, list):
        conditions.extend(
            str(item)
            for item in environment_conditions
            if str(item).strip()
        )
    if not conditions:
        conditions.append(
            "Reassess if the governed material-change policy identifies a new "
            "portfolio-relevant shift."
        )
    sources = daily_snapshot.get("sources", {})
    evidence = (
        tuple(
            str(value)
            for value in sources.values()
            if str(value).strip()
        )
        if isinstance(sources, dict)
        else ()
    )
    snapshot_identifier = str(daily_snapshot["identifier"])
    return PersonalCIOBrief(
        identifier=(
            f"personal-cio-brief:{investor_identifier}:{as_of.isoformat()}"
        ),
        investor_identifier=investor_identifier,
        as_of=as_of,
        generated_at=generated,
        snapshot_identifier=snapshot_identifier,
        policy_identifier=(
            None if profile is None else profile.identifier
        ),
        what_changed=what_changed,
        why_it_matters=why,
        portfolio_effect=portfolio_effect,
        action_status=action,
        recommended_action=recommended,
        review_conditions=tuple(dict.fromkeys(conditions)),
        evidence_identifiers=evidence,
        confidence=_confidence(daily_snapshot),
        data_status=data_status,
        portfolio_alignment=alignment,
    )
