"""Candidate-level information completeness diagnostics.

This module converts existing candidate/evidence objects into the asset-underwriting
matrix so CIO reports can disclose what is available, partial, and missing. It never
manufactures unavailable evidence. Decision gating is owned separately by
``governance.decision_readiness``.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from cio.models import CandidateAssetClass
from intelligence.asset_underwriting import (
    AssetUnderwritingPolicy,
    UnderwritingCoverage,
    UnderwritingDimension,
)
from intelligence.forward_decision import EvidenceAvailability, ForwardDecisionDimension
from portfolio.derivative_lifecycle import DerivativeLifecycleAuthority


_DRIVER_DIMENSIONS: dict[str, tuple[UnderwritingDimension, ...]] = {
    "cash_flow": (UnderwritingDimension.CASH_FLOW,),
    "capital_allocation": (UnderwritingDimension.CORPORATE_ACTIONS,),
    "currency": (UnderwritingDimension.CURRENCY,),
    "carry": (UnderwritingDimension.CARRY,),
    "yield": (UnderwritingDimension.CARRY,),
    "roll_down": (UnderwritingDimension.CARRY, UnderwritingDimension.CURVE),
    "curve_carry": (UnderwritingDimension.CARRY, UnderwritingDimension.CURVE),
    "roll_yield": (UnderwritingDimension.CARRY, UnderwritingDimension.CURVE),
    "spread": (UnderwritingDimension.CREDIT,),
    "default_loss": (UnderwritingDimension.CREDIT,),
    "credit_quality": (UnderwritingDimension.CREDIT,),
    "inventory": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "production": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "demand": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "capacity": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "outages": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "weather": (UnderwritingDimension.PHYSICAL_BALANCE,),
    "network_activity": (UnderwritingDimension.ONCHAIN,),
    "issuance": (UnderwritingDimension.ONCHAIN,),
    "exchange_balances": (UnderwritingDimension.ONCHAIN,),
    "stablecoin_liquidity": (UnderwritingDimension.ONCHAIN,),
    "protocol_risk": (UnderwritingDimension.ONCHAIN,),
    "funding": (UnderwritingDimension.POSITIONING,),
    "open_interest": (UnderwritingDimension.POSITIONING,),
    "positioning": (UnderwritingDimension.POSITIONING,),
    "implied_realized_gap": (UnderwritingDimension.DERIVATIVES,),
    "skew": (UnderwritingDimension.DERIVATIVES,),
    "term_structure": (UnderwritingDimension.DERIVATIVES,),
    "convexity": (UnderwritingDimension.DERIVATIVES,),
}


@dataclass(frozen=True, slots=True)
class CandidateInformationCompleteness:
    candidate_identifier: str
    coverage: UnderwritingCoverage
    available_reasons: tuple[str, ...]
    missing_reasons: tuple[str, ...]
    investment_authority: bool = False
    schema_version: str = "candidate-information-completeness.v2"


def _available_forward_dimensions(evidence: object) -> tuple[ForwardDecisionDimension, ...]:
    forward = getattr(evidence, "forward_intelligence", None)
    context = None if forward is None else getattr(forward, "decision_context", None)
    if context is None:
        return ()
    return tuple(
        item.dimension
        for item in context.dimensions
        if item.availability is EvidenceAvailability.AVAILABLE
    )


def _certified_asset_underwriting(evidence: object):
    for name in (
        "asset_specific_underwriting",
        "asset_underwriting",
        "economic_underwriting",
    ):
        value = getattr(evidence, name, None)
        if value is not None and bool(getattr(value, "decision_certified", False)):
            return value
    return None


class CandidateInformationCompletenessEngine:
    version = "candidate-information-completeness.v2"

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

        # The canonical cash hurdle is itself a governed point-in-time return input.
        # A short U.S.-Treasury cash-equivalent candidate explicitly sets its base
        # return from that hurdle and carries Treasury identity/duration metadata.
        # Treat that combination as carry evidence rather than forcing the same
        # curve/credit packet required of longer-duration fixed income.
        opportunity_cost = getattr(candidate, "opportunity_cost_return", None)
        if (
            asset_class is CandidateAssetClass.CASH_EQUIVALENT
            and bool(getattr(instrument, "is_us_treasury", False))
            and UnderwritingDimension.MACRO in available
            and isinstance(opportunity_cost, (int, float))
            and not isinstance(opportunity_cost, bool)
            and isfinite(float(opportunity_cost))
        ):
            available.add(UnderwritingDimension.CARRY)
            reasons.append(
                "governed cash-hurdle return and Treasury identity provide short-duration carry evidence"
            )

        forward_dimensions = set(_available_forward_dimensions(evidence))
        forward_mapping = {
            ForwardDecisionDimension.FUNDAMENTALS: UnderwritingDimension.FUNDAMENTALS,
            ForwardDecisionDimension.POSITIONING: UnderwritingDimension.POSITIONING,
            ForwardDecisionDimension.DERIVATIVES: UnderwritingDimension.DERIVATIVES,
            ForwardDecisionDimension.CORPORATE_ACTIONS: UnderwritingDimension.CORPORATE_ACTIONS,
        }
        for source_dimension, target_dimension in forward_mapping.items():
            if source_dimension in forward_dimensions:
                available.add(target_dimension)
                reasons.append(
                    f"certified {source_dimension.value} forward evidence is available"
                )

        forward = getattr(evidence, "forward_intelligence", None)
        if forward is not None and getattr(forward, "currency_regime", None) is not None:
            available.add(UnderwritingDimension.CURRENCY)
            reasons.append("certified currency transmission regime is present")

        underwriting = _certified_asset_underwriting(evidence)
        if underwriting is not None:
            observed = tuple(str(item) for item in getattr(underwriting, "observed_drivers", ()))
            for driver in observed:
                for dimension in _DRIVER_DIMENSIONS.get(driver, ()):
                    available.add(dimension)
            if observed:
                reasons.append(
                    "decision-certified asset-specific underwriting drivers are present"
                )

        exposure_profile = getattr(evidence, "exposure_profile", None)
        lifecycle = (
            None if exposure_profile is None else getattr(exposure_profile, "derivative_lifecycle", None)
        )
        if bool(getattr(instrument, "uses_derivatives", False)):
            if lifecycle is not None:
                assessment = DerivativeLifecycleAuthority().assess(
                    lifecycle,
                    instrument_identifier=getattr(instrument, "instrument_id"),
                    as_of=getattr(candidate, "as_of"),
                )
                if assessment.authorized:
                    available.add(UnderwritingDimension.EXECUTION)
                    reasons.append("derivative lifecycle and execution controls are complete")
        elif UnderwritingDimension.IDENTITY in available and UnderwritingDimension.LIQUIDITY in available:
            available.add(UnderwritingDimension.EXECUTION)
            reasons.append("non-derivative execution identity and liquidity evidence are present")

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
            available_reasons=tuple(dict.fromkeys(reasons)),
            missing_reasons=missing_reasons,
        )


__all__ = [
    "CandidateInformationCompleteness",
    "CandidateInformationCompletenessEngine",
]
