"""Claim-level causal investment reasoning built on the governed event-market path.

This module does not create events, candidates, specialist votes, position sizes, or
portfolio actions. It converts an existing :class:`EventMarketAssessment` into a
reproducible package of facts and inferences with explicit evidence, uncertainty,
alternatives, and falsification conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any, Mapping

from intelligence.event_market_forward import (
    EventCausalState,
    EventMarketAssessment,
    TransmissionDirection,
)


class ClaimType(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"


class CausalDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    identifier: str
    observed_at: datetime
    published_at: datetime

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("identifier cannot be empty")
        for name in ("observed_at", "published_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.published_at > self.observed_at:
            raise ValueError("published_at cannot be after observed_at")


@dataclass(frozen=True, slots=True)
class CausalClaim:
    identifier: str
    claim_type: ClaimType
    statement: str
    direction: CausalDirection
    magnitude_range: tuple[float, float]
    confidence: float
    assumptions: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    affected_horizon: str
    invalidation_conditions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.statement.strip():
            raise ValueError("identifier and statement are required")
        if not isinstance(self.claim_type, ClaimType):
            raise TypeError("claim_type must be ClaimType")
        if not isinstance(self.direction, CausalDirection):
            raise TypeError("direction must be CausalDirection")
        low, high = self.magnitude_range
        if not all(isfinite(float(value)) for value in (low, high)) or low > high:
            raise ValueError("magnitude_range must be finite and ordered")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if not self.affected_horizon.strip():
            raise ValueError("affected_horizon is required")
        if not self.evidence_identifiers:
            raise ValueError("every claim requires source evidence identifiers")
        if self.claim_type is ClaimType.INFERENCE:
            if not self.assumptions:
                raise ValueError("inference claims require assumptions")
            if not self.invalidation_conditions:
                raise ValueError("inference claims require invalidation conditions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "claim_type": self.claim_type.value,
            "statement": self.statement,
            "direction": self.direction.value,
            "magnitude_range": list(self.magnitude_range),
            "confidence": round(float(self.confidence), 8),
            "assumptions": list(self.assumptions),
            "contradictory_evidence": list(self.contradictory_evidence),
            "alternative_explanations": list(self.alternative_explanations),
            "affected_horizon": self.affected_horizon,
            "invalidation_conditions": list(self.invalidation_conditions),
            "evidence_identifiers": list(self.evidence_identifiers),
        }


@dataclass(frozen=True, slots=True)
class CausalInvestmentPackage:
    identifier: str
    assessed_at: datetime
    state: str
    claims: tuple[CausalClaim, ...]
    source_evidence: tuple[SourceEvidence, ...]
    unresolved_questions: tuple[str, ...]
    policy_version: str
    schema_version: str = "causal-investment-package.v1"

    @property
    def resolved(self) -> bool:
        return self.state not in {"unresolved", "blocked"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "state": self.state,
            "claims": [claim.to_dict() for claim in self.claims],
            "source_evidence": [
                {
                    "identifier": item.identifier,
                    "observed_at": item.observed_at.isoformat(),
                    "published_at": item.published_at.isoformat(),
                }
                for item in self.source_evidence
            ],
            "unresolved_questions": list(self.unresolved_questions),
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
            "authorizes_portfolio_change": False,
            "authorizes_specialist_vote": False,
            "authorizes_position_size": False,
            "real_money_authorized": False,
        }


class GroundedCausalReasoningEngine:
    """Build claim-level evidence from the existing governed assessment."""

    version = "grounded-causal-reasoning.v1"

    @staticmethod
    def _direction(direction: TransmissionDirection) -> CausalDirection:
        return {
            TransmissionDirection.POSITIVE: CausalDirection.POSITIVE,
            TransmissionDirection.NEGATIVE: CausalDirection.NEGATIVE,
            TransmissionDirection.NEUTRAL: CausalDirection.NEUTRAL,
            TransmissionDirection.MIXED: CausalDirection.MIXED,
        }[direction]

    def build(
        self,
        assessment: EventMarketAssessment,
        *,
        source_timestamps: Mapping[str, tuple[datetime, datetime]],
        priced_in_assessment: str = "not independently established",
    ) -> CausalInvestmentPackage:
        if not isinstance(assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        missing = set(assessment.evidence_identifiers).difference(source_timestamps)
        if missing:
            raise ValueError(f"missing source timestamps for {sorted(missing)!r}")
        source_evidence = tuple(
            SourceEvidence(identifier, *source_timestamps[identifier])
            for identifier in assessment.evidence_identifiers
        )
        if assessment.state in {
            EventCausalState.ANALYSIS_BLOCKED,
            EventCausalState.UNRESOLVED_MAJOR_EVENT,
            EventCausalState.UNKNOWN,
        }:
            state = "blocked" if assessment.state is EventCausalState.ANALYSIS_BLOCKED else "unresolved"
            return CausalInvestmentPackage(
                identifier=f"causal-package:{assessment.identifier}",
                assessed_at=assessment.assessed_at,
                state=state,
                claims=(),
                source_evidence=source_evidence,
                unresolved_questions=assessment.unresolved_questions
                or ("Causal relationship unresolved.",),
                policy_version=f"{assessment.policy_version}+{self.version}",
            )

        assumptions = tuple(
            dict.fromkeys(
                step
                for driver in assessment.drivers
                for step in driver.causal_chain
            )
        ) or ("The governed event-market mapping remains valid.",)
        alternatives = tuple(
            dict.fromkeys(
                (*assessment.alternative_explanations, *(alt for d in assessment.drivers for alt in d.alternatives))
            )
        )
        claims: list[CausalClaim] = []
        for index, transmission in enumerate(assessment.transmissions, start=1):
            magnitude = abs(float(transmission.magnitude))
            low = max(0.0, magnitude * 0.75)
            high = min(1.0, magnitude * 1.25)
            claims.append(
                CausalClaim(
                    identifier=f"{assessment.identifier}:transmission:{index}",
                    claim_type=ClaimType.INFERENCE,
                    statement=(
                        f"The event may affect {transmission.target_identifier} through "
                        f"{transmission.mechanism} What appears priced in: {priced_in_assessment}."
                    ),
                    direction=self._direction(transmission.direction),
                    magnitude_range=(round(low, 8), round(high, 8)),
                    confidence=min(assessment.confidence, transmission.confidence),
                    assumptions=assumptions,
                    contradictory_evidence=assessment.contradictory_evidence,
                    alternative_explanations=alternatives,
                    affected_horizon=transmission.horizon,
                    invalidation_conditions=(
                        "The stated transmission mechanism fails to appear in point-in-time market or fundamental evidence.",
                        "A documented alternative explanation better accounts for the observed outcome.",
                    ),
                    evidence_identifiers=transmission.evidence_identifiers,
                )
            )
        return CausalInvestmentPackage(
            identifier=f"causal-package:{assessment.identifier}",
            assessed_at=assessment.assessed_at,
            state="mixed" if assessment.state is EventCausalState.MIXED else "mapped",
            claims=tuple(claims),
            source_evidence=source_evidence,
            unresolved_questions=assessment.unresolved_questions,
            policy_version=f"{assessment.policy_version}+{self.version}",
        )
