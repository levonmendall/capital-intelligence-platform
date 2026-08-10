"""Corroborate global market leadership with governed forward economics.

Raw bull-market radar output stays research-only. This layer adds a small interaction
term only when price leadership agrees with independently governed forward evidence.
It cannot create a candidate, authorize capital, size a position, or bypass the CIO.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite

from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal, TrendStage
from intelligence.mispriced_change import MispricedChangeState, assess_mispriced_change

_RADAR_PREFIX = "signal:global-opportunity-radar:"
_ECONOMIC_PREFIX = "signal:global-leadership-economics:"
_POLICY_VERSION = "global-leadership-economics.v1"


def _clip(value: float, low: float, high: float) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError("global leadership values must be finite")
    return round(max(low, min(high, number)), 8)


class GlobalLeadershipState(str, Enum):
    UNAVAILABLE = "unavailable"
    UNCONFIRMED = "unconfirmed"
    EMERGING = "emerging"
    LEADING = "leading"
    MATURE = "mature"
    CROWDED = "crowded"
    DETERIORATING = "deteriorating"


@dataclass(frozen=True, slots=True)
class GlobalLeadershipEconomicAssessment:
    candidate_identifier: str
    state: GlobalLeadershipState
    leadership_score: float
    forward_confirmation: float
    interaction_return_adjustment: float
    confidence: float
    mispriced_change_state: str
    mispriced_change_score: float
    evidence_identifiers: tuple[str, ...]
    rationale: str
    policy_version: str = _POLICY_VERSION
    advisory_only: bool = True
    authorizes_capital: bool = False

    def __post_init__(self) -> None:
        if not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(self.state, GlobalLeadershipState):
            raise TypeError("state must be GlobalLeadershipState")
        for name in ("leadership_score", "forward_confirmation", "confidence"):
            object.__setattr__(self, name, _clip(getattr(self, name), 0.0, 1.0))
        object.__setattr__(
            self,
            "mispriced_change_score",
            _clip(self.mispriced_change_score, -1.0, 1.0),
        )
        object.__setattr__(
            self,
            "interaction_return_adjustment",
            _clip(self.interaction_return_adjustment, -0.01, 0.01),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            tuple(
                dict.fromkeys(
                    str(item).strip()
                    for item in self.evidence_identifiers
                    if str(item).strip()
                )
            ),
        )
        if not self.rationale.strip():
            raise ValueError("rationale cannot be empty")


def _radar_signal(bundle: ForwardIntelligenceBundle) -> ForwardSignal | None:
    return next(
        (item for item in bundle.signals if item.identifier.startswith(_RADAR_PREFIX)),
        None,
    )


def _leadership_score(signal: ForwardSignal | None) -> float:
    if signal is None:
        return 0.0
    # The radar publishes confidence = 45% + 45% * score.
    return _clip((signal.confidence - 0.45) / 0.45, 0.0, 1.0)


def _forward_confirmation(bundle: ForwardIntelligenceBundle) -> float:
    impacts = tuple(
        item.expected_return_impact * item.confidence
        for item in bundle.signals
        if not item.identifier.startswith(_RADAR_PREFIX)
        and not item.identifier.startswith(_ECONOMIC_PREFIX)
        and not item.identifier.startswith("signal:mispriced-change:")
    )
    if not impacts:
        return 0.5
    return _clip(0.5 + (sum(impacts) / len(impacts)) / 0.10, 0.0, 1.0)


def assess_global_leadership_economics(
    bundle: ForwardIntelligenceBundle,
) -> GlobalLeadershipEconomicAssessment:
    if not isinstance(bundle, ForwardIntelligenceBundle):
        raise TypeError("bundle must be ForwardIntelligenceBundle")
    radar = _radar_signal(bundle)
    leadership = _leadership_score(radar)
    confirmation = _forward_confirmation(bundle)
    clean_bundle = replace(
        bundle,
        signals=tuple(
            item
            for item in bundle.signals
            if not item.identifier.startswith(_ECONOMIC_PREFIX)
        ),
    )
    mispricing = assess_mispriced_change(clean_bundle)
    trend = bundle.trend_stage
    negative = mispricing.state in {
        MispricedChangeState.DETERIORATING,
        MispricedChangeState.VALUE_TRAP_RISK,
    }
    constructive = mispricing.state in {
        MispricedChangeState.STRONG,
        MispricedChangeState.CONSTRUCTIVE,
    }

    if radar is None:
        state = GlobalLeadershipState.UNAVAILABLE
    elif negative and trend in {TrendStage.REVERSING, TrendStage.DETERIORATING}:
        state = GlobalLeadershipState.DETERIORATING
    elif trend is TrendStage.CROWDED:
        state = GlobalLeadershipState.CROWDED
    elif trend is TrendStage.MATURE:
        state = GlobalLeadershipState.MATURE
    elif trend in {TrendStage.EARLY, TrendStage.BROADENING} and constructive and confirmation >= 0.50:
        state = GlobalLeadershipState.EMERGING
    elif trend is TrendStage.CONFIRMED and constructive and confirmation >= 0.50:
        state = GlobalLeadershipState.LEADING
    else:
        state = GlobalLeadershipState.UNCONFIRMED

    if state in {GlobalLeadershipState.EMERGING, GlobalLeadershipState.LEADING}:
        strength = _clip((mispricing.score + 1.0) / 2.0, 0.0, 1.0)
        interaction = min(0.01, 0.01 * leadership * strength * max(0.50, confirmation))
    elif state is GlobalLeadershipState.DETERIORATING:
        interaction = -min(
            0.01,
            0.01 * max(leadership, 0.50) * max(0.50, 1.0 - confirmation),
        )
    else:
        interaction = 0.0

    confidence = _clip(
        0.45 * (0.0 if radar is None else radar.confidence)
        + 0.35 * mispricing.confidence
        + 0.20 * confirmation,
        0.0,
        1.0,
    )
    evidence = tuple(
        dict.fromkeys(
            (
                *(() if radar is None else radar.evidence_identifiers),
                *mispricing.evidence_identifiers,
                *tuple(
                    identifier
                    for signal in bundle.signals
                    if not signal.identifier.startswith(_ECONOMIC_PREFIX)
                    for identifier in signal.evidence_identifiers
                ),
            )
        )
    )
    rationale = (
        f"Global leadership={state.value}; leadership score={leadership:.0%}; "
        f"mispriced-change={mispricing.state.value}; forward confirmation={confirmation:.0%}; "
        f"interaction adjustment={interaction:+.2%}."
    )
    return GlobalLeadershipEconomicAssessment(
        candidate_identifier=bundle.candidate_identifier,
        state=state,
        leadership_score=leadership,
        forward_confirmation=confirmation,
        interaction_return_adjustment=interaction,
        confidence=confidence,
        mispriced_change_state=mispricing.state.value,
        mispriced_change_score=mispricing.score,
        evidence_identifiers=evidence,
        rationale=rationale,
    )


def enrich_bundle_with_global_leadership_economics(
    bundle: ForwardIntelligenceBundle,
) -> ForwardIntelligenceBundle:
    """Add one idempotent, corroborated leadership interaction signal."""

    assessment = assess_global_leadership_economics(bundle)
    base = tuple(
        item for item in bundle.signals if not item.identifier.startswith(_ECONOMIC_PREFIX)
    )
    signal = None
    if assessment.evidence_identifiers and abs(assessment.interaction_return_adjustment) >= 1e-12:
        signal = ForwardSignal(
            identifier=f"{_ECONOMIC_PREFIX}{bundle.candidate_identifier}",
            as_of=bundle.as_of,
            name="corroborated global leadership economics",
            channels=("forecast",),
            expected_return_impact=assessment.interaction_return_adjustment,
            confidence=assessment.confidence,
            evidence=(assessment.rationale,),
            contradictory_evidence=(),
            assumptions=(
                "Observed leadership and independently governed forward economics remain aligned through the decision horizon",
                "The interaction term does not re-count standalone trend, fundamental, macro, expectations, or valuation effects",
            ),
            risks=(
                "Leadership can reverse before slower fundamental evidence updates",
                "A crowded or mature bull market can remain strong while its forward payoff deteriorates",
            ),
            change_conditions=(
                "Reassess when leadership, expectations, fundamentals, catalysts, valuation, positioning, or cross-asset confirmation changes materially",
            ),
            evidence_identifiers=assessment.evidence_identifiers,
        )
    diagnostics = tuple(
        item
        for item in bundle.diagnostics
        if not item.startswith("Global leadership economics:")
    ) + ("Global leadership economics: " + assessment.rationale,)
    return replace(
        bundle,
        signals=base if signal is None else (*base, signal),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        model_versions=tuple(dict.fromkeys((*bundle.model_versions, _POLICY_VERSION))),
    )


__all__ = [
    "GlobalLeadershipEconomicAssessment",
    "GlobalLeadershipState",
    "assess_global_leadership_economics",
    "enrich_bundle_with_global_leadership_economics",
]
