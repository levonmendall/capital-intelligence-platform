"""Point-in-time capital-flow and market-expectations intelligence.

The engines in this module answer two investor questions for an already governed
candidate:

* where is marginal capital moving and how durable is that movement; and
* how different is the evidence-backed outlook from the outcome implied by recent
  price, positioning, and volatility evidence.

They do not create instruments, authorize capital, construct a portfolio, execute an
order, or add a seventh specialist.  Their signals enrich the existing Market,
Cross-Asset Forecast, and Fundamental & Valuation specialists through the canonical
``ForwardIntelligenceBundle`` contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from math import isfinite, sqrt
from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

from cio.models import CandidateDecisionRecord
from committee.specialists import MarketSpecialistContext
from intelligence.forward import (
    ForwardIntelligenceBundle,
    ForwardScenario,
    ForwardSignal,
)
from intelligence.forward_decision import (
    DecisionTiming,
    DecisionTimingPosture,
    EvidenceAvailability,
    ForwardDecisionContext,
    ForwardDecisionDimension,
    ForwardDimensionAssessment,
    ThesisMonitor,
    applicable_dimensions,
    build_forward_decision_context,
)
from intelligence.forward_research import (
    ForwardResearchEvidence,
    enrich_forward_decision_context,
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=0.0, maximum=1.0)


def _bounded(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, minimum=-1.0, maximum=1.0)


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return round(max(low, min(high, float(value))), 8)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


class CapitalFlowState(str, Enum):
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    SHORT_COVERING = "short_covering"
    CROWDED_ADVANCE = "crowded_advance"
    CROWDED_DECLINE = "crowded_decline"
    ROTATION = "rotation"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class CapitalFlowObservation:
    identifier: str
    symbol: str
    as_of: datetime
    recent_volume_impulse: float
    signed_dollar_flow: float
    accumulation_distribution: float
    price_volume_confirmation: float
    persistence: float
    short_trend: float
    medium_trend: float
    volatility: float
    crowding: float
    short_covering_likelihood: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        object.__setattr__(self, "symbol", _text(self.symbol, field_name="symbol").upper())
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "recent_volume_impulse",
            "signed_dollar_flow",
            "accumulation_distribution",
            "price_volume_confirmation",
            "short_trend",
            "medium_trend",
        ):
            object.__setattr__(
                self,
                field_name,
                _bounded(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "persistence",
            "volatility",
            "crowding",
            "short_covering_likelihood",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class CapitalFlowAssessment:
    state: CapitalFlowState
    direction: float
    persistence: float
    confidence: float
    expected_return_impact: float
    reversal_risk: float
    signal: ForwardSignal
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.state, CapitalFlowState):
            raise TypeError("state must be CapitalFlowState")
        object.__setattr__(self, "direction", _bounded(self.direction, field_name="direction"))
        for field_name in ("persistence", "confidence", "reversal_risk"):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "expected_return_impact",
            _number(
                self.expected_return_impact,
                field_name="expected_return_impact",
                minimum=-0.15,
                maximum=0.15,
            ),
        )
        if not isinstance(self.signal, ForwardSignal):
            raise TypeError("signal must be ForwardSignal")
        object.__setattr__(
            self,
            "diagnostics",
            _texts(self.diagnostics, field_name="diagnostics", minimum=1),
        )


class CapitalFlowEngine:
    """Infer point-in-time flow state from price and dollar-volume behavior.

    This free-data implementation is intentionally a market-flow proxy.  It does not
    claim knowledge of complete ETF subscriptions, dealer inventory, futures
    positioning, or cross-border transactions when those feeds are unavailable.
    """

    version = "capital-flow-positioning.v1-market-proxy"

    @staticmethod
    def observe(
        *,
        symbol: str,
        as_of: datetime,
        rows: Sequence[Mapping[str, object]],
        evidence_identifiers: tuple[str, ...],
    ) -> CapitalFlowObservation:
        timestamp = _aware(as_of, field_name="as_of")
        normalized_symbol = _text(symbol, field_name="symbol").upper()
        if len(rows) < 80:
            raise ValueError("capital-flow observation requires at least 80 daily rows")
        closes: list[float] = []
        volumes: list[float] = []
        material: list[dict[str, object]] = []
        for item in rows:
            close = _number(item.get("c"), field_name="close", minimum=0.00000001)
            volume = _number(item.get("v"), field_name="volume", minimum=0.0)
            closes.append(close)
            volumes.append(volume)
            material.append(
                {
                    "t": str(item.get("t")),
                    "c": round(close, 10),
                    "v": round(volume, 4),
                }
            )
        returns = [
            closes[index] / closes[index - 1] - 1.0
            for index in range(1, len(closes))
            if closes[index - 1] > 0.0
        ]
        dollar_volume = [close * volume for close, volume in zip(closes, volumes, strict=True)]
        recent_volume = fmean(dollar_volume[-20:])
        prior_volume = fmean(dollar_volume[-80:-20])
        volume_impulse = _clip(
            (recent_volume / max(prior_volume, 1.0) - 1.0) / 2.0,
            -1.0,
            1.0,
        )
        recent_returns = returns[-20:]
        recent_dollar_volume = dollar_volume[-20:]
        signed_numerator = sum(
            (1.0 if value > 0.0 else -1.0 if value < 0.0 else 0.0) * flow
            for value, flow in zip(recent_returns, recent_dollar_volume[-len(recent_returns):], strict=True)
        )
        signed_flow = _clip(
            signed_numerator / max(sum(recent_dollar_volume[-len(recent_returns):]), 1.0),
            -1.0,
            1.0,
        )
        weighted_return = sum(
            value * flow
            for value, flow in zip(recent_returns, recent_dollar_volume[-len(recent_returns):], strict=True)
        ) / max(sum(recent_dollar_volume[-len(recent_returns):]), 1.0)
        ordinary_return = fmean(recent_returns) if recent_returns else 0.0
        accumulation_distribution = _clip(
            signed_flow * 0.70 + _clip(weighted_return * 50.0) * 0.30
        )
        short_trend = closes[-1] / closes[-21] - 1.0
        medium_trend = closes[-1] / closes[-64] - 1.0
        direction = 1.0 if short_trend > 0.0 else -1.0 if short_trend < 0.0 else 0.0
        persistence = sum(
            1
            for value in recent_returns
            if (value > 0.0 and direction > 0.0) or (value < 0.0 and direction < 0.0)
        ) / max(len(recent_returns), 1)
        volatility = min(1.0, (pstdev(returns[-63:]) * sqrt(252.0)) if len(returns) >= 2 else 0.0)
        confirmation = _clip(
            0.50 * (1.0 if short_trend * signed_flow > 0.0 else -1.0)
            + 0.30 * accumulation_distribution
            + 0.20 * volume_impulse
        )
        trend_strength = min(1.0, abs(short_trend) / max(volatility / sqrt(12.0), 0.02))
        crowding = _clip(
            0.45 * trend_strength
            + 0.30 * max(0.0, volume_impulse)
            + 0.25 * max(0.0, persistence - 0.55) / 0.45,
            0.0,
            1.0,
        )
        short_covering = _clip(
            0.35 * max(0.0, short_trend) / max(abs(short_trend) + 0.05, 0.05)
            + 0.30 * max(0.0, -medium_trend) / max(abs(medium_trend) + 0.05, 0.05)
            + 0.20 * max(0.0, volume_impulse)
            + 0.15 * volatility,
            0.0,
            1.0,
        )
        derived_identifier = (
            f"derived-capital-flow:{normalized_symbol}:{timestamp.isoformat()}:"
            f"{_digest(material[-80:])}"
        )
        return CapitalFlowObservation(
            identifier=derived_identifier,
            symbol=normalized_symbol,
            as_of=timestamp,
            recent_volume_impulse=volume_impulse,
            signed_dollar_flow=signed_flow,
            accumulation_distribution=accumulation_distribution,
            price_volume_confirmation=confirmation,
            persistence=persistence,
            short_trend=_clip(short_trend),
            medium_trend=_clip(medium_trend),
            volatility=volatility,
            crowding=crowding,
            short_covering_likelihood=short_covering,
            evidence_identifiers=tuple(
                dict.fromkeys((*evidence_identifiers, derived_identifier))
            ),
        )

    def analyze(self, observation: CapitalFlowObservation) -> CapitalFlowAssessment:
        direction = _clip(
            0.35 * observation.signed_dollar_flow
            + 0.25 * observation.accumulation_distribution
            + 0.20 * observation.price_volume_confirmation
            + 0.10 * observation.short_trend
            + 0.10 * observation.medium_trend
        )
        if observation.short_covering_likelihood >= 0.65 and observation.short_trend > 0.0:
            state = CapitalFlowState.SHORT_COVERING
        elif direction >= 0.25 and observation.crowding >= 0.75:
            state = CapitalFlowState.CROWDED_ADVANCE
        elif direction <= -0.25 and observation.crowding >= 0.75:
            state = CapitalFlowState.CROWDED_DECLINE
        elif direction >= 0.20 and observation.persistence >= 0.50:
            state = CapitalFlowState.ACCUMULATION
        elif direction <= -0.20 and observation.persistence >= 0.50:
            state = CapitalFlowState.DISTRIBUTION
        elif observation.short_trend * observation.medium_trend < 0.0:
            state = CapitalFlowState.ROTATION
        else:
            state = CapitalFlowState.NEUTRAL
        reversal_risk = _clip(
            0.55 * observation.crowding
            + 0.25 * observation.short_covering_likelihood
            + 0.20 * max(0.0, -observation.price_volume_confirmation * (1.0 if direction >= 0.0 else -1.0)),
            0.0,
            1.0,
        )
        persistence_quality = abs(observation.persistence - 0.50) * 2.0
        confidence = _clip(
            0.38
            + 0.22 * abs(direction)
            + 0.18 * persistence_quality
            + 0.12 * abs(observation.price_volume_confirmation)
            + 0.10 * min(1.0, abs(observation.recent_volume_impulse)),
            0.0,
            0.82,
        )
        raw_impact = (
            0.045 * direction
            + 0.020 * observation.price_volume_confirmation
            + 0.015 * (observation.persistence - 0.50) * (1.0 if direction >= 0.0 else -1.0)
        )
        if state is CapitalFlowState.SHORT_COVERING:
            raw_impact *= 0.35
        if state in {CapitalFlowState.CROWDED_ADVANCE, CapitalFlowState.CROWDED_DECLINE}:
            raw_impact *= max(0.25, 1.0 - 0.75 * reversal_risk)
        impact = _clip(raw_impact, -0.10, 0.10)
        diagnostics = (
            f"Flow state={state.value}",
            f"Signed dollar flow={observation.signed_dollar_flow:+.2f}",
            f"Volume impulse={observation.recent_volume_impulse:+.2f}",
            f"Persistence={observation.persistence:.0%}",
            f"Crowding={observation.crowding:.0%}",
            f"Short-covering likelihood={observation.short_covering_likelihood:.0%}",
        )
        signal = ForwardSignal(
            identifier=f"signal:capital-flow:{observation.identifier}",
            as_of=observation.as_of,
            name=f"{state.value.replace('_', ' ')} capital-flow proxy",
            channels=("market", "forecast"),
            expected_return_impact=impact,
            confidence=confidence,
            evidence=diagnostics,
            contradictory_evidence=(
                "Free-data price and volume reveal market participation but not complete ETF creations, dealer inventory, futures positioning, or cross-border ownership flows",
                f"Reversal risk={reversal_risk:.0%}",
            ),
            assumptions=(
                "Recent signed dollar volume and price-volume confirmation remain representative through the decision horizon",
                "Corporate actions and venue coverage do not materially distort the observed flow proxy",
            ),
            risks=(
                "Short covering can resemble durable accumulation",
                "Crowded flows can reverse before fundamental evidence changes",
            ),
            change_conditions=(
                "Reassess after a material reversal in signed dollar flow, volume impulse, price-volume confirmation, persistence, or crowding",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )
        return CapitalFlowAssessment(
            state=state,
            direction=direction,
            persistence=observation.persistence,
            confidence=confidence,
            expected_return_impact=impact,
            reversal_risk=reversal_risk,
            signal=signal,
            diagnostics=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class MarketExpectationsObservation:
    identifier: str
    candidate_identifier: str
    as_of: datetime
    evidence_backed_outlook: float
    market_implied_proxy: float
    expected_surprise: float
    priced_in_score: float
    forecast_uncertainty: float
    price_sensitivity: float
    catalyst_strength: float
    flow_confirmation: float
    crowding: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "candidate_identifier"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _aware(self.as_of, field_name="as_of")
        for field_name in (
            "evidence_backed_outlook",
            "market_implied_proxy",
            "expected_surprise",
            "flow_confirmation",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=-1.0,
                    maximum=2.0,
                ),
            )
        for field_name in (
            "priced_in_score",
            "forecast_uncertainty",
            "price_sensitivity",
            "catalyst_strength",
            "crowding",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class MarketExpectationsAssessment:
    expected_surprise: float
    priced_in_score: float
    confidence: float
    expected_return_impact: float
    signal: ForwardSignal
    scenarios: tuple[ForwardScenario, ...]
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expected_surprise",
            _number(self.expected_surprise, field_name="expected_surprise", minimum=-1.0, maximum=2.0),
        )
        for field_name in ("priced_in_score", "confidence"):
            object.__setattr__(self, field_name, _ratio(getattr(self, field_name), field_name=field_name))
        object.__setattr__(
            self,
            "expected_return_impact",
            _number(
                self.expected_return_impact,
                field_name="expected_return_impact",
                minimum=-0.15,
                maximum=0.15,
            ),
        )
        if not isinstance(self.signal, ForwardSignal):
            raise TypeError("signal must be ForwardSignal")
        if not isinstance(self.scenarios, tuple) or not all(
            isinstance(item, ForwardScenario) for item in self.scenarios
        ):
            raise TypeError("scenarios must contain ForwardScenario values")
        object.__setattr__(self, "diagnostics", _texts(self.diagnostics, field_name="diagnostics", minimum=1))


class MarketExpectationsEngine:
    """Compare evidence-backed outlook with a disclosed market-pricing proxy."""

    version = "market-expectations-gap.v1-pilot-proxy"

    @staticmethod
    def observe(
        *,
        candidate: object,
        features: object,
        flow: CapitalFlowAssessment,
    ) -> MarketExpectationsObservation:
        identifier = _text(getattr(candidate, "identifier"), field_name="candidate identifier")
        as_of = _aware(getattr(candidate, "as_of"), field_name="candidate as_of")
        base = float(getattr(candidate, "base_case_return"))
        probability = float(getattr(candidate, "probability_of_success"))
        evidence_outlook = _clip(base * (0.70 + 0.60 * (probability - 0.50)), -0.80, 1.50)
        momentum = float(getattr(features, "momentum"))
        six_month = float(getattr(features, "six_month_return"))
        twelve_month = float(getattr(features, "twelve_month_return"))
        market_implied = _clip(
            0.35 * momentum
            + 0.25 * six_month
            + 0.25 * twelve_month
            + 0.15 * flow.expected_return_impact,
            -0.80,
            1.50,
        )
        uncertainty = _clip(
            0.35 * min(1.0, float(getattr(features, "annualized_volatility")))
            + 0.25 * (1.0 - flow.confidence)
            + 0.20 * flow.reversal_risk
            + 0.20 * abs(float(getattr(features, "rolling_annual_median")) - base),
            0.05,
            1.0,
        )
        surprise = _clip(evidence_outlook - market_implied, -1.0, 2.0)
        scaled_gap = surprise / max(0.10, 2.0 * uncertainty)
        priced_in = _clip(0.50 - scaled_gap, 0.0, 1.0)
        sensitivity = _clip(
            0.35
            + 0.35 * min(1.0, float(getattr(features, "annualized_volatility")))
            + 0.20 * abs(flow.direction)
            + 0.10 * flow.persistence,
            0.0,
            1.0,
        )
        catalysts = tuple(getattr(candidate, "primary_catalysts", ()) or ())
        catalyst_strength = _clip(
            0.30
            + 0.10 * min(3, len(catalysts))
            + 0.25 * float(getattr(getattr(candidate, "evidence_quality"), "score")),
            0.0,
            1.0,
        )
        derived_identifier = (
            f"derived-market-expectations:{identifier}:{as_of.isoformat()}:"
            f"{_digest({'base': base, 'probability': probability, 'market_implied': market_implied, 'flow': flow.signal.identifier})}"
        )
        evidence_ids = tuple(
            dict.fromkeys(
                (
                    *tuple(getattr(candidate, "evidence_identifiers", ()) or ()),
                    *flow.signal.evidence_identifiers,
                    derived_identifier,
                )
            )
        )
        return MarketExpectationsObservation(
            identifier=derived_identifier,
            candidate_identifier=identifier,
            as_of=as_of,
            evidence_backed_outlook=evidence_outlook,
            market_implied_proxy=market_implied,
            expected_surprise=surprise,
            priced_in_score=priced_in,
            forecast_uncertainty=uncertainty,
            price_sensitivity=sensitivity,
            catalyst_strength=catalyst_strength,
            flow_confirmation=flow.direction,
            crowding=flow.reversal_risk,
            evidence_identifiers=evidence_ids,
        )

    def analyze(self, observation: MarketExpectationsObservation) -> MarketExpectationsAssessment:
        impact = _clip(
            observation.expected_surprise
            * observation.price_sensitivity
            * (1.0 - 0.55 * observation.forecast_uncertainty)
            * (1.0 - 0.45 * observation.crowding)
            * 0.20
            + 0.015 * observation.flow_confirmation,
            -0.12,
            0.12,
        )
        confidence = _clip(
            0.36
            + 0.20 * observation.catalyst_strength
            + 0.16 * (1.0 - observation.forecast_uncertainty)
            + 0.12 * abs(observation.flow_confirmation)
            + 0.10 * abs(observation.expected_surprise)
            + 0.06 * (1.0 - observation.crowding),
            0.0,
            0.78,
        )
        diagnostics = (
            f"Evidence-backed outlook={observation.evidence_backed_outlook:+.2%}",
            f"Market-implied proxy={observation.market_implied_proxy:+.2%}",
            f"Expected surprise={observation.expected_surprise:+.2%}",
            f"Estimated priced-in score={observation.priced_in_score:.0%}",
            f"Forecast uncertainty={observation.forecast_uncertainty:.0%}",
            f"Price sensitivity={observation.price_sensitivity:.0%}",
        )
        signal = ForwardSignal(
            identifier=f"signal:market-expectations:{observation.identifier}",
            as_of=observation.as_of,
            name="market expectations gap",
            channels=("market", "forecast", "fundamental"),
            expected_return_impact=impact,
            confidence=confidence,
            evidence=diagnostics,
            contradictory_evidence=(
                "The pilot market-implied estimate is derived from point-in-time price, volatility, distribution, and flow evidence rather than a complete consensus, options, rates, credit, and fund-flow stack",
                f"Crowding or reversal risk={observation.crowding:.0%}",
            ),
            assumptions=(
                "The evidence-backed central outlook and recent market-pricing proxy are comparable over the candidate horizon",
                "The estimated catalyst and price sensitivity remain relevant through implementation",
            ),
            risks=(
                "A correct fundamental outlook can still lose money when expectations were understated or timing was wrong",
                "Recent price action can embed information not yet present in disclosed fundamentals",
            ),
            change_conditions=(
                "Reassess after a material change in the candidate outlook, rolling distribution, volatility, flow confirmation, valuation, or catalyst timing",
            ),
            evidence_identifiers=observation.evidence_identifiers,
        )
        uncertainty = observation.forecast_uncertainty
        scenarios = (
            ForwardScenario(
                label="bull",
                return_delta=_clip(max(0.0, impact) + 0.05 * max(0.0, observation.expected_surprise), 0.0, 0.25),
                probability_delta=_clip(0.05 * max(0.0, observation.flow_confirmation), 0.0, 0.08),
                path_drawdown_delta=0.0,
                rationale="Positive surprise, supportive flow, and catalyst realization cause price to converge toward the evidence-backed outlook.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="base",
                return_delta=impact,
                probability_delta=0.0,
                path_drawdown_delta=_clip(-0.04 * uncertainty, -0.10, 0.0),
                rationale="The expectations gap closes partially while uncertainty and already-priced information limit the move.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
            ForwardScenario(
                label="bear",
                return_delta=_clip(min(0.0, impact) - 0.10 * uncertainty - 0.05 * observation.crowding, -0.25, 0.0),
                probability_delta=_clip(0.06 * max(uncertainty, observation.crowding), 0.0, 0.10),
                path_drawdown_delta=_clip(-0.08 - 0.12 * max(uncertainty, observation.crowding), -0.25, 0.0),
                rationale="The market had superior information, the catalyst fails, or crowded positioning reverses before the outlook materializes.",
                evidence_identifiers=observation.evidence_identifiers,
            ),
        )
        return MarketExpectationsAssessment(
            expected_surprise=observation.expected_surprise,
            priced_in_score=observation.priced_in_score,
            confidence=confidence,
            expected_return_impact=impact,
            signal=signal,
            scenarios=scenarios,
            diagnostics=diagnostics,
        )



def build_predictive_forward_decision_context(
    *,
    candidate: object,
    flow: CapitalFlowAssessment,
    expectations: MarketExpectationsAssessment,
    market: MarketSpecialistContext,
    existing_forward_intelligence: ForwardIntelligenceBundle | None,
) -> ForwardDecisionContext:
    """Map certified current evidence into a truthful common v2 packet."""
    candidate_identifier = _text(getattr(candidate, "identifier"), field_name="candidate identifier")
    as_of = _aware(getattr(candidate, "as_of"), field_name="candidate as_of")
    asset_class = getattr(getattr(candidate, "instrument"), "asset_class")
    candidate_ids = tuple(getattr(candidate, "evidence_identifiers", ()) or ())
    if not candidate_ids:
        raise ValueError("forward decision context requires candidate evidence identifiers")
    evidence_quality = float(getattr(getattr(candidate, "evidence_quality"), "score"))
    existing_signals = () if existing_forward_intelligence is None else existing_forward_intelligence.signals

    def from_signals(dimension, *, summary, channels=(), name_terms=()):
        selected = tuple(
            signal for signal in existing_signals
            if (channels and any(channel in signal.channels for channel in channels))
            or (name_terms and any(term in f"{signal.name} {signal.identifier}".lower() for term in name_terms))
        )
        identifiers = tuple(dict.fromkeys(identifier for signal in selected for identifier in signal.evidence_identifiers))
        if not selected or not identifiers:
            return None
        return ForwardDimensionAssessment(
            dimension=dimension,
            availability=EvidenceAvailability.PARTIAL,
            summary=summary,
            confidence=min(signal.confidence for signal in selected),
            evidence=tuple(dict.fromkeys(item for signal in selected for item in signal.evidence)),
            contradictory_evidence=tuple(dict.fromkeys(item for signal in selected for item in signal.contradictory_evidence)),
            assumptions=tuple(dict.fromkeys(item for signal in selected for item in signal.assumptions)),
            risks=tuple(dict.fromkeys(item for signal in selected for item in signal.risks)),
            change_conditions=tuple(dict.fromkeys(item for signal in selected for item in signal.change_conditions)),
            evidence_identifiers=identifiers,
        )

    assessments = [item for item in (
        from_signals(ForwardDecisionDimension.REGIME, summary="Governed Phase-5 macro and currency signals provide partial regime context", channels=("macro", "currency")),
        from_signals(ForwardDecisionDimension.FUNDAMENTALS, summary="Governed Phase-5 signals provide partial business and valuation trajectory context", channels=("fundamental",)),
        from_signals(ForwardDecisionDimension.CROSS_ASSET, summary="Governed macro, currency and forecast signals provide partial cross-asset confirmation", channels=("macro", "currency", "forecast")),
        from_signals(ForwardDecisionDimension.STRUCTURAL, summary="Governed structural-theme evidence provides partial value-chain transmission context", name_terms=("structural", "theme", "value-chain", "bottleneck")),
    ) if item is not None]

    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.EXPECTATIONS,
        availability=EvidenceAvailability.AVAILABLE,
        summary=f"Evidence-backed outlook versus market-implied proxy gives expected surprise {expectations.expected_surprise:+.2%}; estimated priced-in score {expectations.priced_in_score:.0%}",
        confidence=expectations.confidence,
        evidence=expectations.diagnostics,
        contradictory_evidence=expectations.signal.contradictory_evidence,
        assumptions=expectations.signal.assumptions,
        risks=expectations.signal.risks,
        change_conditions=expectations.signal.change_conditions,
        evidence_identifiers=expectations.signal.evidence_identifiers,
        market_expectation=f"Market-implied proxy; estimated priced-in score {expectations.priced_in_score:.0%}",
        internal_expectation=f"Evidence-backed expected surprise {expectations.expected_surprise:+.2%}",
    ))

    catalysts = tuple(getattr(candidate, "primary_catalysts", ()) or ())
    if catalysts:
        assessments.append(ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.CATALYSTS,
            availability=EvidenceAvailability.PARTIAL,
            summary="Candidate catalysts are governed but no certified dated event calendar is attached; event timing and collision risk remain unresolved",
            confidence=min(0.75, evidence_quality),
            evidence=tuple(f"Candidate catalyst: {item}" for item in catalysts),
            assumptions=("Catalyst descriptions remain relevant through the next governed review",),
            risks=("Undated catalysts cannot support pre-event versus post-event timing decisions",),
            change_conditions=("Reassess when a certified event date or revised catalyst becomes available",),
            evidence_identifiers=candidate_ids,
        ))

    assessments.extend((
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.POSITIONING,
            availability=EvidenceAvailability.PARTIAL,
            summary=f"Price-and-volume market-behavior proxy indicates {flow.state.value}; complete institutional, fund, futures, dealer and cross-border positioning is not claimed",
            confidence=flow.confidence,
            evidence=flow.diagnostics,
            contradictory_evidence=flow.signal.contradictory_evidence,
            assumptions=flow.signal.assumptions,
            risks=flow.signal.risks,
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=flow.signal.evidence_identifiers,
        ),
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.MICROSTRUCTURE,
            availability=EvidenceAvailability.PARTIAL,
            summary="Liquidity and price/volume confirmation provide a partial market-structure view; order-book and dealer inventory evidence are not asserted",
            confidence=min(flow.confidence, float(market.confidence)),
            evidence=tuple(dict.fromkeys((*market.evidence, *flow.diagnostics))),
            contradictory_evidence=("No complete order-book, dealer inventory, or venue-fragmentation model is claimed",),
            assumptions=flow.signal.assumptions,
            risks=tuple(dict.fromkeys((*market.risks, *flow.signal.risks))),
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=tuple(dict.fromkeys((*market.evidence_identifiers, *flow.signal.evidence_identifiers))),
        ),
        ForwardDimensionAssessment(
            dimension=ForwardDecisionDimension.REFLEXIVITY,
            availability=EvidenceAvailability.PARTIAL,
            summary=f"Crowding/reversal proxies imply {flow.reversal_risk:.0%} reversal risk; forced-flow mechanics remain incomplete without certified dealer/leverage data",
            confidence=flow.confidence,
            evidence=flow.diagnostics,
            contradictory_evidence=("Short-covering and crowding are inferred from market behavior rather than complete owner/dealer books",),
            assumptions=flow.signal.assumptions,
            risks=flow.signal.risks,
            change_conditions=flow.signal.change_conditions,
            evidence_identifiers=flow.signal.evidence_identifiers,
        ),
    ))

    scenario_evidence = tuple(
        f"{point.label}: probability={point.probability:.1%}, return={point.total_return:+.2%}"
        for point in getattr(candidate, "scenario_distribution")
    )
    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.PATH_RISK,
        availability=EvidenceAvailability.AVAILABLE,
        summary=f"Canonical candidate distribution spans bear/base/bull outcomes with expected downside {float(getattr(candidate, 'expected_downside')):+.2%} over {int(getattr(candidate, 'decision_horizon_days'))} days",
        confidence=evidence_quality,
        evidence=scenario_evidence,
        contradictory_evidence=tuple(getattr(candidate, "contradictory_evidence", ()) or ()),
        assumptions=tuple(getattr(candidate, "critical_assumptions", ()) or ()),
        risks=tuple(getattr(candidate, "key_risks", ()) or ()),
        change_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ()),
        evidence_identifiers=candidate_ids,
    ))
    assessments.append(ForwardDimensionAssessment(
        dimension=ForwardDecisionDimension.PORTFOLIO_CONTEXT,
        availability=EvidenceAvailability.PARTIAL,
        summary=f"Pre-committee edge versus governed opportunity-cost baseline is {float(getattr(candidate, 'opportunity_edge')):+.2%}; current weight {float(getattr(candidate, 'current_portfolio_weight')):.2%}. Final best-alternative comparison remains downstream.",
        confidence=evidence_quality,
        evidence=(f"Net expected return={float(getattr(candidate, 'net_expected_return')):+.2%}", f"Opportunity-cost return={float(getattr(candidate, 'opportunity_cost_return')):+.2%}"),
        assumptions=("Final portfolio competition and constraints remain authoritative downstream",),
        risks=("An attractive standalone candidate can still be inferior to another use of portfolio capital",),
        change_conditions=("Reassess after changes in opportunity cost, holdings, cash hurdle, or competing candidates",),
        evidence_identifiers=candidate_ids,
    ))

    timing = DecisionTiming(
        posture=DecisionTimingPosture.NO_TIMING_EDGE,
        rationale="No certified dated catalyst calendar is attached, so v2 does not invent a pre-event/post-event timing edge",
        next_reassessment_at=_aware(getattr(candidate, "review_at"), field_name="candidate review_at"),
    )
    thesis_monitor = ThesisMonitor(
        thesis="Governed candidate thesis: " + "; ".join(catalysts[:2]),
        must_remain_true=tuple(getattr(candidate, "critical_assumptions", ()) or ()),
        invalidation_conditions=tuple(getattr(candidate, "invalidation_conditions", ()) or ()),
        monitor_evidence=tuple(getattr(candidate, "monitoring_indicators", ()) or ()),
    )
    applicable = applicable_dimensions(asset_class)
    assessments = [
        item for item in assessments if item.dimension in applicable
    ]
    return build_forward_decision_context(
        identifier=f"forward-decision:{candidate_identifier}:{as_of.isoformat()}",
        candidate_identifier=candidate_identifier,
        as_of=as_of,
        asset_class=asset_class,
        assessments=tuple(assessments),
        timing=timing,
        thesis_monitor=thesis_monitor,
    )


@dataclass(frozen=True, slots=True)
class PredictiveMarketIntelligence:
    flow: CapitalFlowAssessment
    expectations: MarketExpectationsAssessment
    market: MarketSpecialistContext
    forward_intelligence: ForwardIntelligenceBundle
    evidence_identifiers: tuple[str, ...]
    model_versions: tuple[tuple[str, str], ...]


def merge_forward_intelligence(
    existing: ForwardIntelligenceBundle | None,
    predictive: ForwardIntelligenceBundle,
) -> ForwardIntelligenceBundle:
    if existing is None:
        return predictive
    if existing.candidate_identifier != predictive.candidate_identifier:
        raise ValueError("forward-intelligence bundles refer to different candidates")
    if existing.as_of != predictive.as_of:
        raise ValueError("forward-intelligence bundles have different as_of timestamps")
    signals = tuple(
        {item.identifier: item for item in (*existing.signals, *predictive.signals)}.values()
    )
    scenarios = tuple((*existing.scenarios, *predictive.scenarios))
    return ForwardIntelligenceBundle(
        identifier=f"forward-intelligence:merged:{existing.candidate_identifier}:{existing.as_of.isoformat()}:{_digest([existing.identifier, predictive.identifier])}",
        candidate_identifier=existing.candidate_identifier,
        as_of=existing.as_of,
        signals=signals,
        scenarios=scenarios,
        diagnostics=tuple(dict.fromkeys((*existing.diagnostics, *predictive.diagnostics))),
        model_versions=tuple(dict.fromkeys((*existing.model_versions, *predictive.model_versions))),
        theme_stage=existing.theme_stage or predictive.theme_stage,
        trend_stage=existing.trend_stage or predictive.trend_stage,
        policy_regime=existing.policy_regime or predictive.policy_regime,
        currency_regime=existing.currency_regime or predictive.currency_regime,
        decision_context=predictive.decision_context or existing.decision_context,
        schema_version="forward-intelligence.v2-predictive-market",
    )


def build_predictive_market_intelligence(
    *,
    candidate: object,
    features: object,
    flow_observation: CapitalFlowObservation,
    market: MarketSpecialistContext,
    existing_forward_intelligence: ForwardIntelligenceBundle | None,
    research_evidence: ForwardResearchEvidence | None = None,
) -> PredictiveMarketIntelligence:
    flow = CapitalFlowEngine().analyze(flow_observation)
    expectations_observation = MarketExpectationsEngine.observe(
        candidate=candidate,
        features=features,
        flow=flow,
    )
    expectations = MarketExpectationsEngine().analyze(expectations_observation)
    enriched_market = replace(
        market,
        market_regime=f"{market.market_regime}+{flow.state.value}",
        expected_return_impact=_clip(
            market.expected_return_impact + flow.expected_return_impact,
            -1.0,
            1.0,
        ),
        confidence=_clip(
            0.60 * market.confidence + 0.40 * flow.confidence,
            0.0,
            1.0,
        ),
        positioning=_clip(
            0.35 * market.positioning + 0.65 * flow.direction,
            -1.0,
            1.0,
        ),
        evidence=tuple(
            dict.fromkeys(
                (
                    *market.evidence,
                    *flow.diagnostics,
                    *expectations.diagnostics,
                )
            )
        ),
        risks=tuple(
            dict.fromkeys(
                (
                    *market.risks,
                    "Observed market flow is a price-and-volume proxy until complete fund, futures, options, dealer, credit, and cross-border sources are certified",
                    f"Flow reversal risk={flow.reversal_risk:.0%}",
                    f"Estimated priced-in score={expectations.priced_in_score:.0%}",
                )
            )
        ),
        entry_conditions=tuple(
            dict.fromkeys(
                (
                    *market.entry_conditions,
                    "Capital-flow direction and persistence do not reverse before implementation",
                    "The expectations gap remains positive after refreshed price, volatility, and candidate evidence",
                )
            )
        ),
        evidence_identifiers=tuple(
            dict.fromkeys(
                (
                    *market.evidence_identifiers,
                    *flow.signal.evidence_identifiers,
                    *expectations.signal.evidence_identifiers,
                )
            )
        ),
    )
    decision_context = (
        build_predictive_forward_decision_context(
            candidate=candidate,
            flow=flow,
            expectations=expectations,
            market=enriched_market,
            existing_forward_intelligence=existing_forward_intelligence,
        )
        if isinstance(candidate, CandidateDecisionRecord)
        else None
    )
    if decision_context is not None:
        decision_context = enrich_forward_decision_context(
            decision_context,
            research_evidence,
        )
    predictive_bundle = ForwardIntelligenceBundle(
        identifier=f"forward-intelligence:predictive-market:{getattr(candidate, 'identifier')}:{getattr(candidate, 'as_of').isoformat()}",
        candidate_identifier=str(getattr(candidate, "identifier")),
        as_of=getattr(candidate, "as_of"),
        signals=(flow.signal, expectations.signal),
        scenarios=expectations.scenarios,
        diagnostics=tuple(dict.fromkeys((*flow.diagnostics, *expectations.diagnostics))),
        model_versions=(
            CapitalFlowEngine.version,
            MarketExpectationsEngine.version,
            *((research_evidence.schema_version,) if research_evidence is not None else ()),
            *((decision_context.schema_version,) if decision_context is not None else ()),
        ),
        decision_context=decision_context,
        schema_version="forward-intelligence.v2-predictive-market",
    )
    bundle = merge_forward_intelligence(
        existing_forward_intelligence,
        predictive_bundle,
    )
    evidence_identifiers = tuple(
        dict.fromkeys(
            (
                *flow.signal.evidence_identifiers,
                *expectations.signal.evidence_identifiers,
                *(research_evidence.evidence_identifiers if research_evidence is not None else ()),
            )
        )
    )
    return PredictiveMarketIntelligence(
        flow=flow,
        expectations=expectations,
        market=enriched_market,
        forward_intelligence=bundle,
        evidence_identifiers=evidence_identifiers,
        model_versions=(
            ("capital_flow", CapitalFlowEngine.version),
            ("market_expectations", MarketExpectationsEngine.version),
            *(((("forward_research", research_evidence.schema_version),)) if research_evidence is not None else ()),
        ),
    )


__all__ = [
    "CapitalFlowAssessment",
    "CapitalFlowEngine",
    "CapitalFlowObservation",
    "CapitalFlowState",
    "MarketExpectationsAssessment",
    "MarketExpectationsEngine",
    "MarketExpectationsObservation",
    "PredictiveMarketIntelligence",
    "build_predictive_forward_decision_context",
    "build_predictive_market_intelligence",
    "merge_forward_intelligence",
]
