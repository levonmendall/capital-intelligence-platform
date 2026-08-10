"""Fail-closed candidate decision-readiness policy.

The underwriting completeness matrix is broader than the minimum information that
must block capital.  This module identifies the asset-specific dimensions that are
material enough to prohibit a candidate from entering the governed opportunity
funnel when they are unavailable.  It cannot authorize capital, relax a CIO hurdle,
or turn partial/shadow information into decision evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

from cio.models import CandidateAssetClass
from intelligence.asset_underwriting import UnderwritingCoverage, UnderwritingDimension
from intelligence.information_completeness import (
    CandidateInformationCompleteness,
    CandidateInformationCompletenessEngine,
)

_COMMON_CRITICAL = frozenset(
    {
        UnderwritingDimension.IDENTITY,
        UnderwritingDimension.MARKET_DATA,
        UnderwritingDimension.LIQUIDITY,
        UnderwritingDimension.MACRO,
        UnderwritingDimension.VALUATION,
        UnderwritingDimension.HISTORY,
    }
)

_CRITICAL: dict[CandidateAssetClass, frozenset[UnderwritingDimension]] = {
    CandidateAssetClass.US_EQUITY: _COMMON_CRITICAL
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CASH_FLOW,
    },
    CandidateAssetClass.INTERNATIONAL_EQUITY: _COMMON_CRITICAL
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CASH_FLOW,
        UnderwritingDimension.CURRENCY,
    },
    CandidateAssetClass.US_ETF: _COMMON_CRITICAL,
    CandidateAssetClass.CASH_EQUIVALENT: {
        UnderwritingDimension.IDENTITY,
        UnderwritingDimension.MARKET_DATA,
        UnderwritingDimension.LIQUIDITY,
        UnderwritingDimension.MACRO,
        UnderwritingDimension.CARRY,
    },
    CandidateAssetClass.FIXED_INCOME: _COMMON_CRITICAL
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.CREDIT,
        UnderwritingDimension.CURRENCY,
    },
    CandidateAssetClass.COMMODITY: _COMMON_CRITICAL
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.PHYSICAL_BALANCE,
    },
    CandidateAssetClass.FX: _COMMON_CRITICAL
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURRENCY,
    },
    CandidateAssetClass.CRYPTO: _COMMON_CRITICAL
    | {UnderwritingDimension.ONCHAIN},
    CandidateAssetClass.REAL_ESTATE: _COMMON_CRITICAL
    | {
        UnderwritingDimension.FUNDAMENTALS,
        UnderwritingDimension.CASH_FLOW,
        UnderwritingDimension.CREDIT,
    },
    CandidateAssetClass.FUTURE: _COMMON_CRITICAL
    | {
        UnderwritingDimension.CARRY,
        UnderwritingDimension.CURVE,
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.OPTION: _COMMON_CRITICAL
    | {
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.VOLATILITY: _COMMON_CRITICAL
    | {
        UnderwritingDimension.DERIVATIVES,
        UnderwritingDimension.EXECUTION,
    },
    CandidateAssetClass.ALTERNATIVE: _COMMON_CRITICAL
    | {UnderwritingDimension.EXECUTION},
    CandidateAssetClass.OTHER: _COMMON_CRITICAL
    | {UnderwritingDimension.EXECUTION},
}


@dataclass(frozen=True, slots=True)
class CandidateDecisionReadiness:
    candidate_identifier: str
    asset_class: CandidateAssetClass
    coverage: UnderwritingCoverage
    blocking_required: tuple[UnderwritingDimension, ...]
    blocking_missing: tuple[UnderwritingDimension, ...]
    decision_ready: bool
    reasons: tuple[str, ...]
    information_completeness: CandidateInformationCompleteness
    investment_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "candidate-decision-readiness.v1"

    @property
    def exclusion_reasons(self) -> tuple[str, ...]:
        if self.decision_ready:
            return ()
        return tuple(
            f"Decision-readiness gate: {item.value} evidence is critically required for {self.asset_class.value}."
            for item in self.blocking_missing
        )


class CandidateDecisionReadinessPolicy:
    """Identify missing evidence that must block new capital for an asset class."""

    version = "candidate-decision-readiness-policy.v1"

    def __init__(
        self,
        completeness_engine: CandidateInformationCompletenessEngine | None = None,
    ) -> None:
        self.completeness_engine = (
            completeness_engine or CandidateInformationCompletenessEngine()
        )

    @staticmethod
    def blocking_dimensions(
        asset_class: CandidateAssetClass,
    ) -> tuple[UnderwritingDimension, ...]:
        if not isinstance(asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        return tuple(sorted(_CRITICAL[asset_class], key=lambda item: item.value))

    def assess(self, candidate: object, evidence: object) -> CandidateDecisionReadiness:
        completeness = self.completeness_engine.assess(candidate, evidence)
        asset_class = completeness.coverage.asset_class
        required = self.blocking_dimensions(asset_class)
        missing_set = set(completeness.coverage.missing)
        blocking_missing = tuple(item for item in required if item in missing_set)
        reasons = tuple(
            dict.fromkeys(
                (
                    *completeness.available_reasons,
                    *(
                        (
                            "All asset-specific critical decision-information dimensions are available.",
                        )
                        if not blocking_missing
                        else tuple(
                            f"Missing critical {item.value} evidence."
                            for item in blocking_missing
                        )
                    ),
                )
            )
        )
        return CandidateDecisionReadiness(
            candidate_identifier=completeness.candidate_identifier,
            asset_class=asset_class,
            coverage=completeness.coverage,
            blocking_required=required,
            blocking_missing=blocking_missing,
            decision_ready=not blocking_missing,
            reasons=reasons,
            information_completeness=completeness,
        )


__all__ = [
    "CandidateDecisionReadiness",
    "CandidateDecisionReadinessPolicy",
]
