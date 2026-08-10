"""Candidate-level information completeness diagnostics.

This module converts existing candidate/evidence objects into the asset-underwriting
matrix so CIO reports can disclose what is available, partial, and missing. It is
observability only and cannot relax an evidence veto or manufacture unavailable
evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

from intelligence.asset_underwriting import (
    AssetUnderwritingPolicy,
    UnderwritingCoverage,
    UnderwritingDimension,
)
from intelligence.forward_decision import EvidenceAvailability, ForwardDecisionDimension


@dataclass(frozen=True, slots=True)
class CandidateInformationCompleteness:
    candidate_identifier: str
    coverage: UnderwritingCoverage
    available_reasons: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    investment_authority: bool = False
    schema_version: str = "candidate-information-completeness.v1"


class CandidateInformationCompletenessEngine:
    version = "candidate-information-completeness.v1"

    def assess(self, candidate: object, evidence: object) -> CandidateInformationCompleteness:
        instrument = getattr(candidate, "instrument")
        asset_class = getattr(instrument, "asset_class")
        available: set[UnderwritingDimension] = set()
        reasons: list[str] = []

        if getattr(instrument, "security_master_snapshot_identifier", None) and getattr(
            instrument, "security_master_record_identifiers", ()
        ):
            available.add(UnderwritingDimension.IDENTITY)
            reasons.append("point-in-time security-master identity is present")
        if getattr(candidate, "evidence_identifiers", ()):
            available.add(UnderwritingDimension.MARKET_DATA)
            reasons.append("candidate market evidence identifiers are present")
        if float(getattr(candidate, "liquidity_score", 0.0)) > 0.0:
            available.add(UnderwritingDimension.LIQUIDITY)
            reasons.append("candidate liquidity evidence is present")
        macro = getattr(evidence, "macro", None)
        if macro is not None and getattr(macro, "evidence_identifiers", ()):
            available.add(UnderwritingDimension.MACRO)
            reasons.append("macro evidence identifiers are present")
        if float(getattr(instrument, "analytical_coverage", 0.0)) >= 0.50:
            available.add(UnderwritingDimension.HISTORY)
            reasons.append("analytical history coverage is at least 50%")
        company = getattr(evidence, "company", None)
        if company is not None:
            available.update(
                {
                    UnderwritingDimension.FUNDAMENTALS,
                    UnderwritingDimension.VALUATION,
                    UnderwritingDimension.CASH_FLOW,
                }
            )
            reasons.append("point-in-time company analysis is present")
        if getattr(evidence, "asset_valuation", None) is not None:
            available.add(UnderwritingDimension.VALUATION)
            reasons.append("asset-specific valuation packet is present")

        forward = getattr(evidence, "forward_intelligence", None)
        context = None if forward is None else getattr(forward, "decision_context", None)
        if context is not None:
            by_dimension = {item.dimension: item for item in context.dimensions}
            positioning = by_dimension.get(ForwardDecisionDimension.POSITIONING)
            if positioning is not None and positioning.availability is EvidenceAvailability.AVAILABLE:
                available.add(UnderwritingDimension.POSITIONING)
                reasons.append("certified positioning research is available")
            derivatives = by_dimension.get(ForwardDecisionDimension.DERIVATIVES)
            if derivatives is not None and derivatives.availability is EvidenceAvailability.AVAILABLE:
                available.add(UnderwritingDimension.DERIVATIVES)
                reasons.append("certified derivatives research is available")
        if forward is not None and getattr(forward, "currency_regime", None) is not None:
            available.add(UnderwritingDimension.CURRENCY)
            reasons.append("certified currency transmission regime is present")

        coverage = AssetUnderwritingPolicy().assess(
            asset_class,
            tuple(sorted(available, key=lambda item: item.value)),
        )
        missing_reasons = tuple(
            f"{item.value} evidence is required but not decision-complete"
            for item in coverage.missing
        )
        return CandidateInformationCompleteness(
            candidate_identifier=str(getattr(candidate, "identifier")),
            coverage=coverage,
            available_reasons=tuple(reasons),
            missing_reasons=missing_reasons,
        )


__all__ = [
    "CandidateInformationCompleteness",
    "CandidateInformationCompletenessEngine",
]
