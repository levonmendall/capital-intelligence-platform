"""Fail-closed candidate decision-readiness policy.

The underwriting completeness matrix is broader than the minimum information that
must block capital. This module identifies the asset-specific dimensions that are
material enough to prohibit a candidate from entering the governed opportunity
funnel when they are unavailable. It cannot authorize capital, relax a CIO hurdle,
or turn partial/shadow information into decision evidence.

Decision readiness is deliberately two-axis. The execution vehicle determines the
minimum information required to trade the exact instrument safely. A distinct
``economic_exposure_class`` may require deeper underlying intelligence (for example,
a listed crypto wrapper still has crypto economics). Missing deep economic-exposure
intelligence is disclosed separately and can be promoted to a capital-blocking rule
only through the governed certification process. This prevents a wrapper label from
masquerading as complete understanding without abruptly converting existing pilot
coverage into an unreviewed strategy change.
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

# Specialized dimensions that disclose whether a wrapper is understood at the level
# of its underlying economics. Common vehicle dimensions (identity, market data,
# liquidity, generic macro/history) remain owned by the execution-vehicle lane.
_ECONOMIC_EXPOSURE_CRITICAL: dict[
    CandidateAssetClass, frozenset[UnderwritingDimension]
] = {
    CandidateAssetClass.US_EQUITY: frozenset({UnderwritingDimension.VALUATION}),
    CandidateAssetClass.INTERNATIONAL_EQUITY: frozenset(
        {UnderwritingDimension.VALUATION, UnderwritingDimension.CURRENCY}
    ),
    CandidateAssetClass.US_ETF: frozenset({UnderwritingDimension.VALUATION}),
    CandidateAssetClass.CASH_EQUIVALENT: frozenset({UnderwritingDimension.CARRY}),
    CandidateAssetClass.FIXED_INCOME: frozenset(
        {
            UnderwritingDimension.CARRY,
            UnderwritingDimension.CURVE,
            UnderwritingDimension.CREDIT,
        }
    ),
    CandidateAssetClass.COMMODITY: frozenset(
        {
            UnderwritingDimension.CARRY,
            UnderwritingDimension.CURVE,
            UnderwritingDimension.PHYSICAL_BALANCE,
        }
    ),
    CandidateAssetClass.FX: frozenset(
        {UnderwritingDimension.CARRY, UnderwritingDimension.CURRENCY}
    ),
    CandidateAssetClass.CRYPTO: frozenset(
        {UnderwritingDimension.ONCHAIN, UnderwritingDimension.POSITIONING}
    ),
    CandidateAssetClass.REAL_ESTATE: frozenset(
        {
            UnderwritingDimension.FUNDAMENTALS,
            UnderwritingDimension.CASH_FLOW,
            UnderwritingDimension.CREDIT,
        }
    ),
    CandidateAssetClass.FUTURE: frozenset(
        {
            UnderwritingDimension.CARRY,
            UnderwritingDimension.CURVE,
            UnderwritingDimension.DERIVATIVES,
        }
    ),
    CandidateAssetClass.OPTION: frozenset(
        {UnderwritingDimension.DERIVATIVES, UnderwritingDimension.POSITIONING}
    ),
    CandidateAssetClass.VOLATILITY: frozenset(
        {UnderwritingDimension.DERIVATIVES, UnderwritingDimension.POSITIONING}
    ),
    CandidateAssetClass.ALTERNATIVE: frozenset(
        {UnderwritingDimension.POSITIONING}
    ),
    CandidateAssetClass.OTHER: frozenset(),
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
    economic_exposure_class: CandidateAssetClass | None = None
    deep_required: tuple[UnderwritingDimension, ...] = ()
    deep_missing: tuple[UnderwritingDimension, ...] = ()
    deep_intelligence_complete: bool = True
    investment_authority: bool = False
    execution_authority: bool = False
    schema_version: str = "candidate-decision-readiness.v2"

    @property
    def exclusion_reasons(self) -> tuple[str, ...]:
        if self.decision_ready:
            return ()
        return tuple(
            f"Decision-readiness gate: {item.value} evidence is critically required for {self.asset_class.value}."
            for item in self.blocking_missing
        )

    @property
    def deep_intelligence_gaps(self) -> tuple[str, ...]:
        return tuple(
            f"Deep economic-exposure intelligence: {item.value} evidence is not decision-complete for {(self.economic_exposure_class or self.asset_class).value}."
            for item in self.deep_missing
        )


class CandidateDecisionReadinessPolicy:
    """Identify missing evidence that must block new capital for an asset class."""

    version = "candidate-decision-readiness-policy.v2-two-axis"

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

    @staticmethod
    def economic_exposure_dimensions(
        economic_exposure_class: CandidateAssetClass,
    ) -> tuple[UnderwritingDimension, ...]:
        if not isinstance(economic_exposure_class, CandidateAssetClass):
            raise TypeError("economic_exposure_class must be CandidateAssetClass")
        return tuple(
            sorted(
                _ECONOMIC_EXPOSURE_CRITICAL[economic_exposure_class],
                key=lambda item: item.value,
            )
        )

    def assess(self, candidate: object, evidence: object) -> CandidateDecisionReadiness:
        completeness = self.completeness_engine.assess(candidate, evidence)
        asset_class = completeness.coverage.asset_class
        instrument = getattr(candidate, "instrument")
        economic_exposure_class = (
            getattr(instrument, "economic_exposure_class", None) or asset_class
        )
        if not isinstance(economic_exposure_class, CandidateAssetClass):
            raise TypeError("candidate economic exposure class must be CandidateAssetClass")

        required = self.blocking_dimensions(asset_class)
        available = set(completeness.coverage.available)
        blocking_missing = tuple(item for item in required if item not in available)

        deep_required = self.economic_exposure_dimensions(economic_exposure_class)
        deep_missing = tuple(item for item in deep_required if item not in available)
        deep_complete = not deep_missing

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
        deep_reasons = (
            (
                f"Deep {economic_exposure_class.value} economic-exposure intelligence is complete.",
            )
            if deep_complete
            else tuple(
                f"Deep {economic_exposure_class.value} intelligence is missing {item.value} evidence; the gap is disclosed and remains promotion-gated."
                for item in deep_missing
            )
        )
        reasons = tuple(
            dict.fromkeys(
                (*completeness.available_reasons, *readiness_reasons, *deep_reasons)
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
            economic_exposure_class=economic_exposure_class,
            deep_required=deep_required,
            deep_missing=deep_missing,
            deep_intelligence_complete=deep_complete,
        )

    def filter_paper_evidence_result(self, result: object):
        """Remove non-ready candidates before screening while preserving holdings.

        The paper-evidence result is intentionally treated as a structural protocol so
        this governance module does not import the production facade and create a
        circular dependency. Missing candidate evidence fails closed as an exclusion.
        Deep wrapper-underlying gaps are disclosed by ``assess`` but are not silently
        promoted into new capital blocks until the corresponding analytical domain is
        certified for that economic exposure.
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
