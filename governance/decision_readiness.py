"""Fail-closed candidate decision-readiness policy.

The underwriting completeness matrix is broader than the minimum information that
must block capital. This module identifies the asset-specific dimensions that are
material enough to prohibit a candidate from entering the governed opportunity
funnel when they are unavailable. It cannot authorize capital, relax a CIO hurdle,
or turn partial/shadow information into decision evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

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
        readiness_reasons = (
            (
                "All asset-specific critical decision-information dimensions are available.",
            )
            if not blocking_missing
            else tuple(
                f"Missing critical {item.value} evidence."
                for item in blocking_missing
            )
        )
        reasons = tuple(
            dict.fromkeys((*completeness.available_reasons, *readiness_reasons))
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

    def filter_paper_evidence_result(self, result: object):
        """Remove non-ready candidates before screening while preserving holdings.

        The paper-evidence result is intentionally treated as a structural protocol so
        this governance module does not import the production facade and create a
        circular dependency. Missing candidate evidence fails closed as an exclusion.
        """
        candidates = tuple(getattr(result, "candidates"))
        candidate_evidence = tuple(getattr(result, "candidate_evidence"))
        by_identifier = {
            item.candidate_identifier: item for item in candidate_evidence
        }
        if len(by_identifier) != len(candidate_evidence):
            raise ValueError("candidate evidence must be unique by candidate identifier")

        retained_candidates: list[object] = []
        retained_evidence: list[object] = []
        exclusions = list(tuple(getattr(result, "exclusions")))
        excluded_instruments = {str(item[0]) for item in exclusions}

        for candidate in candidates:
            evidence = by_identifier.get(candidate.identifier)
            if evidence is None:
                reasons = (
                    "Decision-readiness gate: governed candidate evidence is missing.",
                )
                instrument_identifier = candidate.instrument.instrument_id
                if instrument_identifier not in excluded_instruments:
                    exclusions.append((instrument_identifier, reasons))
                    excluded_instruments.add(instrument_identifier)
                continue
            readiness = self.assess(candidate, evidence)
            if readiness.decision_ready:
                retained_candidates.append(candidate)
                retained_evidence.append(evidence)
                continue
            instrument_identifier = candidate.instrument.instrument_id
            if instrument_identifier not in excluded_instruments:
                exclusions.append(
                    (instrument_identifier, readiness.exclusion_reasons)
                )
                excluded_instruments.add(instrument_identifier)

        return replace(
            result,
            candidates=tuple(retained_candidates),
            candidate_evidence=tuple(retained_evidence),
            exclusions=tuple(exclusions),
        )


__all__ = [
    "CandidateDecisionReadiness",
    "CandidateDecisionReadinessPolicy",
]
