"""Independent specialist-analysis packet for CIO synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median

from cio.models import (
    CandidateDecisionRecord,
    MaterialDissent,
    SpecialistPosition,
    SpecialistRole,
)


_REQUIRED_ROLES = frozenset(SpecialistRole)


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _text_tuple(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name) for item in value
    )
    if len(normalized) < minimum:
        raise ValueError(
            f"{field_name} must contain at least {minimum} item(s)"
        )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class SpecialistAnalysis:
    """One specialist's independent first-pass assessment of a candidate."""

    candidate_identifier: str
    role: SpecialistRole
    completed_at: datetime
    independent_first_pass: bool
    position: SpecialistPosition
    conclusion: str
    expected_return_impact: float
    confidence: float
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    critical_assumptions: tuple[str, ...]
    risks: tuple[str, ...]
    limitations: tuple[str, ...]
    change_conditions: tuple[str, ...]
    veto_reasons: tuple[str, ...] = ()
    implementation_blocks: tuple[str, ...] = ()
    recommended_position_weight: float | None = None
    funding_source: str | None = None
    evidence_origin_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_identifier",
            _required_text(
                self.candidate_identifier,
                field_name="candidate_identifier",
            ),
        )
        if not isinstance(self.role, SpecialistRole):
            raise TypeError("role must be a SpecialistRole")
        if not isinstance(self.completed_at, datetime):
            raise TypeError("completed_at must be a datetime")
        if (
            self.completed_at.tzinfo is None
            or self.completed_at.utcoffset() is None
        ):
            raise ValueError("completed_at must be timezone-aware")
        if not isinstance(self.independent_first_pass, bool):
            raise TypeError("independent_first_pass must be a bool")
        if not self.independent_first_pass:
            raise ValueError(
                "specialist analysis must be completed independently before review"
            )
        if not isinstance(self.position, SpecialistPosition):
            raise TypeError("position must be a SpecialistPosition")
        object.__setattr__(
            self,
            "conclusion",
            _required_text(self.conclusion, field_name="conclusion"),
        )
        for field_name in ("expected_return_impact", "confidence"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if field_name == "confidence" and not 0.0 <= normalized <= 1.0:
                raise ValueError("confidence must be between 0.0 and 1.0")
            object.__setattr__(self, field_name, round(normalized, 8))
        for field_name, minimum in (
            ("supporting_evidence", 1),
            ("contradictory_evidence", 0),
            ("critical_assumptions", 1),
            ("risks", 1),
            ("limitations", 0),
            ("change_conditions", 1),
            ("veto_reasons", 0),
            ("implementation_blocks", 0),
            ("evidence_origin_identifiers", 0),
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=minimum,
                ),
            )
        if self.veto_reasons and self.role is not SpecialistRole.EVIDENCE_GOVERNANCE:
            raise ValueError(
                "only the Evidence & Governance Officer may issue evidence vetoes"
            )
        if (
            self.implementation_blocks
            and self.role is not SpecialistRole.PORTFOLIO_RISK
        ):
            raise ValueError(
                "only the Portfolio & Risk Manager may issue implementation blocks"
            )
        if self.recommended_position_weight is not None:
            if self.role is not SpecialistRole.PORTFOLIO_RISK:
                raise ValueError(
                    "only the Portfolio & Risk Manager may propose position size"
                )
            weight = float(self.recommended_position_weight)
            if not 0.0 <= weight <= 1.0:
                raise ValueError(
                    "recommended_position_weight must be between 0.0 and 1.0"
                )
            object.__setattr__(
                self,
                "recommended_position_weight",
                round(weight, 8),
            )
        if self.funding_source is not None:
            if self.role is not SpecialistRole.PORTFOLIO_RISK:
                raise ValueError(
                    "only the Portfolio & Risk Manager may propose funding"
                )
            object.__setattr__(
                self,
                "funding_source",
                _required_text(self.funding_source, field_name="funding_source"),
            )


@dataclass(frozen=True, slots=True)
class IndependentSpecialistPacket:
    """Exactly six independent specialist analyses for one candidate."""

    candidate_identifier: str
    analyses: tuple[SpecialistAnalysis, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_identifier",
            _required_text(
                self.candidate_identifier,
                field_name="candidate_identifier",
            ),
        )
        if not isinstance(self.analyses, tuple) or not all(
            isinstance(item, SpecialistAnalysis) for item in self.analyses
        ):
            raise TypeError(
                "analyses must be a tuple of SpecialistAnalysis values"
            )
        roles = tuple(item.role for item in self.analyses)
        if len(roles) != len(set(roles)):
            raise ValueError("specialist packet cannot contain duplicate roles")
        missing = _REQUIRED_ROLES.difference(roles)
        extra = set(roles).difference(_REQUIRED_ROLES)
        if missing or extra:
            missing_text = ", ".join(sorted(item.value for item in missing))
            extra_text = ", ".join(sorted(item.value for item in extra))
            raise ValueError(
                "specialist packet must contain exactly the six governing roles; "
                f"missing={missing_text or '-'}; extra={extra_text or '-'}"
            )
        if any(
            item.candidate_identifier != self.candidate_identifier
            for item in self.analyses
        ):
            raise ValueError(
                "all specialist analyses must reference the packet candidate"
            )

    def for_role(self, role: SpecialistRole) -> SpecialistAnalysis:
        if not isinstance(role, SpecialistRole):
            raise TypeError("role must be a SpecialistRole")
        return next(item for item in self.analyses if item.role is role)

    @property
    def evidence_vetoes(self) -> tuple[str, ...]:
        return self.for_role(SpecialistRole.EVIDENCE_GOVERNANCE).veto_reasons

    @property
    def implementation_blocks(self) -> tuple[str, ...]:
        return self.for_role(SpecialistRole.PORTFOLIO_RISK).implementation_blocks

    @property
    def portfolio_recommendation(self) -> SpecialistAnalysis:
        return self.for_role(SpecialistRole.PORTFOLIO_RISK)

    @property
    def median_confidence(self) -> float:
        return round(median(item.confidence for item in self.analyses), 6)

    @property
    def support_ratio(self) -> float:
        supportive = sum(
            item.position is SpecialistPosition.SUPPORTIVE
            for item in self.analyses
        )
        return round(supportive / len(self.analyses), 6)

    @property
    def opposing(self) -> tuple[SpecialistAnalysis, ...]:
        return tuple(
            item
            for item in self.analyses
            if item.position in {
                SpecialistPosition.OPPOSED,
                SpecialistPosition.ABSTAIN,
            }
        )

    def strongest_dissent(self) -> MaterialDissent | None:
        opposing = self.opposing
        if not opposing:
            return None
        strongest = max(
            opposing,
            key=lambda item: (
                item.confidence,
                abs(item.expected_return_impact),
            ),
        )
        reason_parts = list(strongest.risks)
        reason_parts.extend(strongest.limitations)
        reason = "; ".join(reason_parts) or strongest.conclusion
        return MaterialDissent(
            opposing_role=strongest.role,
            opposing_conclusion=strongest.conclusion,
            disagreement_reason=reason,
            resolving_evidence=strongest.change_conditions,
        )

    def validate_against(self, candidate: CandidateDecisionRecord) -> None:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be a CandidateDecisionRecord")
        if candidate.identifier != self.candidate_identifier:
            raise ValueError("specialist packet does not match the candidate")
        if any(item.completed_at < candidate.as_of for item in self.analyses):
            raise ValueError(
                "specialist analyses cannot predate the candidate evidence boundary"
            )


__all__ = [
    "IndependentSpecialistPacket",
    "SpecialistAnalysis",
]
