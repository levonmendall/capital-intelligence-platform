"""Dynamic causal leadership transition intelligence for global rotation.

This layer converts already-governed structural-theme, leadership, expectations and
mispriced-change evidence into a stateful-looking transition assessment for the current
point in time. It does not invent value-chain relationships and it does not authorize
capital. A successor must already be explicitly named by governed theme transmission,
and candidate-specific economics must independently corroborate the opportunity.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from intelligence.forward import ForwardIntelligenceBundle, ThemeStage, TrendStage
from intelligence.global_leadership import assess_global_leadership_economics
from intelligence.mispriced_change import MispricedChangeState, assess_mispriced_change
from intelligence.theme_successor import theme_successor_score


class CausalTransitionStage(str, Enum):
    UNAVAILABLE = "unavailable"
    SOURCE_LEADERSHIP = "source_leadership"
    EARLY_SUCCESSOR = "early_successor"
    ACCELERATING_SUCCESSOR = "accelerating_successor"
    BROADENING_SUCCESSOR = "broadening_successor"
    PRICED_OR_CROWDED = "priced_or_crowded"
    DECAYING = "decaying"


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("causal rotation values must be finite")
    return round(max(low, min(high, number)), 8)


def _pricing_score(bundle: ForwardIntelligenceBundle) -> float:
    """Recover the disclosed point-in-time theme priced-in estimate when available."""

    values: list[float] = []
    for signal in bundle.signals:
        if not signal.identifier.startswith("signal:theme:"):
            continue
        for item in signal.contradictory_evidence:
            marker = "Estimated theme benefit already priced="
            if not item.startswith(marker) or not item.endswith("%"):
                continue
            try:
                values.append(float(item[len(marker):-1]) / 100.0)
            except ValueError:
                continue
    return _clip(max(values) if values else 0.50)


def _bottleneck_score(bundle: ForwardIntelligenceBundle) -> float:
    values: list[float] = []
    for diagnostic in bundle.diagnostics:
        if not diagnostic.startswith("Theme bottlenecks: "):
            continue
        for token in diagnostic.split(":", 1)[1].split(","):
            if "=" not in token:
                continue
            try:
                values.append(float(token.rsplit("=", 1)[1].strip()))
            except ValueError:
                continue
    if not values:
        return 0.0
    return round(max(-1.0, min(1.0, max(values))), 8)


def _trend_acceleration(bundle: ForwardIntelligenceBundle) -> float:
    stage = bundle.trend_stage
    return {
        TrendStage.EARLY: 0.65,
        TrendStage.CONFIRMED: 0.78,
        TrendStage.BROADENING: 0.88,
        TrendStage.MATURE: 0.50,
        TrendStage.CROWDED: 0.30,
        TrendStage.REVERSING: 0.10,
        TrendStage.DETERIORATING: 0.05,
        None: 0.50,
    }[stage]


def _theme_acceleration(bundle: ForwardIntelligenceBundle) -> float:
    stage = bundle.theme_stage
    return {
        ThemeStage.EMERGING: 0.68,
        ThemeStage.ACCELERATING: 0.90,
        ThemeStage.BROADENING: 0.82,
        ThemeStage.SUPPLY_CONSTRAINED: 0.92,
        ThemeStage.CAPACITY_EXPANDING: 0.48,
        ThemeStage.CROWDED: 0.28,
        ThemeStage.OVERSUPPLIED: 0.10,
        ThemeStage.DECELERATING: 0.08,
        ThemeStage.NORMALIZING: 0.35,
        None: 0.50,
    }[stage]


@dataclass(frozen=True, slots=True)
class CausalOpportunityAssessment:
    candidate_identifier: str
    stage: CausalTransitionStage
    score: float
    transition_probability: float
    bottleneck_score: float
    pricing_gap: float
    forward_confirmation: float
    leadership_score: float
    mispriced_change_score: float
    successor_attention: float
    successor_sources: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    rationale: str
    policy_version: str = "causal-opportunity-rotation.v1"
    authorizes_capital: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(self.stage, CausalTransitionStage):
            raise TypeError("stage must be CausalTransitionStage")
        for name in (
            "score",
            "transition_probability",
            "pricing_gap",
            "forward_confirmation",
            "leadership_score",
            "successor_attention",
        ):
            object.__setattr__(self, name, _clip(getattr(self, name)))
        object.__setattr__(
            self,
            "bottleneck_score",
            round(max(-1.0, min(1.0, float(self.bottleneck_score))), 8),
        )
        object.__setattr__(
            self,
            "mispriced_change_score",
            round(max(-1.0, min(1.0, float(self.mispriced_change_score))), 8),
        )
        object.__setattr__(
            self,
            "successor_sources",
            tuple(dict.fromkeys(item.strip() for item in self.successor_sources if item.strip())),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            tuple(dict.fromkeys(item.strip() for item in self.evidence_identifiers if item.strip())),
        )
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")
        if self.authorizes_capital:
            raise ValueError("causal opportunity assessment cannot authorize capital")


def assess_causal_opportunity(
    bundle: ForwardIntelligenceBundle | None,
) -> CausalOpportunityAssessment | None:
    """Assess whether leadership is migrating toward this already-governed candidate."""

    if bundle is None:
        return None
    if not isinstance(bundle, ForwardIntelligenceBundle):
        raise TypeError("bundle must be ForwardIntelligenceBundle or None")

    successor, successor_evidence = theme_successor_score(bundle)
    sources = tuple(
        dict.fromkeys(
            diagnostic.split(" <- ", 1)[1].split(";", 1)[0].strip()
            for diagnostic in bundle.diagnostics
            if diagnostic.startswith("Theme successor rotation:") and " <- " in diagnostic
        )
    )
    leadership = assess_global_leadership_economics(bundle)
    mispricing = assess_mispriced_change(bundle)
    pricing_gap = 1.0 - _pricing_score(bundle)
    bottleneck = _bottleneck_score(bundle)
    trend = _trend_acceleration(bundle)
    theme = _theme_acceleration(bundle)
    constructive_mispricing = _clip(0.5 + 0.5 * mispricing.score)
    bottleneck_positive = _clip(0.5 + 0.5 * bottleneck)

    transition_probability = _clip(
        0.24 * successor
        + 0.18 * leadership.leadership_score
        + 0.18 * constructive_mispricing
        + 0.14 * leadership.forward_confirmation
        + 0.10 * pricing_gap
        + 0.08 * bottleneck_positive
        + 0.04 * trend
        + 0.04 * theme
    )
    score = _clip(
        0.30 * transition_probability
        + 0.20 * leadership.leadership_score
        + 0.20 * constructive_mispricing
        + 0.12 * pricing_gap
        + 0.10 * bottleneck_positive
        + 0.08 * max(trend, theme)
    )

    negative = mispricing.state in {
        MispricedChangeState.DETERIORATING,
        MispricedChangeState.VALUE_TRAP_RISK,
    } or bundle.trend_stage in {TrendStage.REVERSING, TrendStage.DETERIORATING}
    crowded = (
        bundle.trend_stage is TrendStage.CROWDED
        or bundle.theme_stage is ThemeStage.CROWDED
        or pricing_gap <= 0.20
    )
    if negative:
        stage = CausalTransitionStage.DECAYING
    elif crowded:
        stage = CausalTransitionStage.PRICED_OR_CROWDED
    elif successor > 0.0 and transition_probability >= 0.72:
        stage = CausalTransitionStage.ACCELERATING_SUCCESSOR
    elif successor > 0.0 and transition_probability >= 0.56:
        stage = CausalTransitionStage.EARLY_SUCCESSOR
    elif bundle.theme_stage in {ThemeStage.BROADENING, ThemeStage.SUPPLY_CONSTRAINED}:
        stage = CausalTransitionStage.BROADENING_SUCCESSOR
    elif leadership.leadership_score > 0.0:
        stage = CausalTransitionStage.SOURCE_LEADERSHIP
    else:
        stage = CausalTransitionStage.UNAVAILABLE

    # A decaying/priced chain should not receive a positive causal rank boost.
    if stage is CausalTransitionStage.DECAYING:
        score = min(score, 0.20)
    elif stage is CausalTransitionStage.PRICED_OR_CROWDED:
        score = min(score, 0.45)

    evidence = tuple(
        dict.fromkeys(
            (
                *successor_evidence,
                *leadership.evidence_identifiers,
                *mispricing.evidence_identifiers,
            )
        )
    )
    rationale = (
        f"Causal transition={stage.value}; probability={transition_probability:.0%}; "
        f"successor attention={successor:.0%}; bottleneck={bottleneck:+.2f}; "
        f"pricing gap={pricing_gap:.0%}; forward confirmation="
        f"{leadership.forward_confirmation:.0%}."
    )
    return CausalOpportunityAssessment(
        candidate_identifier=bundle.candidate_identifier,
        stage=stage,
        score=score,
        transition_probability=transition_probability,
        bottleneck_score=bottleneck,
        pricing_gap=pricing_gap,
        forward_confirmation=leadership.forward_confirmation,
        leadership_score=leadership.leadership_score,
        mispriced_change_score=mispricing.score,
        successor_attention=successor,
        successor_sources=sources,
        evidence_identifiers=evidence,
        rationale=rationale,
    )


__all__ = [
    "CausalOpportunityAssessment",
    "CausalTransitionStage",
    "assess_causal_opportunity",
]
