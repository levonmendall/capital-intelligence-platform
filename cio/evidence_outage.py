"""Governed aging and escalation for operational evidence outages.

A temporary provider outage may preserve an existing holding, but it cannot preserve
an unobservable thesis indefinitely. This module distinguishes short operational
unavailability from thesis contradiction, integrity emergencies, and loss of
custody, settlement, or lifecycle observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from cio.models import CandidateAssetClass, CandidateDecisionRecord, PriorDecisionContext


class EvidenceOutageDisposition(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    HOLD_WITH_DECAY = "hold_with_decay"
    REDUCE = "reduce"
    EMERGENCY_REDUCE = "emergency_reduce"


@dataclass(frozen=True, slots=True)
class EvidenceOutagePolicy:
    version: str = "evidence-outage-aging.v1"
    diversified_maximum_days: float = 10.0
    standard_maximum_days: float = 7.0
    volatile_maximum_days: float = 2.0
    substitute_evidence_multiplier: float = 2.0
    minimum_confidence_ceiling: float = 0.25

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for field_name in (
            "diversified_maximum_days",
            "standard_maximum_days",
            "volatile_maximum_days",
            "substitute_evidence_multiplier",
        ):
            if float(getattr(self, field_name)) <= 0.0:
                raise ValueError(f"{field_name} must be positive")
        if not 0.0 <= self.minimum_confidence_ceiling <= 1.0:
            raise ValueError("minimum_confidence_ceiling must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class EvidenceOutageAssessment:
    disposition: EvidenceOutageDisposition
    policy_version: str
    outage_age_days: float
    maximum_tolerable_days: float
    confidence_ceiling: float
    reason: str

    @property
    def requires_reduction(self) -> bool:
        return self.disposition in {
            EvidenceOutageDisposition.REDUCE,
            EvidenceOutageDisposition.EMERGENCY_REDUCE,
        }


class EvidenceOutageAuthority:
    def __init__(self, policy: EvidenceOutagePolicy | None = None) -> None:
        self.policy = policy or EvidenceOutagePolicy()

    def assess(
        self,
        candidate: CandidateDecisionRecord,
        prior_context: PriorDecisionContext | None,
        *,
        operational_only_veto: bool,
    ) -> EvidenceOutageAssessment:
        if not operational_only_veto or candidate.current_portfolio_weight <= 0.0:
            return EvidenceOutageAssessment(
                disposition=EvidenceOutageDisposition.NOT_APPLICABLE,
                policy_version=self.policy.version,
                outage_age_days=0.0,
                maximum_tolerable_days=0.0,
                confidence_ceiling=1.0,
                reason="No operational-only holding outage requires aging.",
            )
        maximum = self._maximum_days(candidate.instrument.asset_class)
        if prior_context is None:
            last_complete = candidate.as_of
            substitute = False
            custody_observable = True
            lifecycle_observable = True
            outage_started = candidate.as_of
        else:
            last_complete = (
                prior_context.last_complete_evidence_at
                or prior_context.decided_at
            )
            outage_started = (
                prior_context.operational_outage_started_at
                or last_complete
            )
            substitute = prior_context.independent_substitute_evidence_available
            custody_observable = prior_context.custody_settlement_observable
            lifecycle_observable = prior_context.lifecycle_observable
        if last_complete > candidate.as_of or outage_started > candidate.as_of:
            raise ValueError("outage evidence timestamps cannot be from the future")
        if substitute:
            maximum *= self.policy.substitute_evidence_multiplier
        age_days = max(
            0.0,
            (candidate.as_of - max(last_complete, outage_started)).total_seconds()
            / 86400.0,
        )
        if not custody_observable or not lifecycle_observable:
            missing = []
            if not custody_observable:
                missing.append("custody or settlement")
            if not lifecycle_observable:
                missing.append("instrument lifecycle")
            return EvidenceOutageAssessment(
                disposition=EvidenceOutageDisposition.EMERGENCY_REDUCE,
                policy_version=self.policy.version,
                outage_age_days=round(age_days, 8),
                maximum_tolerable_days=round(maximum, 8),
                confidence_ceiling=self.policy.minimum_confidence_ceiling,
                reason=(
                    "Operational evidence is unavailable and "
                    + " and ".join(missing)
                    + " observability is lost; risk reduction cannot wait for provider repair."
                ),
            )
        if age_days > maximum:
            return EvidenceOutageAssessment(
                disposition=EvidenceOutageDisposition.REDUCE,
                policy_version=self.policy.version,
                outage_age_days=round(age_days, 8),
                maximum_tolerable_days=round(maximum, 8),
                confidence_ceiling=self.policy.minimum_confidence_ceiling,
                reason=(
                    f"The operational evidence outage has persisted {age_days:.1f} days, "
                    f"beyond the {maximum:.1f}-day limit for this exposure; the last "
                    "validated thesis can no longer support the full position."
                ),
            )
        fraction = 0.0 if maximum <= 0.0 else age_days / maximum
        ceiling = max(
            self.policy.minimum_confidence_ceiling,
            1.0 - 0.75 * fraction,
        )
        substitute_text = (
            " Independent substitute evidence extends the bounded review window."
            if substitute
            else ""
        )
        return EvidenceOutageAssessment(
            disposition=EvidenceOutageDisposition.HOLD_WITH_DECAY,
            policy_version=self.policy.version,
            outage_age_days=round(age_days, 8),
            maximum_tolerable_days=round(maximum, 8),
            confidence_ceiling=round(ceiling, 8),
            reason=(
                f"The operational evidence outage is {age_days:.1f} days old within a "
                f"{maximum:.1f}-day bounded hold window; confidence decays while new or "
                "increased exposure remains prohibited."
                + substitute_text
            ),
        )

    def _maximum_days(self, asset_class: CandidateAssetClass) -> float:
        if asset_class in {
            CandidateAssetClass.US_ETF,
            CandidateAssetClass.FIXED_INCOME,
            CandidateAssetClass.CASH_EQUIVALENT,
        }:
            return self.policy.diversified_maximum_days
        if asset_class in {
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.OPTION,
            CandidateAssetClass.FUTURE,
            CandidateAssetClass.VOLATILITY,
        }:
            return self.policy.volatile_maximum_days
        return self.policy.standard_maximum_days


__all__ = [
    "EvidenceOutageAssessment",
    "EvidenceOutageAuthority",
    "EvidenceOutageDisposition",
    "EvidenceOutagePolicy",
]
