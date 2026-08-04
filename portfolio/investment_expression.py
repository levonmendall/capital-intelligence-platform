"""Rank certified candidates as investable expressions of portfolio posture.

The engine does not create instruments or authorize capital.  It compares candidates
already present in the governed opportunity set and asks which one most directly,
liquidly, cheaply, and diversifiably expresses the current portfolio posture after
capital-flow and market-expectations evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Mapping, Sequence

from portfolio.compounding_allocation import (
    CandidateAllocationDirective,
    PortfolioPosture,
    PortfolioPostureEngine,
    PortfolioSleeve,
    classify_candidate_sleeve,
)


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    if not isfinite(float(value)):
        raise ValueError("expression score inputs must be finite")
    return round(max(low, min(high, float(value))), 8)


@dataclass(frozen=True, slots=True)
class InvestmentExpressionAssessment:
    candidate_identifier: str
    sleeve: PortfolioSleeve
    directness: float
    posture_alignment: float
    capital_flow_support: float
    expectations_advantage: float
    liquidity_quality: float
    implementation_efficiency: float
    diversification_value: float
    catalyst_quality: float
    score: float
    rationale: tuple[str, ...]
    model_version: str = "investment-expression-selection.v1"


class InvestmentExpressionEngine:
    version = "investment-expression-selection.v1"

    @staticmethod
    def _signals(context: object | None) -> tuple[object, ...]:
        bundle = getattr(context, "forward_intelligence", None)
        return tuple(getattr(bundle, "signals", ()) or ())

    @staticmethod
    def _signal(signals: Sequence[object], text: str) -> object | None:
        lowered = text.lower()
        return next(
            (
                item
                for item in signals
                if lowered in str(getattr(item, "name", "")).lower()
            ),
            None,
        )

    def assess(
        self,
        *,
        candidate: object,
        context: object | None,
        posture: PortfolioPosture,
        portfolio: object | None,
    ) -> InvestmentExpressionAssessment:
        identifier = str(getattr(candidate, "identifier"))
        sleeve = classify_candidate_sleeve(candidate)
        preferred = sleeve in posture.preferred_sleeves
        discouraged = sleeve in posture.discouraged_sleeves
        range_value = posture.range_for(sleeve)
        directness = _clip(
            (0.75 if preferred else -0.65 if discouraged else 0.10)
            + 0.20 * range_value.midpoint
        )

        signals = self._signals(context)
        flow = self._signal(signals, "capital-flow")
        expectations = self._signal(signals, "market expectations")
        flow_support = _clip(
            float(getattr(flow, "expected_return_impact", 0.0)) * 8.0
            * float(getattr(flow, "confidence", 0.0))
        )
        expectations_advantage = _clip(
            float(getattr(expectations, "expected_return_impact", 0.0)) * 8.0
            * float(getattr(expectations, "confidence", 0.0))
        )

        market = getattr(context, "market", None)
        liquidity_quality = _clip(float(getattr(market, "liquidity", 0.0)))
        cost = max(0.0, float(getattr(candidate, "implementation_cost_return", 0.0)))
        implementation_efficiency = _clip(1.0 - min(1.0, cost / 0.02), 0.0, 1.0)

        instrument = getattr(candidate, "instrument", None)
        candidate_bucket = str(getattr(instrument, "correlation_bucket", "")).strip()
        held_buckets = {
            str(getattr(item, "correlation_bucket", "")).strip()
            for item in tuple(getattr(portfolio, "positions", ()) or ())
            if str(getattr(item, "correlation_bucket", "")).strip()
        }
        diversification = 0.65 if candidate_bucket and candidate_bucket not in held_buckets else 0.20
        catalysts = tuple(getattr(candidate, "primary_catalysts", ()) or ())
        catalyst_quality = _clip(0.25 + 0.20 * min(3, len(catalysts)), 0.0, 1.0)
        posture_alignment = _clip(
            directness * (0.60 + 0.40 * posture.confidence)
        )
        score = _clip(
            0.24 * posture_alignment
            + 0.18 * flow_support
            + 0.20 * expectations_advantage
            + 0.12 * liquidity_quality
            + 0.10 * implementation_efficiency
            + 0.09 * diversification
            + 0.07 * catalyst_quality
        )
        rationale = (
            f"Sleeve={sleeve.value}; posture={posture.regime.value}",
            f"Directness={directness:+.2f}; posture alignment={posture_alignment:+.2f}",
            f"Flow support={flow_support:+.2f}; expectations advantage={expectations_advantage:+.2f}",
            f"Liquidity={liquidity_quality:+.2f}; implementation efficiency={implementation_efficiency:+.2f}",
            f"Diversification={diversification:+.2f}; catalyst quality={catalyst_quality:+.2f}",
        )
        return InvestmentExpressionAssessment(
            candidate_identifier=identifier,
            sleeve=sleeve,
            directness=directness,
            posture_alignment=posture_alignment,
            capital_flow_support=flow_support,
            expectations_advantage=expectations_advantage,
            liquidity_quality=liquidity_quality,
            implementation_efficiency=implementation_efficiency,
            diversification_value=diversification,
            catalyst_quality=catalyst_quality,
            score=score,
            rationale=rationale,
            model_version=self.version,
        )


class InvestorPortfolioPostureEngine(PortfolioPostureEngine):
    """Attach expression quality to the existing posture directives."""

    def __init__(self, *, expression_engine: InvestmentExpressionEngine | None = None) -> None:
        super().__init__()
        self.expression_engine = expression_engine or InvestmentExpressionEngine()
        self._contexts: dict[str, object] = {}
        self._portfolio: object | None = None
        self.latest_assessments: tuple[InvestmentExpressionAssessment, ...] = ()

    def set_expression_context(
        self,
        *,
        candidates: Sequence[object],
        specialist_contexts: Sequence[object],
        portfolio: object,
    ) -> None:
        if len(candidates) != len(specialist_contexts):
            raise ValueError("candidate and specialist-context counts must match")
        self._contexts = {
            str(getattr(candidate, "identifier")): context
            for candidate, context in zip(candidates, specialist_contexts, strict=True)
        }
        self._portfolio = portfolio

    def clear_expression_context(self) -> None:
        self._contexts = {}
        self._portfolio = None

    def directives(
        self,
        candidates: Sequence[object],
        posture: PortfolioPosture,
    ) -> tuple[CandidateAllocationDirective, ...]:
        base = super().directives(candidates, posture)
        assessments = tuple(
            self.expression_engine.assess(
                candidate=candidate,
                context=self._contexts.get(str(getattr(candidate, "identifier"))),
                posture=posture,
                portfolio=self._portfolio,
            )
            for candidate in candidates
        )
        self.latest_assessments = assessments
        by_identifier = {item.candidate_identifier: item for item in assessments}
        return tuple(
            replace(
                directive,
                posture_alignment=by_identifier[
                    directive.candidate_identifier
                ].score,
                preferred=(
                    directive.preferred
                    and by_identifier[directive.candidate_identifier].score > 0.0
                ),
                rationale=(
                    directive.rationale
                    + " Expression selection: "
                    + "; ".join(
                        by_identifier[directive.candidate_identifier].rationale
                    )
                    + f"; composite score={by_identifier[directive.candidate_identifier].score:+.2f}."
                ),
            )
            for directive in base
        )


__all__ = [
    "InvestmentExpressionAssessment",
    "InvestmentExpressionEngine",
    "InvestorPortfolioPostureEngine",
]
