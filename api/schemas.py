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


class ErrorResponse(StrictModel):
    detail: str


__all__ = [
    "DailyHistoryItem",
    "DailyHistoryResponse",
    "DecisionResponse",
    "EnvironmentResponse",
    "ErrorResponse",
    "HealthResponse",
    "PortfolioListResponse",
    "ReadinessComponentResponse",
    "ReadinessResponse",
    "ReplayListResponse",
    "ReplayReference",
]
