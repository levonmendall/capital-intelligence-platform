"""Stable response schemas for the Capital Intelligence API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(StrictModel):
    status: str
    service: str
    version: str


class ReadinessComponentResponse(StrictModel):
    required: bool
    ready: bool
    detail: str


class ReadinessResponse(StrictModel):
    ready: bool
    components: dict[str, ReadinessComponentResponse]


class DailyHistoryItem(StrictModel):
    identifier: str
    as_of: str
    generated_at: str
    score: int = Field(ge=0, le=100)
    score_delta: int | None
    status: str
    environment: str
    risk: str
    committee: str
    portfolio_impact: str
    changed_materially: bool
    should_alert: bool
    decision_replays: list[str]


class DailyHistoryResponse(StrictModel):
    items: list[DailyHistoryItem]
    limit: int
    offset: int
    total: int


class EnvironmentResponse(StrictModel):
    snapshot_identifier: str
    as_of: str
    environment: dict[str, Any]
    sources: dict[str, str]


class DecisionResponse(StrictModel):
    decision_identifier: str
    snapshot_identifier: str
    as_of: str
    decision_card: dict[str, Any]
    sources: dict[str, str]


class ReplayReference(StrictModel):
    identifier: str
    available: bool
    created_at: str | None = None
    relative_return: float | None = None
    lesson: str | None = None


class ReplayListResponse(StrictModel):
    items: list[ReplayReference]
    total: int


class PortfolioListResponse(StrictModel):
    items: list[dict[str, Any]]
    total: int


class ConvictionDriverResponse(StrictModel):
    component: str
    change_points: int


class ConvictionHistoryItem(StrictModel):
    as_of: str
    conviction: int = Field(ge=0, le=100)
    capital_intelligence_score: int = Field(ge=0, le=100)


class ConvictionTrendResponse(StrictModel):
    schema_version: str
    as_of: str | None
    current: int | None = Field(default=None, ge=0, le=100)
    previous: int | None = Field(default=None, ge=0, le=100)
    change_points: int | None
    net_change_points: int | None
    direction: str
    streak: int
    capital_intelligence_score: int | None = Field(default=None, ge=0, le=100)
    score_change_points: int | None
    drivers: list[ConvictionDriverResponse]
    history: list[ConvictionHistoryItem]
    explanation: str
    policy_version: str


class InvestorPatternResponse(StrictModel):
    code: str
    label: str
    count: int
    recorded_as_mistake: bool | None = None


class InvestorActionTendencyResponse(StrictModel):
    action: str
    count: int


class InvestorMemoryResponse(StrictModel):
    schema_version: str
    investor_identifier: str
    as_of: str | None
    total_events: int
    preferred_risk_level: str | None
    recurring_patterns: list[InvestorPatternResponse]
    recurring_mistakes: list[InvestorPatternResponse]
    lessons: list[str]
    action_tendencies: list[InvestorActionTendencyResponse]
    memory_is_explicit: bool


class InvestorMemoryEventResponse(StrictModel):
    schema_version: str
    identifier: str
    investor_identifier: str
    recorded_at: str
    event_type: str
    summary: str
    source_decision_identifier: str | None
    action: str | None
    risk_level: str | None
    behavior_tags: list[str]
    lesson: str | None


class InvestorMemoryHistoryResponse(StrictModel):
    items: list[InvestorMemoryEventResponse]
    total: int


class ErrorResponse(StrictModel):
    detail: str


__all__ = [
    "ConvictionDriverResponse",
    "ConvictionHistoryItem",
    "ConvictionTrendResponse",
    "DailyHistoryItem",
    "DailyHistoryResponse",
    "DecisionResponse",
    "EnvironmentResponse",
    "ErrorResponse",
    "HealthResponse",
    "InvestorActionTendencyResponse",
    "InvestorMemoryEventResponse",
    "InvestorMemoryHistoryResponse",
    "InvestorMemoryResponse",
    "InvestorPatternResponse",
    "PortfolioListResponse",
    "ReadinessComponentResponse",
    "ReadinessResponse",
    "ReplayListResponse",
    "ReplayReference",
]
