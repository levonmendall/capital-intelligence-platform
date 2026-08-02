"""Versioned asset-specific evidence applicability for specialist review."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cio import CandidateAssetClass, CandidateDecisionRecord


class ApplicableAnalysis(str, Enum):
    COMPANY = "company_analysis"
    ASSET_VALUATION = "asset_valuation"


@dataclass(frozen=True, slots=True)
class ApplicableEvidenceRule:
    asset_class: CandidateAssetClass
    required_analysis: ApplicableAnalysis
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if not isinstance(self.required_analysis, ApplicableAnalysis):
            raise TypeError("required_analysis must be ApplicableAnalysis")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description cannot be empty")


@dataclass(frozen=True, slots=True)
class ApplicableEvidenceAssessment:
    policy_version: str
    rule: ApplicableEvidenceRule
    complete: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version cannot be empty")
        if not isinstance(self.rule, ApplicableEvidenceRule):
            raise TypeError("rule must be ApplicableEvidenceRule")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be bool")
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")
        if self.complete and self.reasons:
            raise ValueError("complete assessment cannot contain missing-evidence reasons")
        if not self.complete and not self.reasons:
            raise ValueError("incomplete assessment must explain the missing evidence")


class ApplicableEvidenceMatrix:
    """Resolve the mandatory independent return-driver packet for each asset."""

    version = "applicable-evidence.v1"

    _EQUITY_CLASSES = frozenset(
        {
            CandidateAssetClass.US_EQUITY,
            CandidateAssetClass.INTERNATIONAL_EQUITY,
        }
    )

    def resolve(self, candidate: CandidateDecisionRecord) -> ApplicableEvidenceRule:
        if not isinstance(candidate, CandidateDecisionRecord):
            raise TypeError("candidate must be CandidateDecisionRecord")
        asset_class = candidate.instrument.asset_class
        if asset_class in self._EQUITY_CLASSES:
            return ApplicableEvidenceRule(
                asset_class=asset_class,
                required_analysis=ApplicableAnalysis.COMPANY,
                description=(
                    "point-in-time normalized company quality, financial, earnings, "
                    "cash-flow, growth and valuation analysis"
                ),
            )
        return ApplicableEvidenceRule(
            asset_class=asset_class,
            required_analysis=ApplicableAnalysis.ASSET_VALUATION,
            description=(
                "point-in-time asset-specific valuation and economic return-driver analysis"
            ),
        )

    def assess(
        self,
        candidate: CandidateDecisionRecord,
        *,
        company_present: bool,
        asset_valuation_class: CandidateAssetClass | None,
    ) -> ApplicableEvidenceAssessment:
        rule = self.resolve(candidate)
        reasons: list[str] = []
        if rule.required_analysis is ApplicableAnalysis.COMPANY:
            if not company_present:
                reasons.append(
                    f"{rule.description} is missing for {rule.asset_class.value}"
                )
        else:
            if asset_valuation_class is None:
                reasons.append(
                    f"{rule.description} is missing for {rule.asset_class.value}"
                )
            elif asset_valuation_class is not rule.asset_class:
                reasons.append(
                    "asset-specific valuation packet does not match the candidate asset class"
                )
        return ApplicableEvidenceAssessment(
            policy_version=self.version,
            rule=rule,
            complete=not reasons,
            reasons=tuple(reasons),
        )


__all__ = [
    "ApplicableAnalysis",
    "ApplicableEvidenceAssessment",
    "ApplicableEvidenceMatrix",
    "ApplicableEvidenceRule",
]
