"""Point-in-time replay of a decision chain and its later outcome."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from committee.regime_governance import RegimeCommitteeDecision
from evaluation import DecisionQualityReview
from intelligence.regime_pipeline import InstitutionalRegimeRun
from monitoring import MarketChangeAssessment
from portfolio import PortfolioFitDecision
from reporting.capital_intelligence import (
    committee_vote_summary,
    environment_label_for_regime,
)
from reporting.decision_card import build_cio_decision_card


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class DecisionReplayEvent:
    """External event that caused the user to revisit the decision chain."""

    title: str
    occurred_at: datetime
    summary: str
    evidence_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("title", "summary"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.occurred_at, field_name="occurred_at")
        if not isinstance(self.evidence_identifiers, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.evidence_identifiers
        ):
            raise TypeError("evidence_identifiers must contain non-empty strings")


@dataclass(frozen=True, slots=True)
class DecisionReplayPerformance:
    """Outcome measured after the original decision was made."""

    measured_at: datetime
    benchmark: str
    decision_return: float
    benchmark_return: float
    note: str | None = None

    def __post_init__(self) -> None:
        _aware(self.measured_at, field_name="measured_at")
        object.__setattr__(
            self,
            "benchmark",
            _required_text(self.benchmark, field_name="benchmark"),
        )
        for field_name in ("decision_return", "benchmark_return"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or normalized < -1.0:
                raise ValueError(f"{field_name} must be finite and at least -1.0")
            object.__setattr__(self, field_name, round(normalized, 6))
        if self.note is not None:
            object.__setattr__(
                self,
                "note",
                _required_text(self.note, field_name="note"),
            )

    @property
    def relative_return(self) -> float:
        return round(self.decision_return - self.benchmark_return, 6)

    @property
    def summary(self) -> str:
        verb = "outperformed" if self.relative_return >= 0 else "underperformed"
        return (
            f"The decision {verb} {self.benchmark} by "
            f"{abs(self.relative_return):.1%}."
        )


@dataclass(frozen=True, slots=True)
class DecisionReplayStep:
    """One ordered item in the replay timeline."""

    stage: str
    occurred_at: datetime
    headline: str
    detail: str

    def __post_init__(self) -> None:
        for field_name in ("stage", "headline", "detail"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.occurred_at, field_name="occurred_at")


@dataclass(frozen=True, slots=True)
class DecisionReplay:
    """Immutable replay that separates original reasoning from hindsight."""

    identifier: str
    decision_identifier: str
    created_at: datetime
    steps: tuple[DecisionReplayStep, ...]
    point_in_time_sources: tuple[str, ...]
    relative_return: float | None
    lesson: str | None

    def __post_init__(self) -> None:
        for field_name in ("identifier", "decision_identifier"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.created_at, field_name="created_at")
        if not isinstance(self.steps, tuple) or not self.steps or not all(
            isinstance(step, DecisionReplayStep) for step in self.steps
        ):
            raise TypeError("steps must contain DecisionReplayStep values")
        if not isinstance(self.point_in_time_sources, tuple) or not all(
            isinstance(item, str) and item.strip()
            for item in self.point_in_time_sources
        ):
            raise TypeError("point_in_time_sources must contain non-empty strings")
        if self.relative_return is not None:
            if isinstance(self.relative_return, bool) or not isinstance(
                self.relative_return, (int, float)
            ):
                raise TypeError("relative_return must be numeric or None")
            if not isfinite(float(self.relative_return)):
                raise ValueError("relative_return must be finite")
            object.__setattr__(
                self,
                "relative_return",
                round(float(self.relative_return), 6),
            )
        if self.lesson is not None:
            object.__setattr__(
                self,
                "lesson",
                _required_text(self.lesson, field_name="lesson"),
            )


def build_decision_replay(
    event: DecisionReplayEvent,
    previous_run: InstitutionalRegimeRun,
    current_run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    *,
    change: MarketChangeAssessment | None = None,
    portfolio_fit: PortfolioFitDecision | None = None,
    performance: DecisionReplayPerformance | None = None,
    review: DecisionQualityReview | None = None,
) -> DecisionReplay:
    """Assemble the stored reasoning chain without rewriting history."""

    if not isinstance(event, DecisionReplayEvent):
        raise TypeError("event must be a DecisionReplayEvent")
    if not isinstance(previous_run, InstitutionalRegimeRun):
        raise TypeError("previous_run must be an InstitutionalRegimeRun")
    if not isinstance(current_run, InstitutionalRegimeRun):
        raise TypeError("current_run must be an InstitutionalRegimeRun")
    if previous_run.as_of > current_run.as_of:
        raise ValueError("previous_run must not be after current_run")
    if event.occurred_at > current_run.as_of:
        raise ValueError("event cannot occur after the current run")
    if change is not None and (
        change.previous_as_of != previous_run.as_of
        or change.current_as_of != current_run.as_of
    ):
        raise ValueError("change must connect the supplied runs")
    if performance is not None and performance.measured_at < decision.decided_at:
        raise ValueError("performance must be measured after the decision")
    if review is not None:
        if review.decision_identifier != decision.decision_identifier:
            raise ValueError("review must reference the decision")
        if review.reviewed_at < decision.decided_at:
            raise ValueError("review must occur after the decision")

    card = build_cio_decision_card(
        current_run,
        decision,
        change=change,
        portfolio_fit=portfolio_fit,
    )
    previous_environment = environment_label_for_regime(
        previous_run.assessment.result.regime
    )
    current_environment = environment_label_for_regime(
        current_run.assessment.result.regime
    )
    environment_detail = (
        change.explanation if change is not None else card.why_now
    )
    portfolio_detail = card.decision
    if portfolio_fit is not None and portfolio_fit.permitted_weight_delta is not None:
        portfolio_detail = (
            "Permitted portfolio change: "
            f"{portfolio_fit.permitted_weight_delta:+.1%}. "
            f"{card.portfolio_explanation}"
        )

    steps: list[DecisionReplayStep] = [
        DecisionReplayStep(
            stage="event",
            occurred_at=event.occurred_at,
            headline=event.title,
            detail=event.summary,
        ),
        DecisionReplayStep(
            stage="environment",
            occurred_at=current_run.as_of,
            headline=f"{previous_environment} → {current_environment}",
            detail=environment_detail,
        ),
        DecisionReplayStep(
            stage="committee",
            occurred_at=decision.decided_at,
            headline=committee_vote_summary(decision),
            detail=decision.rationale,
        ),
        DecisionReplayStep(
            stage="portfolio",
            occurred_at=decision.decided_at,
            headline=card.portfolio_explanation,
            detail=portfolio_detail,
        ),
    ]
    if performance is not None:
        steps.append(
            DecisionReplayStep(
                stage="outcome",
                occurred_at=performance.measured_at,
                headline=performance.summary,
                detail=performance.note or "Measured after the original decision.",
            )
        )

    lesson = None
    if review is not None and review.lessons:
        lesson = review.lessons[0]
        steps.append(
            DecisionReplayStep(
                stage="lesson",
                occurred_at=review.reviewed_at,
                headline="Lesson",
                detail=lesson,
            )
        )

    return DecisionReplay(
        identifier=f"decision-replay:{decision.decision_identifier}",
        decision_identifier=decision.decision_identifier,
        created_at=(
            review.reviewed_at
            if review is not None
            else performance.measured_at
            if performance is not None
            else decision.decided_at
        ),
        steps=tuple(steps),
        point_in_time_sources=(
            decision.regime_run_identifier,
            decision.decision_identifier,
            *event.evidence_identifiers,
        ),
        relative_return=(performance.relative_return if performance else None),
        lesson=lesson,
    )


def decision_replay_to_dict(replay: DecisionReplay) -> dict[str, Any]:
    """Return the stable replay schema for client drill-down."""

    if not isinstance(replay, DecisionReplay):
        raise TypeError("replay must be a DecisionReplay")
    return {
        "schema_version": "decision-replay.v1",
        "identifier": replay.identifier,
        "decision_identifier": replay.decision_identifier,
        "created_at": replay.created_at.isoformat(),
        "timeline": [
            {
                "stage": step.stage,
                "occurred_at": step.occurred_at.isoformat(),
                "headline": step.headline,
                "detail": step.detail,
            }
            for step in replay.steps
        ],
        "point_in_time_sources": list(replay.point_in_time_sources),
        "relative_return": replay.relative_return,
        "lesson": replay.lesson,
        "hindsight_is_separate": True,
    }


def render_decision_replay_json(replay: DecisionReplay) -> str:
    return json.dumps(decision_replay_to_dict(replay), indent=2, sort_keys=True)


def render_decision_replay_markdown(replay: DecisionReplay) -> str:
    """Render the full reasoning chain as a readable timeline."""

    lines = ["# Decision Replay", ""]
    for step in replay.steps:
        lines.extend(
            (
                f"## {step.occurred_at.date().isoformat()} · {step.stage.title()}",
                f"**{step.headline}**",
                step.detail,
                "",
            )
        )
    lines.extend(
        (
            "---",
            "The original reasoning is point-in-time. Performance and lessons are later observations.",
        )
    )
    return "\n".join(lines)


__all__ = [
    "DecisionReplay",
    "DecisionReplayEvent",
    "DecisionReplayPerformance",
    "DecisionReplayStep",
    "build_decision_replay",
    "decision_replay_to_dict",
    "render_decision_replay_json",
    "render_decision_replay_markdown",
]
