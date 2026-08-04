"""Decision-focused value-of-information research planning.

The planner ranks unresolved assumptions by their potential to change a governed
decision. It cannot bypass provider governance, delay risk exits, or authorize capital.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class ResearchStatus(str, Enum):
    PLANNED = "planned"
    BLOCKED_PROVIDER = "blocked_provider"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class UnresolvedAssumption:
    identifier: str
    question: str
    current_uncertainty: float
    decision_identifier: str
    potential_action_change: str
    decision_sensitivity: float
    resolution_probability: float
    required_source: str
    provider_approved: bool
    collection_cost: float
    deadline: datetime
    resolution_criteria: str

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.question.strip():
            raise ValueError("identifier and question are required")
        for name in ("current_uncertainty", "decision_sensitivity", "resolution_probability"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if float(self.collection_cost) < 0.0:
            raise ValueError("collection_cost cannot be negative")
        if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
            raise ValueError("deadline must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResearchQuestion:
    assumption_identifier: str
    question: str
    expected_information_value: float
    required_source: str
    collection_cost: float
    deadline: datetime
    resolution_criteria: str
    status: ResearchStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_identifier": self.assumption_identifier,
            "question": self.question,
            "expected_information_value": self.expected_information_value,
            "required_source": self.required_source,
            "collection_cost": self.collection_cost,
            "deadline": self.deadline.isoformat(),
            "resolution_criteria": self.resolution_criteria,
            "status": self.status.value,
            "authorizes_portfolio_change": False,
            "bypasses_provider_governance": False,
        }


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    decision_identifier: str
    created_at: datetime
    questions: tuple[ResearchQuestion, ...]
    urgent_risk_review_preserved: bool = True


class ValueOfInformationPlanner:
    version = "value-of-information.v1"

    def plan(
        self,
        assumptions: tuple[UnresolvedAssumption, ...],
        *,
        created_at: datetime,
    ) -> tuple[ResearchPlan, ...]:
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        grouped: dict[str, list[ResearchQuestion]] = {}
        seen: set[tuple[str, str]] = set()
        for item in assumptions:
            key = (item.decision_identifier, item.question.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            gross = (
                item.current_uncertainty
                * item.decision_sensitivity
                * item.resolution_probability
            )
            value = round(max(0.0, gross - item.collection_cost), 8)
            status = (
                ResearchStatus.BLOCKED_PROVIDER
                if not item.provider_approved
                else ResearchStatus.EXPIRED
                if item.deadline < created_at
                else ResearchStatus.PLANNED
            )
            grouped.setdefault(item.decision_identifier, []).append(
                ResearchQuestion(
                    assumption_identifier=item.identifier,
                    question=item.question,
                    expected_information_value=value,
                    required_source=item.required_source,
                    collection_cost=item.collection_cost,
                    deadline=item.deadline,
                    resolution_criteria=item.resolution_criteria,
                    status=status,
                )
            )
        return tuple(
            ResearchPlan(
                decision_identifier=decision,
                created_at=created_at,
                questions=tuple(
                    sorted(
                        questions,
                        key=lambda item: (
                            item.status is ResearchStatus.PLANNED,
                            item.expected_information_value,
                            item.assumption_identifier,
                        ),
                        reverse=True,
                    )
                ),
            )
            for decision, questions in sorted(grouped.items())
        )
