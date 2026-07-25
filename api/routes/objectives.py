"""Authenticated investor objectives and Personal CIO brief routes."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from api.config import ApiSettings
from api.dependencies import get_resources, get_settings, require_principal
from api.repositories import ApiResources
from personal_cio import (
    GoalPriority,
    GoalType,
    InvestmentPolicyProfile,
    InvestorGoal,
    RiskCapacity,
    RiskPreference,
    SQLiteInvestmentPolicyStore,
    brief_to_dict,
    build_personal_cio_brief,
    goal_to_dict,
    policy_to_dict,
)
from security import AuthenticatedPrincipal


router = APIRouter(prefix="/v1", tags=["investor objectives"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestmentPolicyRequest(StrictModel):
    primary_objective: str = Field(min_length=1, max_length=200)
    time_horizon_years: int = Field(ge=1, le=100)
    risk_capacity: str
    risk_preference: str
    required_return: float | None = Field(default=None, ge=0, le=1)
    maximum_tolerable_drawdown: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    minimum_liquidity_months: int = Field(default=0, ge=0, le=120)
    income_requirement: float | None = Field(default=None, ge=0)
    tax_sensitivity: str = "medium"
    rebalance_tolerance: str = "moderate"


class InvestorGoalRequest(StrictModel):
    goal_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    goal_type: str
    priority: str
    target_date: date | None = None
    target_amount: float | None = Field(default=None, ge=0)
    funded_amount: float | None = Field(default=None, ge=0)
    portfolio_codes: list[str] = Field(default_factory=list)
    liquidity_required: bool = False


def _authorize(
    principal: AuthenticatedPrincipal,
    investor_identifier: str,
    *,
    write: bool = False,
) -> None:
    if not principal.can_access_investor(investor_identifier, write=write):
        raise HTTPException(
            status_code=404,
            detail="investor objectives were not found",
        )


def _store(
    settings: ApiSettings,
    *,
    read_only: bool = False,
) -> SQLiteInvestmentPolicyStore:
    path = settings.investor_memory_database.with_name("investment_policy.db")
    if read_only and not path.exists():
        return SQLiteInvestmentPolicyStore(path)
    return SQLiteInvestmentPolicyStore(path, read_only=read_only)


def _authorized_portfolios(
    principal: AuthenticatedPrincipal,
    resources: ApiResources,
) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    for portfolio in resources.portfolios.list():
        code = str(portfolio["code"])
        if not principal.can_access_mandate(code):
            continue
        detail = resources.portfolios.get(code)
        items.append(detail or portfolio)
    return tuple(items)


@router.get("/investment-policy/{investor_identifier}")
def latest_policy(
    investor_identifier: str,
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier)
    path = settings.investor_memory_database.with_name("investment_policy.db")
    if not path.exists():
        return {"profile": None, "context_complete": False}
    profile = SQLiteInvestmentPolicyStore(
        path,
        read_only=True,
    ).latest_profile(investor_identifier)
    return {
        "profile": None if profile is None else policy_to_dict(profile),
        "context_complete": profile is not None,
    }


@router.get("/investment-policy/{investor_identifier}/history")
def policy_history(
    investor_identifier: str,
    limit: int = Query(default=50, ge=1, le=200),
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier)
    path = settings.investor_memory_database.with_name("investment_policy.db")
    if not path.exists():
        return {"items": [], "total": 0}
    items = SQLiteInvestmentPolicyStore(
        path,
        read_only=True,
    ).profile_history(investor_identifier, limit=limit)
    return {
        "items": [policy_to_dict(item) for item in items],
        "total": len(items),
    }


@router.post("/investment-policy/{investor_identifier}")
def record_policy(
    investor_identifier: str,
    request: InvestmentPolicyRequest,
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier, write=True)
    store = _store(settings)
    previous = store.latest_profile(investor_identifier)
    now = datetime.now(timezone.utc)
    try:
        profile = InvestmentPolicyProfile(
            identifier=f"investment-policy:{investor_identifier}:{uuid4()}",
            investor_identifier=investor_identifier,
            version="investment-policy-profile.v1",
            effective_at=now,
            primary_objective=request.primary_objective,
            time_horizon_years=request.time_horizon_years,
            risk_capacity=RiskCapacity(request.risk_capacity),
            risk_preference=RiskPreference(request.risk_preference),
            required_return=request.required_return,
            maximum_tolerable_drawdown=request.maximum_tolerable_drawdown,
            minimum_liquidity_months=request.minimum_liquidity_months,
            income_requirement=request.income_requirement,
            tax_sensitivity=request.tax_sensitivity,
            rebalance_tolerance=request.rebalance_tolerance,
            supersedes_identifier=(
                None if previous is None else previous.identifier
            ),
        )
        store.append_profile(profile)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return policy_to_dict(profile)


@router.get("/goals/{investor_identifier}")
def goals(
    investor_identifier: str,
    include_history: bool = False,
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier)
    path = settings.investor_memory_database.with_name("investment_policy.db")
    if not path.exists():
        return {"items": [], "total": 0}
    items = SQLiteInvestmentPolicyStore(path, read_only=True).goals(
        investor_identifier,
        history=include_history,
    )
    return {
        "items": [goal_to_dict(item) for item in items],
        "total": len(items),
    }


@router.post("/goals/{investor_identifier}")
def record_goal(
    investor_identifier: str,
    request: InvestorGoalRequest,
    settings: ApiSettings = Depends(get_settings),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier, write=True)
    store = _store(settings)
    previous = next(
        (
            item
            for item in store.goals(investor_identifier)
            if item.goal_key == request.goal_key
        ),
        None,
    )
    now = datetime.now(timezone.utc)
    try:
        goal = InvestorGoal(
            identifier=(
                f"investor-goal:{investor_identifier}:"
                f"{request.goal_key}:{uuid4()}"
            ),
            goal_key=request.goal_key,
            investor_identifier=investor_identifier,
            version="investor-goal.v1",
            name=request.name,
            goal_type=GoalType(request.goal_type),
            priority=GoalPriority(request.priority),
            effective_at=now,
            target_date=request.target_date,
            target_amount=request.target_amount,
            funded_amount=request.funded_amount,
            portfolio_codes=tuple(request.portfolio_codes),
            liquidity_required=request.liquidity_required,
            supersedes_identifier=(
                None if previous is None else previous.identifier
            ),
        )
        store.append_goal(goal)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return goal_to_dict(goal)


@router.get("/personal-cio/{investor_identifier}/latest")
def latest_personal_cio_brief(
    investor_identifier: str,
    settings: ApiSettings = Depends(get_settings),
    resources: ApiResources = Depends(get_resources),
    principal: AuthenticatedPrincipal = Depends(require_principal),
) -> dict[str, object]:
    _authorize(principal, investor_identifier)
    snapshot = resources.snapshots.latest_payload()
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="daily intelligence is not available",
        )
    path = settings.investor_memory_database.with_name("investment_policy.db")
    profile = None
    investor_goals = ()
    if path.exists():
        store = SQLiteInvestmentPolicyStore(path, read_only=True)
        profile = store.latest_profile(investor_identifier)
        investor_goals = store.goals(investor_identifier)
    brief = build_personal_cio_brief(
        investor_identifier,
        daily_snapshot=snapshot,
        profile=profile,
        goals=investor_goals,
        portfolios=_authorized_portfolios(principal, resources),
    )
    return brief_to_dict(brief)
