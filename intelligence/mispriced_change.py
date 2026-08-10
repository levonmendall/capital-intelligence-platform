"""Governed synthesis of mispriced change from existing point-in-time evidence.

The synthesis looks for *interaction* among persistent trend, future-state valuation,
fundamental acceleration, expectations, catalysts, regime fit, and payoff asymmetry.
It never creates a candidate, changes an investment threshold, sizes a position, issues
a CIO action, or authorizes real money. Its only numerical output is a tightly bounded
interaction adjustment supplied to the existing cross-asset forecast specialist, which
may challenge it before the existing CIO and construction gates run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from math import isfinite
from statistics import fmean

from intelligence.forward import (
    ForwardIntelligenceBundle,
    ForwardSignal,
    TrendStage,
)
from intelligence.forward_decision import (
    EvidenceAvailability,
    ForwardDecisionDimension,
)


_SYNTHESIS_PREFIX = "signal:mispriced-change:"
_EXPECTATIONS_PATTERN = re.compile(
    r"expected surprise\s+([+-]?\d+(?:\.\d+)?)%;\s*priced-in score\s+(\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)
_PRICED_IN_PATTERN = re.compile(
    r"Estimated benefit already priced\s*=\s*(\d+(?:\.\d+)?)%",
    re.IGNORECASE,
)


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


def _ratio(value: float) -> float:
    return _clip(value, 0.0, 1.0)


def _bounded(value: float) -> float:
    return _clip(value, -1.0, 1.0)


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


class MispricedChangeState(str, Enum):
    """Advisory classification of how price and changing economics interact."""

    STRONG = "strong_mispriced_change"
    CONSTRUCTIVE = "constructive_mispriced_change"
    MIXED = "mixed"
    MOMENTUM_ONLY = "momentum_only"
    VALUE_TRAP_RISK = "value_trap_risk"
    DETERIORATING = "deteriorating"
    INCOMPLETE = "incomplete_evidence"


@dataclass(frozen=True, slots=True)
class MispricedChangeComponent:
    """One independently traceable input to the synthesis."""

    name: str
    score: float
    confidence: float
    rationale: str
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("component name cannot be empty")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("component rationale cannot be empty")
        object.__setattr__(self, "score", _bounded(_finite(self.score, field_name="score")))
        object.__setattr__(
            self,
            "confidence",
            _ratio(_finite(self.confidence, field_name="confidence")),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _unique(self.evidence_identifiers),
        )


@dataclass(frozen=True, slots=True)
class MispricedChangeAssessment:
    """Advisory interaction thesis derived only from already-governed evidence."""

    candidate_identifier: str
    state: MispricedChangeState
    score: float
    confidence: float
    coverage: float
    evidence_independence: float
    interaction_return_adjustment: float
    components: tuple[MispricedChangeComponent, ...]
    thesis: str
    supporting_evidence: tuple[str, ...]
    contradictory_evidence: tuple[str, ...]
    missing_components: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    policy_version: str = "mispriced-change-synthesis.v1"
    advisory_only: bool = True
    authorizes_capital: bool = False
    real_money_authorized: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_identifier, str) or not self.candidate_identifier.strip():
            raise ValueError("candidate_identifier cannot be empty")
        if not isinstance(self.state, MispricedChangeState):
            raise TypeError("state must be MispricedChangeState")
        object.__setattr__(self, "score", _bounded(_finite(self.score, field_name="score")))
        for name in ("confidence", "coverage", "evidence_independence"):
            object.__setattr__(
                self,
                name,
                _ratio(_finite(getattr(self, name), field_name=name)),
            )
        adjustment = _finite(
            self.interaction_return_adjustment,
            field_name="interaction_return_adjustment",
        )
        if not -0.03 <= adjustment <= 0.03:
            raise ValueError("interaction_return_adjustment must stay within +/-3%")
        object.__setattr__(self, "interaction_return_adjustment", round(adjustment, 8))
        if not isinstance(self.components, tuple) or not all(
            isinstance(item, MispricedChangeComponent) for item in self.components
        ):
            raise TypeError("components must contain MispricedChangeComponent values")
        if not isinstance(self.thesis, str) or not self.thesis.strip():
            raise ValueError("thesis cannot be empty")
        for name in (
            "supporting_evidence",
            "contradictory_evidence",
            "missing_components",
            "evidence_identifiers",
        ):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                raise TypeError(f"{name} must be a tuple")
            object.__setattr__(self, name, _unique(value))
        if self.advisory_only is not True:
            raise ValueError("mispriced-change synthesis must remain advisory_only")
        if self.authorizes_capital is not False or self.real_money_authorized is not False:
            raise ValueError("mispriced-change synthesis cannot authorize capital")


_COMPONENT_WEIGHTS = {
    "trend_persistence": 0.18,
    "future_state_valuation": 0.18,
    "fundamental_acceleration": 0.18,
    "expectations_revision_gap": 0.15,
    "catalyst_support": 0.10,
    "regime_fit": 0.09,
    "payoff_asymmetry": 0.12,
}

_STAGE_SCORE = {
    TrendStage.BROADENING: 1.0,
    TrendStage.CONFIRMED: 0.80,
    TrendStage.EARLY: 0.50,
    TrendStage.MATURE: 0.15,
    TrendStage.CROWDED: -0.20,
    TrendStage.REVERSING: -0.80,
    TrendStage.DETERIORATING: -1.0,
}


def _base_signals(bundle: ForwardIntelligenceBundle) -> tuple[ForwardSignal, ...]:
    return tuple(
        item
        for item in bundle.signals
        if not item.identifier.startswith(_SYNTHESIS_PREFIX)
    )


def _find_signal(bundle: ForwardIntelligenceBundle, *needles: str) -> ForwardSignal | None:
    lowered = tuple(item.lower() for item in needles)
    for signal in _base_signals(bundle):
        haystack = f"{signal.identifier} {signal.name}".lower()
        if any(item in haystack for item in lowered):
            return signal
    return None


def _component(
    name: str,
    *,
    score: float,
    confidence: float,
    rationale: str,
    evidence_identifiers: tuple[str, ...],
) -> MispricedChangeComponent:
    return MispricedChangeComponent(
        name=name,
        score=score,
        confidence=confidence,
        rationale=rationale,
        evidence_identifiers=evidence_identifiers,
    )


def _trend_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    signal = _find_signal(bundle, "signal:trend:", "market trend")
    if signal is None:
        return None
    impact_score = _bounded(signal.expected_return_impact / 0.12)
    stage_score = _STAGE_SCORE.get(bundle.trend_stage, impact_score)
    score = _bounded(0.55 * impact_score + 0.45 * stage_score)
    return _component(
        "trend_persistence",
        score=score,
        confidence=signal.confidence,
        rationale=(
            f"Trend stage={None if bundle.trend_stage is None else bundle.trend_stage.value}; "
            f"standalone trend effect={signal.expected_return_impact:+.2%}."
        ),
        evidence_identifiers=signal.evidence_identifiers,
    )


def _business_signal(bundle: ForwardIntelligenceBundle) -> ForwardSignal | None:
    return _find_signal(bundle, "signal:business:", "strategic business economics")


def _fundamental_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    signal = _business_signal(bundle)
    if signal is None:
        return None
    return _component(
        "fundamental_acceleration",
        score=_bounded(signal.expected_return_impact / 0.15),
        confidence=signal.confidence,
        rationale=f"Strategic-business forward effect={signal.expected_return_impact:+.2%}.",
        evidence_identifiers=signal.evidence_identifiers,
    )


def _priced_in_share(signal: ForwardSignal) -> float | None:
    for value in signal.contradictory_evidence:
        match = _PRICED_IN_PATTERN.search(value)
        if match is not None:
            return _ratio(float(match.group(1)) / 100.0)
    return None


def _valuation_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    signal = _business_signal(bundle)
    if signal is None:
        return None
    priced_in = _priced_in_share(signal)
    if priced_in is None:
        return None
    # This deliberately evaluates how much of the *changing economics* appears priced,
    # rather than rewarding a low trailing multiple. Deteriorating economics are handled
    # separately by the fundamental/value-trap interaction state.
    return _component(
        "future_state_valuation",
        score=_bounded(1.0 - 2.0 * priced_in),
        confidence=_ratio(signal.confidence * 0.90),
        rationale=f"Estimated share of forward economic benefit already priced={priced_in:.0%}.",
        evidence_identifiers=signal.evidence_identifiers,
    )


def _expectations_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    direct = _find_signal(bundle, "market-expectations", "expectations gap")
    if direct is not None:
        return _component(
            "expectations_revision_gap",
            score=_bounded(direct.expected_return_impact / 0.10),
            confidence=direct.confidence,
            rationale=f"Direct expectations-gap effect={direct.expected_return_impact:+.2%}.",
            evidence_identifiers=direct.evidence_identifiers,
        )
    context = bundle.decision_context
    if context is None:
        return None
    assessment = next(
        (
            item
            for item in context.dimensions
            if item.dimension is ForwardDecisionDimension.EXPECTATIONS
        ),
        None,
    )
    if assessment is None or assessment.availability not in {
        EvidenceAvailability.AVAILABLE,
        EvidenceAvailability.PARTIAL,
    }:
        return None
    match = _EXPECTATIONS_PATTERN.search(assessment.summary)
    if match is None:
        return None
    expected_surprise = float(match.group(1)) / 100.0
    priced_in = _ratio(float(match.group(2)) / 100.0)
    surprise_score = _bounded(expected_surprise / 0.10)
    pricing_score = _bounded(1.0 - 2.0 * priced_in)
    return _component(
        "expectations_revision_gap",
        score=_bounded(0.70 * surprise_score + 0.30 * pricing_score),
        confidence=assessment.confidence,
        rationale=(
            f"Certified expected surprise={expected_surprise:+.2%}; "
            f"priced-in score={priced_in:.0%}."
        ),
        evidence_identifiers=assessment.evidence_identifiers,
    )


def _catalyst_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    context = bundle.decision_context
    if context is None or not context.catalysts:
        return None
    impacts = tuple(item.expected_return_impact for item in context.catalysts)
    score = _bounded(sum(impacts) / 0.15)
    identifiers = _unique(
        identifier
        for event in context.catalysts
        for identifier in event.evidence_identifiers
    )
    return _component(
        "catalyst_support",
        score=score,
        confidence=_ratio(0.55 + 0.08 * min(len(context.catalysts), 4)),
        rationale=f"Probability-weighted catalyst effect={sum(impacts):+.2%} across {len(impacts)} event(s).",
        evidence_identifiers=identifiers,
    )


def _regime_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    regime_signals = tuple(
        item
        for item in _base_signals(bundle)
        if item.identifier.startswith(("signal:monetary:", "signal:currency:", "signal:theme:"))
    )
    if not regime_signals:
        return None
    weights = tuple(max(0.05, item.confidence) for item in regime_signals)
    total = sum(weights)
    impact = sum(
        item.expected_return_impact * weight
        for item, weight in zip(regime_signals, weights)
    ) / total
    return _component(
        "regime_fit",
        score=_bounded(impact / 0.12),
        confidence=_ratio(fmean(item.confidence for item in regime_signals)),
        rationale=f"Confidence-weighted macro/structural transmission effect={impact:+.2%}.",
        evidence_identifiers=_unique(
            identifier
            for signal in regime_signals
            for identifier in signal.evidence_identifiers
        ),
    )


def _payoff_component(bundle: ForwardIntelligenceBundle) -> MispricedChangeComponent | None:
    context = bundle.decision_context
    distribution = None if context is None else context.return_distribution
    if distribution is None:
        return None
    downside = max(
        abs(distribution.tail_loss),
        abs(distribution.expected_max_drawdown),
        0.02,
    )
    asymmetry = _bounded((distribution.expected_return / downside) / 2.0)
    beat_cash = _bounded(2.0 * distribution.probability_beat_cash - 1.0)
    beat_best = _bounded(2.0 * distribution.probability_beat_best_alternative - 1.0)
    score = _bounded(0.40 * asymmetry + 0.30 * beat_cash + 0.30 * beat_best)
    return _component(
        "payoff_asymmetry",
        score=score,
        confidence=_ratio(0.45 + 0.45 * min(distribution.probability_positive, 1.0)),
        rationale=(
            f"Expected return={distribution.expected_return:+.2%}; "
            f"beat-cash={distribution.probability_beat_cash:.0%}; "
            f"beat-best-alternative={distribution.probability_beat_best_alternative:.0%}; "
            f"tail loss={distribution.tail_loss:.2%}."
        ),
        evidence_identifiers=distribution.evidence_identifiers,
    )


def _interaction_adjustment(
    state: MispricedChangeState,
    *,
    score: float,
    confidence: float,
) -> float:
    if state is MispricedChangeState.STRONG:
        raw = 0.03 * confidence * _clip(0.60 + 0.40 * max(score, 0.0), 0.0, 1.0)
    elif state is MispricedChangeState.CONSTRUCTIVE:
        raw = 0.015 * confidence * _clip(0.50 + 0.50 * max(score, 0.0), 0.0, 1.0)
    elif state is MispricedChangeState.VALUE_TRAP_RISK:
        raw = -0.02 * confidence
    elif state is MispricedChangeState.MOMENTUM_ONLY:
        raw = -0.01 * confidence
    elif state is MispricedChangeState.DETERIORATING:
        raw = -0.02 * confidence * _clip(0.50 + 0.50 * abs(min(score, 0.0)), 0.0, 1.0)
    else:
        raw = 0.0
    return _clip(raw, -0.03, 0.03)


def assess_mispriced_change(bundle: ForwardIntelligenceBundle) -> MispricedChangeAssessment:
    """Synthesize existing evidence without manufacturing a new standalone forecast."""

    if not isinstance(bundle, ForwardIntelligenceBundle):
        raise TypeError("bundle must be ForwardIntelligenceBundle")
    components = tuple(
        item
        for item in (
            _trend_component(bundle),
            _valuation_component(bundle),
            _fundamental_component(bundle),
            _expectations_component(bundle),
            _catalyst_component(bundle),
            _regime_component(bundle),
            _payoff_component(bundle),
        )
        if item is not None
    )
    by_name = {item.name: item for item in components}
    missing = tuple(name for name in _COMPONENT_WEIGHTS if name not in by_name)
    coverage = len(components) / len(_COMPONENT_WEIGHTS)
    available_weight = sum(_COMPONENT_WEIGHTS[item.name] for item in components)
    score = 0.0
    if available_weight > 0.0:
        score = sum(
            _COMPONENT_WEIGHTS[item.name] * item.score
            for item in components
        ) / available_weight
    score = _bounded(score)

    claims = tuple(
        identifier
        for item in components
        for identifier in item.evidence_identifiers
    )
    unique_identifiers = _unique(claims)
    independence = 0.0 if not claims else len(unique_identifiers) / len(claims)
    raw_confidence = (
        0.0
        if not components
        else sum(
            _COMPONENT_WEIGHTS[item.name] * item.confidence
            for item in components
        ) / available_weight
    )
    confidence = _ratio(
        raw_confidence
        * (0.55 + 0.45 * coverage)
        * (0.60 + 0.40 * independence)
    )

    trend = by_name.get("trend_persistence")
    valuation = by_name.get("future_state_valuation")
    fundamental = by_name.get("fundamental_acceleration")
    expectations = by_name.get("expectations_revision_gap")
    trend_score = None if trend is None else trend.score
    valuation_score = None if valuation is None else valuation.score
    fundamental_score = None if fundamental is None else fundamental.score
    expectations_score = None if expectations is None else expectations.score

    if (
        valuation_score is not None
        and valuation_score >= 0.35
        and (
            (fundamental_score is not None and fundamental_score <= -0.20)
            or (trend_score is not None and trend_score <= -0.20)
        )
    ):
        state = MispricedChangeState.VALUE_TRAP_RISK
    elif (
        trend_score is not None
        and trend_score >= 0.40
        and (
            fundamental_score is None
            or fundamental_score <= 0.10
            or valuation_score is None
            or valuation_score <= 0.0
        )
    ):
        state = MispricedChangeState.MOMENTUM_ONLY
    elif score <= -0.25 or (
        trend_score is not None
        and fundamental_score is not None
        and trend_score <= -0.40
        and fundamental_score < 0.0
    ):
        state = MispricedChangeState.DETERIORATING
    elif coverage < 0.43:
        state = MispricedChangeState.INCOMPLETE
    elif (
        score >= 0.35
        and coverage >= 0.57
        and independence >= 0.35
        and trend_score is not None
        and trend_score >= 0.25
        and valuation_score is not None
        and valuation_score >= 0.15
        and fundamental_score is not None
        and fundamental_score >= 0.20
        and (expectations_score is None or expectations_score > -0.25)
    ):
        state = MispricedChangeState.STRONG
    elif score >= 0.18 and coverage >= 0.50:
        state = MispricedChangeState.CONSTRUCTIVE
    else:
        state = MispricedChangeState.MIXED

    adjustment = _interaction_adjustment(
        state,
        score=score,
        confidence=confidence,
    )
    positive = tuple(
        f"{item.name}: {item.rationale} score={item.score:+.2f}"
        for item in components
        if item.score > 0.10
    )
    contradictory = tuple(
        f"{item.name}: {item.rationale} score={item.score:+.2f}"
        for item in components
        if item.score < -0.10
    )
    thesis = (
        f"{state.value}: cross-domain change score {score:+.2f}, "
        f"coverage {coverage:.0%}, evidence independence {independence:.0%}, "
        f"interaction adjustment {adjustment:+.2%}."
    )
    return MispricedChangeAssessment(
        candidate_identifier=bundle.candidate_identifier,
        state=state,
        score=score,
        confidence=confidence,
        coverage=coverage,
        evidence_independence=independence,
        interaction_return_adjustment=adjustment,
        components=components,
        thesis=thesis,
        supporting_evidence=positive or (thesis,),
        contradictory_evidence=contradictory,
        missing_components=missing,
        evidence_identifiers=unique_identifiers,
    )


def _signal_for_assessment(
    assessment: MispricedChangeAssessment,
    *,
    bundle: ForwardIntelligenceBundle,
) -> ForwardSignal | None:
    if not assessment.evidence_identifiers or abs(assessment.interaction_return_adjustment) < 1e-12:
        return None
    return ForwardSignal(
        identifier=f"{_SYNTHESIS_PREFIX}{assessment.candidate_identifier}",
        as_of=bundle.as_of,
        name="mispriced change synthesis",
        channels=("forecast",),
        expected_return_impact=assessment.interaction_return_adjustment,
        confidence=assessment.confidence,
        evidence=assessment.supporting_evidence,
        contradictory_evidence=assessment.contradictory_evidence,
        assumptions=(
            "The interaction among price trend, changing economics, expectations, and valuation remains valid through the decision horizon",
            "The synthesis adjustment represents only cross-signal interaction and does not re-count the underlying standalone expected-return effects",
        ),
        risks=(
            "A strong trend can be fully priced before reported fundamentals peak",
            "An apparently cheap future-state valuation can be a value trap when business or trend evidence deteriorates",
        ),
        change_conditions=(
            "Reassess when trend stage, priced-in assumptions, fundamental trajectory, expectations, catalysts, regime evidence, or payoff distribution changes",
        ),
        evidence_identifiers=assessment.evidence_identifiers,
    )


def enrich_bundle_with_mispriced_change(
    bundle: ForwardIntelligenceBundle,
) -> ForwardIntelligenceBundle:
    """Attach one idempotent advisory interaction signal to an existing bundle."""

    assessment = assess_mispriced_change(bundle)
    base_signals = _base_signals(bundle)
    signal = _signal_for_assessment(assessment, bundle=bundle)
    signals = base_signals if signal is None else (*base_signals, signal)
    diagnostic = (
        "Mispriced change: "
        f"state={assessment.state.value}; score={assessment.score:+.2f}; "
        f"coverage={assessment.coverage:.0%}; independence={assessment.evidence_independence:.0%}; "
        f"interaction={assessment.interaction_return_adjustment:+.2%}"
    )
    if assessment.missing_components:
        diagnostic += "; unavailable=" + ",".join(assessment.missing_components)
    diagnostics = tuple(
        dict.fromkeys(
            item
            for item in bundle.diagnostics
            if not item.startswith("Mispriced change:")
        )
    ) + (diagnostic,)
    versions = tuple(
        dict.fromkeys((*bundle.model_versions, assessment.policy_version))
    )
    return replace(
        bundle,
        signals=tuple(signals),
        diagnostics=diagnostics,
        model_versions=versions,
    )


__all__ = [
    "MispricedChangeAssessment",
    "MispricedChangeComponent",
    "MispricedChangeState",
    "assess_mispriced_change",
    "enrich_bundle_with_mispriced_change",
]
