"""Governed committee review enrichment for the canonical six-specialist packet."""

from __future__ import annotations

from dataclasses import replace

from cio.committee import (
    EvidenceVetoCategory,
    IndependentSpecialistPacket,
)
from cio.models import (
    CandidateAssetClass,
    SpecialistPosition,
    SpecialistRole,
)
from committee.specialists import (
    CandidateSpecialistContext,
    IndependentSpecialistService as _IndependentSpecialistService,
)
from company import CompanyFactor


_EQUITY_CLASSES = frozenset(
    {
        CandidateAssetClass.US_EQUITY,
        CandidateAssetClass.INTERNATIONAL_EQUITY,
    }
)


def _unique(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for group in groups
            for item in group
            if isinstance(item, str) and item.strip()
        )
    )


class IndependentSpecialistService(_IndependentSpecialistService):
    """Preserve complete evidence and strengthen specialist-to-CIO handoff."""

    def analyze(self, candidate, context) -> IndependentSpecialistPacket:
        packet = super().analyze(candidate, context)
        if not isinstance(context, CandidateSpecialistContext):
            raise TypeError("context must be a CandidateSpecialistContext")

        enriched = []
        for analysis in packet.analyses:
            if analysis.role is SpecialistRole.MACRO_ECONOMIC:
                analysis = self._enrich_macro(analysis, context)
            elif analysis.role is SpecialistRole.MARKET:
                analysis = self._enrich_market(analysis, context)
            elif analysis.role is SpecialistRole.FUNDAMENTAL_VALUATION:
                analysis = self._enrich_fundamental(analysis, context)
            elif analysis.role is SpecialistRole.EVIDENCE_GOVERNANCE:
                analysis = self._enforce_equity_coverage(
                    analysis,
                    candidate=candidate,
                    context=context,
                )
            enriched.append(analysis)

        return IndependentSpecialistPacket(
            candidate_identifier=packet.candidate_identifier,
            analyses=tuple(enriched),
            historical_learning=packet.historical_learning,
        )

    @staticmethod
    def _enrich_macro(analysis, context: CandidateSpecialistContext):
        macro = context.macro
        diagnostics = (
            f"macro regime={macro.regime}",
            f"candidate macro return impact={macro.expected_return_impact:+.6f}",
            f"macro confidence={macro.confidence:.6f}",
        )
        return replace(
            analysis,
            supporting_evidence=_unique(
                analysis.supporting_evidence,
                diagnostics,
                macro.tailwinds,
            ),
            contradictory_evidence=_unique(
                analysis.contradictory_evidence,
                macro.headwinds,
                macro.systemic_risks,
            ),
            risks=_unique(
                analysis.risks,
                macro.headwinds,
                macro.systemic_risks,
            ),
            change_conditions=_unique(
                analysis.change_conditions,
                macro.scenarios,
            ),
            evidence_origin_identifiers=_unique(
                analysis.evidence_origin_identifiers,
                macro.evidence_identifiers,
            ),
        )

    @staticmethod
    def _enrich_market(analysis, context: CandidateSpecialistContext):
        market = context.market
        diagnostics = (
            f"market regime={market.market_regime}",
            f"trend={market.trend:+.6f}",
            f"momentum={market.momentum:+.6f}",
            f"breadth={market.breadth:+.6f}",
            f"liquidity={market.liquidity:+.6f}",
            f"positioning={market.positioning:+.6f}",
            f"candidate market return impact={market.expected_return_impact:+.6f}",
            f"market confidence={market.confidence:.6f}",
        )
        return replace(
            analysis,
            supporting_evidence=_unique(
                analysis.supporting_evidence,
                diagnostics,
                market.evidence,
            ),
            contradictory_evidence=_unique(
                analysis.contradictory_evidence,
                market.risks,
            ),
            risks=_unique(analysis.risks, market.risks),
            change_conditions=_unique(
                analysis.change_conditions,
                market.entry_conditions,
            ),
            evidence_origin_identifiers=_unique(
                analysis.evidence_origin_identifiers,
                market.evidence_identifiers or market.evidence,
            ),
        )

    @staticmethod
    def _enrich_fundamental(analysis, context: CandidateSpecialistContext):
        company = context.company
        if company is None:
            return analysis

        factors = tuple(
            company.factor(factor)
            for factor in (
                CompanyFactor.QUALITY,
                CompanyFactor.GROWTH,
                CompanyFactor.EARNINGS_QUALITY,
                CompanyFactor.VALUATION,
            )
        )
        factor_evidence = tuple(
            evidence
            for factor in factors
            for evidence in factor.evidence
        )
        factor_risks = tuple(
            risk
            for factor in factors
            for risk in factor.risks
        )
        return replace(
            analysis,
            supporting_evidence=_unique(
                analysis.supporting_evidence,
                factor_evidence,
            ),
            contradictory_evidence=_unique(
                analysis.contradictory_evidence,
                factor_risks,
            ),
            risks=_unique(analysis.risks, factor_risks),
            evidence_origin_identifiers=_unique(
                analysis.evidence_origin_identifiers,
                factor_evidence,
            ),
        )

    @staticmethod
    def _enforce_equity_coverage(analysis, *, candidate, context):
        asset_class = candidate.instrument.asset_class
        reasons = list(analysis.veto_reasons)
        categories = list(analysis.veto_categories)

        if (
            asset_class in _EQUITY_CLASSES
            and context.company is None
            and not any(
                "company analysis is missing" in reason.lower()
                for reason in reasons
            )
        ):
            reasons.append(
                "point-in-time normalized company analysis is missing for an equity"
            )
            categories.append(EvidenceVetoCategory.OPERATIONAL_UNAVAILABLE)

        if tuple(reasons) == analysis.veto_reasons:
            return analysis

        return replace(
            analysis,
            position=SpecialistPosition.OPPOSED,
            conclusion=(
                "The candidate evidence does not satisfy role-complete governance requirements."
            ),
            risks=_unique(analysis.risks, tuple(reasons)),
            limitations=_unique(
                analysis.limitations,
                ("Required equity valuation coverage is incomplete",),
            ),
            change_conditions=_unique(
                analysis.change_conditions,
                (
                    "Provide the required point-in-time company valuation packet",
                ),
            ),
            veto_reasons=tuple(reasons),
            veto_categories=tuple(categories),
        )


__all__ = ["IndependentSpecialistService"]
