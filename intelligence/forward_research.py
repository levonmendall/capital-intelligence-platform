"""Governed forward opportunity discovery, nowcasting, and timing research.

This module extends Forward Decision Intelligence with research-only evidence.  It
never creates an executable order, changes qualification thresholds, adds a
specialist, or authorizes capital.  All observations are point-in-time and require
explicit evidence lineage.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from math import isfinite
from statistics import fmean
from typing import Any, Mapping

from cio.models import CandidateAssetClass
from data.provider_dataset import ProviderDatasetSnapshot, ProviderDatasetType
from intelligence.event_market_forward import EventMarketAssessment, EventCausalState
from intelligence.forward_decision import (
    DecisionTiming,
    DecisionTimingPosture,
    EvidenceAvailability,
    ForwardDecisionContext,
    ForwardDecisionDimension,
    ForwardDimensionAssessment,
    applicable_dimensions,
)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(value: object, *, field_name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number) or not low <= number <= high:
        raise ValueError(f"{field_name} must be finite and between {low} and {high}")
    return round(number, 8)


def _texts(values: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    result = tuple(_text(item, field_name=field_name) for item in values)
    if len(result) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


class ExpectationEvidenceKind(str, Enum):
    ANALYST_EPS = "analyst_eps"
    ANALYST_REVENUE = "analyst_revenue"
    ESTIMATE_REVISION = "estimate_revision"
    ESTIMATE_DISPERSION = "estimate_dispersion"
    COMPANY_GUIDANCE = "company_guidance"
    MACRO_CONSENSUS = "macro_consensus"
    POLICY_PROBABILITY = "policy_probability"
    YIELD_CURVE = "yield_curve"
    INFLATION_EXPECTATION = "inflation_expectation"
    OPTIONS_IMPLIED = "options_implied"
    CREDIT_IMPLIED = "credit_implied"
    COMMODITY_CURVE = "commodity_curve"
    EVENT_PROBABILITY = "event_probability"


class PositioningEvidenceKind(str, Enum):
    ETF_FLOW = "etf_flow"
    FUND_FLOW = "fund_flow"
    FUTURES_POSITIONING = "futures_positioning"
    SHORT_INTEREST = "short_interest"
    BORROW_UTILIZATION = "borrow_utilization"
    BORROW_COST = "borrow_cost"
    OPTIONS_VOLUME = "options_volume"
    OPTIONS_OPEN_INTEREST = "options_open_interest"
    OPTIONS_OPENING_CLOSING = "options_opening_closing"
    OPTIONS_SKEW = "options_skew"
    OPTIONS_TERM_STRUCTURE = "options_term_structure"
    DEALER_GAMMA = "dealer_gamma"
    DEALER_VANNA = "dealer_vanna"
    DEALER_CHARM = "dealer_charm"
    CTA_POSITIONING = "cta_positioning"
    VOL_CONTROL = "vol_control"
    CROSS_BORDER_FLOW = "cross_border_flow"
    CRYPTO_FUNDING = "crypto_funding"
    CRYPTO_OPEN_INTEREST = "crypto_open_interest"
    CRYPTO_LIQUIDATIONS = "crypto_liquidations"


class NowcastTarget(str, Enum):
    CPI = "cpi"
    PAYROLLS = "payrolls"
    GDP = "gdp"
    RETAIL_SALES = "retail_sales"
    INDUSTRIAL_PRODUCTION = "industrial_production"
    COMPANY_REVENUE = "company_revenue"
    COMPANY_EARNINGS = "company_earnings"
    COMPANY_MARGIN = "company_margin"
    INVENTORIES = "inventories"
    COMMODITY_SUPPLY = "commodity_supply"
    COMMODITY_DEMAND = "commodity_demand"


@dataclass(frozen=True, slots=True)
class CertifiedExpectationObservation:
    identifier: str
    subject_identifier: str
    kind: ExpectationEvidenceKind
    as_of: datetime
    market_expectation: float
    internal_expectation: float
    uncertainty: float
    confidence: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("identifier", "subject_identifier"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.kind, ExpectationEvidenceKind):
            raise TypeError("kind must be ExpectationEvidenceKind")
        for name in ("market_expectation", "internal_expectation"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=-10_000.0, high=10_000.0))
        object.__setattr__(self, "uncertainty", _number(self.uncertainty, field_name="uncertainty", low=0.0, high=10_000.0))
        object.__setattr__(self, "confidence", _number(self.confidence, field_name="confidence", low=0.0, high=1.0))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))

    @property
    def standardized_surprise(self) -> float:
        scale = max(self.uncertainty, abs(self.market_expectation) * 0.05, 1e-6)
        return _clip((self.internal_expectation - self.market_expectation) / scale, -5.0, 5.0)


@dataclass(frozen=True, slots=True)
class ExpectationsIntelligence:
    expected_surprise: float
    priced_in_score: float
    confidence: float
    observations: tuple[CertifiedExpectationObservation, ...]
    evidence_identifiers: tuple[str, ...]
    proxy_fallback: bool = False
    schema_version: str = "expectations-intelligence.v2"


class ExpectationsIntelligenceEngine:
    version = "expectations-intelligence.v2-certified"

    def analyze(
        self,
        observations: tuple[CertifiedExpectationObservation, ...],
        *,
        proxy_expected_surprise: float | None = None,
        proxy_priced_in_score: float | None = None,
        proxy_confidence: float | None = None,
    ) -> ExpectationsIntelligence:
        if observations:
            weighted = [(item.standardized_surprise, max(0.05, item.confidence)) for item in observations]
            total_weight = sum(weight for _value, weight in weighted)
            standardized = sum(value * weight for value, weight in weighted) / total_weight
            surprise = _clip(standardized * 0.10, -1.0, 1.0)
            priced_in = _clip(0.5 - surprise * 2.0, 0.0, 1.0)
            confidence = _clip(fmean(item.confidence for item in observations) * min(1.0, 0.65 + 0.08 * len(observations)), 0.0, 1.0)
            evidence_ids = tuple(dict.fromkeys(identifier for item in observations for identifier in item.evidence_identifiers))
            return ExpectationsIntelligence(surprise, priced_in, confidence, observations, evidence_ids)
        if proxy_expected_surprise is None or proxy_priced_in_score is None or proxy_confidence is None:
            raise ValueError("certified expectations or explicit proxy fallback is required")
        return ExpectationsIntelligence(
            _number(proxy_expected_surprise, field_name="proxy_expected_surprise", low=-1.0, high=2.0),
            _number(proxy_priced_in_score, field_name="proxy_priced_in_score", low=0.0, high=1.0),
            _number(proxy_confidence, field_name="proxy_confidence", low=0.0, high=1.0),
            (),
            (),
            proxy_fallback=True,
        )


@dataclass(frozen=True, slots=True)
class PositioningObservation:
    identifier: str
    subject_identifier: str
    kind: PositioningEvidenceKind
    as_of: datetime
    directional_pressure: float
    crowding: float
    confidence: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("identifier", "subject_identifier"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.kind, PositioningEvidenceKind):
            raise TypeError("kind must be PositioningEvidenceKind")
        object.__setattr__(self, "directional_pressure", _number(self.directional_pressure, field_name="directional_pressure", low=-1.0, high=1.0))
        for name in ("crowding", "confidence"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=0.0, high=1.0))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


_DERIVATIVE_KINDS = frozenset({
    PositioningEvidenceKind.OPTIONS_VOLUME,
    PositioningEvidenceKind.OPTIONS_OPEN_INTEREST,
    PositioningEvidenceKind.OPTIONS_OPENING_CLOSING,
    PositioningEvidenceKind.OPTIONS_SKEW,
    PositioningEvidenceKind.OPTIONS_TERM_STRUCTURE,
    PositioningEvidenceKind.DEALER_GAMMA,
    PositioningEvidenceKind.DEALER_VANNA,
    PositioningEvidenceKind.DEALER_CHARM,
    PositioningEvidenceKind.CRYPTO_FUNDING,
    PositioningEvidenceKind.CRYPTO_OPEN_INTEREST,
    PositioningEvidenceKind.CRYPTO_LIQUIDATIONS,
})


@dataclass(frozen=True, slots=True)
class PositioningIntelligence:
    direction: float
    crowding: float
    reversal_risk: float
    confidence: float
    observations: tuple[PositioningObservation, ...]
    derivative_coverage: bool
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "positioning-intelligence.v2"


class PositioningIntelligenceEngine:
    version = "positioning-intelligence.v2-certified"

    def analyze(self, observations: tuple[PositioningObservation, ...]) -> PositioningIntelligence:
        if not observations:
            raise ValueError("at least one positioning observation is required")
        weights = [max(0.05, item.confidence) for item in observations]
        total = sum(weights)
        direction = sum(item.directional_pressure * weight for item, weight in zip(observations, weights)) / total
        crowding = sum(item.crowding * weight for item, weight in zip(observations, weights)) / total
        disagreement = fmean(abs(item.directional_pressure - direction) for item in observations)
        reversal = _clip(0.55 * crowding + 0.30 * disagreement + 0.15 * max(0.0, abs(direction) - 0.65), 0.0, 1.0)
        confidence = _clip(fmean(item.confidence for item in observations) * (1.0 - 0.35 * disagreement), 0.0, 1.0)
        ids = tuple(dict.fromkeys(identifier for item in observations for identifier in item.evidence_identifiers))
        return PositioningIntelligence(
            _clip(direction, -1.0, 1.0), _clip(crowding, 0.0, 1.0), reversal, confidence,
            observations, any(item.kind in _DERIVATIVE_KINDS for item in observations), ids,
        )


@dataclass(frozen=True, slots=True)
class NowcastObservation:
    identifier: str
    target: NowcastTarget
    as_of: datetime
    signal: float
    weight: float
    confidence: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        if not isinstance(self.target, NowcastTarget):
            raise TypeError("target must be NowcastTarget")
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "signal", _number(self.signal, field_name="signal", low=-10_000.0, high=10_000.0))
        object.__setattr__(self, "weight", _number(self.weight, field_name="weight", low=0.0, high=100.0))
        object.__setattr__(self, "confidence", _number(self.confidence, field_name="confidence", low=0.0, high=1.0))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class NowcastEstimate:
    target: NowcastTarget
    as_of: datetime
    estimate: float
    lower_bound: float
    upper_bound: float
    probability_above_consensus: float | None
    confidence: float
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "governed-nowcast.v1"


class GovernedNowcastingEngine:
    version = "governed-nowcasting.v1"

    def estimate(
        self,
        observations: tuple[NowcastObservation, ...],
        *,
        consensus: float | None = None,
    ) -> NowcastEstimate:
        if not observations:
            raise ValueError("nowcast requires at least one observation")
        target = observations[0].target
        as_of = max(item.as_of for item in observations)
        if any(item.target is not target for item in observations):
            raise ValueError("nowcast observations must share a target")
        weights = [max(0.01, item.weight * item.confidence) for item in observations]
        total = sum(weights)
        estimate = sum(item.signal * weight for item, weight in zip(observations, weights)) / total
        dispersion = fmean(abs(item.signal - estimate) for item in observations)
        confidence = _clip(fmean(item.confidence for item in observations) * (1.0 / (1.0 + dispersion)), 0.0, 1.0)
        band = max(dispersion, abs(estimate) * (1.0 - confidence) * 0.25, 1e-6)
        probability = None
        if consensus is not None:
            gap = (estimate - float(consensus)) / band
            probability = _clip(0.5 + 0.22 * gap, 0.01, 0.99)
        ids = tuple(dict.fromkeys(identifier for item in observations for identifier in item.evidence_identifiers))
        return NowcastEstimate(target, as_of, round(estimate, 8), round(estimate-band, 8), round(estimate+band, 8), probability, confidence, ids)


@dataclass(frozen=True, slots=True)
class ResearchExposure:
    exposure_identifier: str
    instrument_identifier: str
    symbol: str
    asset_class: CandidateAssetClass
    liquidity_score: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("exposure_identifier", "instrument_identifier", "symbol"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        object.__setattr__(self, "liquidity_score", _number(self.liquidity_score, field_name="liquidity_score", low=0.0, high=1.0))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class ForwardOpportunityHypothesis:
    identifier: str
    information_identifier: str
    instrument_identifier: str
    symbol: str
    direction: str
    horizon: str
    mechanism: str
    research_priority: float
    evidence_identifiers: tuple[str, ...]
    research_only: bool = True
    authorizes_capital: bool = False
    schema_version: str = "forward-opportunity-hypothesis.v1"


class ForwardOpportunityDiscoveryEngine:
    """Turn an existing causal assessment into explicit research hypotheses only."""

    version = "forward-opportunity-discovery.v1"

    def discover(
        self,
        assessment: EventMarketAssessment,
        *,
        eligible_exposures: tuple[ResearchExposure, ...],
    ) -> tuple[ForwardOpportunityHypothesis, ...]:
        if assessment.state in {EventCausalState.ANALYSIS_BLOCKED, EventCausalState.UNRESOLVED_MAJOR_EVENT, EventCausalState.UNKNOWN}:
            return ()
        by_exposure: dict[str, list[ResearchExposure]] = {}
        for exposure in eligible_exposures:
            by_exposure.setdefault(exposure.exposure_identifier, []).append(exposure)
        results: list[ForwardOpportunityHypothesis] = []
        for transmission in assessment.transmissions:
            for exposure in by_exposure.get(transmission.target_identifier, ()):
                priority = _clip(transmission.magnitude * transmission.confidence * (0.55 + 0.45 * exposure.liquidity_score), 0.0, 1.0)
                results.append(ForwardOpportunityHypothesis(
                    identifier=f"forward-hypothesis:{assessment.identifier}:{exposure.instrument_identifier}",
                    information_identifier=assessment.information_identifier,
                    instrument_identifier=exposure.instrument_identifier,
                    symbol=exposure.symbol.upper(),
                    direction=transmission.direction.value,
                    horizon=transmission.horizon,
                    mechanism=transmission.mechanism,
                    research_priority=priority,
                    evidence_identifiers=tuple(dict.fromkeys((*assessment.evidence_identifiers, *transmission.evidence_identifiers, *exposure.evidence_identifiers))),
                ))
        return tuple(sorted(results, key=lambda item: (item.research_priority, item.symbol), reverse=True))


@dataclass(frozen=True, slots=True)
class ValueOfWaitingInputs:
    as_of: datetime
    invest_now_expected_return: float
    downside_if_unresolved: float
    probability_uncertainty_resolves: float
    expected_upside_lost_by_waiting: float
    expected_post_event_entry_drag: float
    transaction_cost_return: float
    alternative_return_while_waiting: float
    thesis_decay_return: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        for name in ("invest_now_expected_return", "downside_if_unresolved", "expected_upside_lost_by_waiting", "expected_post_event_entry_drag", "transaction_cost_return", "alternative_return_while_waiting", "thesis_decay_return"):
            object.__setattr__(self, name, _number(getattr(self, name), field_name=name, low=-1.0, high=2.0))
        object.__setattr__(self, "probability_uncertainty_resolves", _number(self.probability_uncertainty_resolves, field_name="probability_uncertainty_resolves", low=0.0, high=1.0))
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))


@dataclass(frozen=True, slots=True)
class ValueOfWaitingAssessment:
    posture: DecisionTimingPosture
    invest_now_value: float
    wait_value: float
    value_of_waiting: float
    rationale: str
    evidence_identifiers: tuple[str, ...]
    advisory_only: bool = True
    schema_version: str = "value-of-waiting.v1"


class ValueOfWaitingEngine:
    version = "value-of-waiting.v1"

    def assess(self, inputs: ValueOfWaitingInputs) -> ValueOfWaitingAssessment:
        risk_avoided = abs(min(0.0, inputs.downside_if_unresolved)) * inputs.probability_uncertainty_resolves
        invest_now = inputs.invest_now_expected_return - inputs.transaction_cost_return
        wait_value = (
            inputs.alternative_return_while_waiting
            + risk_avoided
            - inputs.expected_upside_lost_by_waiting
            - inputs.expected_post_event_entry_drag
            - inputs.thesis_decay_return
        )
        value = wait_value - invest_now
        if value > 0.0025:
            posture = DecisionTimingPosture.WAIT_FOR_EVENT
        elif value < -0.0025:
            posture = DecisionTimingPosture.ACT_NOW
        else:
            posture = DecisionTimingPosture.REASSESS
        return ValueOfWaitingAssessment(
            posture, round(invest_now, 8), round(wait_value, 8), round(value, 8),
            f"Advisory wait value {value:+.2%}: information-risk benefit {risk_avoided:+.2%} versus expected upside/entry/thesis-decay costs.",
            inputs.evidence_identifiers,
        )


@dataclass(frozen=True, slots=True)
class ForwardResearchEvidence:
    expectations: ExpectationsIntelligence | None = None
    positioning: PositioningIntelligence | None = None
    nowcasts: tuple[NowcastEstimate, ...] = ()
    value_of_waiting: ValueOfWaitingAssessment | None = None
    schema_version: str = "forward-research-evidence.v1"

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        values: list[str] = []
        if self.expectations is not None:
            values.extend(self.expectations.evidence_identifiers)
        if self.positioning is not None:
            values.extend(self.positioning.evidence_identifiers)
        for item in self.nowcasts:
            values.extend(item.evidence_identifiers)
        if self.value_of_waiting is not None:
            values.extend(self.value_of_waiting.evidence_identifiers)
        return tuple(dict.fromkeys(values))


def _merge_assessment(
    existing: ForwardDimensionAssessment,
    *,
    availability: EvidenceAvailability,
    summary: str,
    confidence: float,
    evidence: tuple[str, ...],
    identifiers: tuple[str, ...],
    market_expectation: str | None = None,
    internal_expectation: str | None = None,
) -> ForwardDimensionAssessment:
    return ForwardDimensionAssessment(
        dimension=existing.dimension,
        availability=availability,
        summary=summary,
        confidence=confidence,
        evidence=tuple(dict.fromkeys((*existing.evidence, *evidence))),
        contradictory_evidence=existing.contradictory_evidence,
        assumptions=existing.assumptions,
        risks=existing.risks,
        change_conditions=existing.change_conditions,
        evidence_identifiers=tuple(dict.fromkeys((*existing.evidence_identifiers, *identifiers))),
        market_expectation=market_expectation or existing.market_expectation,
        internal_expectation=internal_expectation or existing.internal_expectation,
    )


def enrich_forward_decision_context(
    context: ForwardDecisionContext,
    research: ForwardResearchEvidence | None,
) -> ForwardDecisionContext:
    if research is None:
        return context
    applicable = applicable_dimensions(context.asset_class)
    dimensions = {item.dimension: item for item in context.dimensions}
    if research.expectations is not None and research.expectations.observations and ForwardDecisionDimension.EXPECTATIONS in applicable:
        exp = research.expectations
        current = dimensions[ForwardDecisionDimension.EXPECTATIONS]
        dimensions[current.dimension] = _merge_assessment(
            current,
            availability=EvidenceAvailability.AVAILABLE,
            summary=f"Certified expectations evidence indicates expected surprise {exp.expected_surprise:+.2%}; priced-in score {exp.priced_in_score:.0%}.",
            confidence=exp.confidence,
            evidence=tuple(f"{item.kind.value}: market={item.market_expectation:g}, internal={item.internal_expectation:g}" for item in exp.observations),
            identifiers=exp.evidence_identifiers,
            market_expectation=f"Certified market expectations; priced-in score {exp.priced_in_score:.0%}",
            internal_expectation=f"Certified evidence-backed surprise {exp.expected_surprise:+.2%}",
        )
    if research.positioning is not None and ForwardDecisionDimension.POSITIONING in applicable:
        pos = research.positioning
        current = dimensions[ForwardDecisionDimension.POSITIONING]
        dimensions[current.dimension] = _merge_assessment(
            current,
            availability=EvidenceAvailability.AVAILABLE,
            summary=f"Certified positioning evidence direction {pos.direction:+.2f}, crowding {pos.crowding:.0%}, reversal risk {pos.reversal_risk:.0%}.",
            confidence=pos.confidence,
            evidence=tuple(f"{item.kind.value}: direction={item.directional_pressure:+.2f}, crowding={item.crowding:.0%}" for item in pos.observations),
            identifiers=pos.evidence_identifiers,
        )
        if pos.derivative_coverage and ForwardDecisionDimension.DERIVATIVES in applicable:
            current = dimensions[ForwardDecisionDimension.DERIVATIVES]
            dimensions[current.dimension] = ForwardDimensionAssessment(
                dimension=current.dimension,
                availability=EvidenceAvailability.AVAILABLE,
                summary="Certified derivatives/positioning observations populate the derivatives forward view.",
                confidence=pos.confidence,
                evidence=tuple(f"Certified {item.kind.value}" for item in pos.observations if item.kind in _DERIVATIVE_KINDS),
                contradictory_evidence=current.contradictory_evidence,
                assumptions=current.assumptions,
                risks=current.risks,
                change_conditions=current.change_conditions,
                evidence_identifiers=pos.evidence_identifiers,
            )
    if research.nowcasts and ForwardDecisionDimension.ALTERNATIVE_DATA in applicable:
        current = dimensions[ForwardDecisionDimension.ALTERNATIVE_DATA]
        ids = tuple(dict.fromkeys(identifier for item in research.nowcasts for identifier in item.evidence_identifiers))
        evidence = tuple(f"{item.target.value} nowcast={item.estimate:g} [{item.lower_bound:g}, {item.upper_bound:g}] confidence={item.confidence:.0%}" for item in research.nowcasts)
        dimensions[current.dimension] = ForwardDimensionAssessment(
            dimension=current.dimension,
            availability=EvidenceAvailability.AVAILABLE,
            summary="Governed point-in-time nowcasts provide pre-release leading evidence.",
            confidence=min(item.confidence for item in research.nowcasts),
            evidence=tuple(dict.fromkeys((*current.evidence, *evidence))),
            contradictory_evidence=current.contradictory_evidence,
            assumptions=current.assumptions,
            risks=current.risks,
            change_conditions=current.change_conditions,
            evidence_identifiers=tuple(dict.fromkeys((*current.evidence_identifiers, *ids))),
        )
    timing = context.timing
    if research.value_of_waiting is not None:
        assessment = research.value_of_waiting
        timing = DecisionTiming(
            posture=assessment.posture,
            rationale=assessment.rationale,
            next_reassessment_at=None if timing is None else timing.next_reassessment_at,
        )
    return replace(context, dimensions=tuple(dimensions[item] for item in ForwardDecisionDimension), timing=timing)


def _rows(snapshot: ProviderDatasetSnapshot) -> tuple[Mapping[str, Any], ...]:
    payload = snapshot.payload
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, Mapping))
    for key in ("data", "rows", "observations", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, Mapping))
    return (payload,)


def expectation_observations_from_snapshot(snapshot: ProviderDatasetSnapshot) -> tuple[CertifiedExpectationObservation, ...]:
    if snapshot.query.dataset_type not in {ProviderDatasetType.EXPECTATIONS, ProviderDatasetType.EVENT_EXPECTATIONS}:
        return ()
    result = []
    for index, row in enumerate(_rows(snapshot), start=1):
        result.append(CertifiedExpectationObservation(
            identifier=str(row.get("identifier") or f"{snapshot.provider}:{snapshot.query.dataset_type.value}:{index}:{snapshot.content_hash[:12]}"),
            subject_identifier=str(row.get("subject_identifier") or snapshot.query.provider_symbol),
            kind=ExpectationEvidenceKind(str(row["kind"])),
            as_of=snapshot.query.as_of,
            market_expectation=float(row["market_expectation"]),
            internal_expectation=float(row["internal_expectation"]),
            uncertainty=float(row.get("uncertainty", 0.0)),
            confidence=float(row.get("confidence", 0.5)),
            evidence_identifiers=(f"provider-dataset:{snapshot.provider}:{snapshot.content_hash}",),
        ))
    return tuple(result)


def positioning_observations_from_snapshot(snapshot: ProviderDatasetSnapshot) -> tuple[PositioningObservation, ...]:
    if snapshot.query.dataset_type not in {ProviderDatasetType.POSITIONING, ProviderDatasetType.DERIVATIVE_POSITIONING}:
        return ()
    result = []
    for index, row in enumerate(_rows(snapshot), start=1):
        result.append(PositioningObservation(
            identifier=str(row.get("identifier") or f"{snapshot.provider}:{snapshot.query.dataset_type.value}:{index}:{snapshot.content_hash[:12]}"),
            subject_identifier=str(row.get("subject_identifier") or snapshot.query.provider_symbol),
            kind=PositioningEvidenceKind(str(row["kind"])),
            as_of=snapshot.query.as_of,
            directional_pressure=float(row["directional_pressure"]),
            crowding=float(row.get("crowding", 0.0)),
            confidence=float(row.get("confidence", 0.5)),
            evidence_identifiers=(f"provider-dataset:{snapshot.provider}:{snapshot.content_hash}",),
        ))
    return tuple(result)


def nowcast_observations_from_snapshot(snapshot: ProviderDatasetSnapshot) -> tuple[NowcastObservation, ...]:
    if snapshot.query.dataset_type is not ProviderDatasetType.LEADING_INDICATORS:
        return ()
    result = []
    for index, row in enumerate(_rows(snapshot), start=1):
        result.append(NowcastObservation(
            identifier=str(row.get("identifier") or f"{snapshot.provider}:leading:{index}:{snapshot.content_hash[:12]}"),
            target=NowcastTarget(str(row["target"])),
            as_of=snapshot.query.as_of,
            signal=float(row["signal"]),
            weight=float(row.get("weight", 1.0)),
            confidence=float(row.get("confidence", 0.5)),
            evidence_identifiers=(f"provider-dataset:{snapshot.provider}:{snapshot.content_hash}",),
        ))
    return tuple(result)


__all__ = [
    "CertifiedExpectationObservation", "ExpectationEvidenceKind", "ExpectationsIntelligence",
    "ExpectationsIntelligenceEngine", "ForwardOpportunityDiscoveryEngine", "ForwardOpportunityHypothesis",
    "ForwardResearchEvidence", "GovernedNowcastingEngine", "NowcastEstimate", "NowcastObservation",
    "NowcastTarget", "PositioningEvidenceKind", "PositioningIntelligence", "PositioningIntelligenceEngine",
    "PositioningObservation", "ResearchExposure", "ValueOfWaitingAssessment", "ValueOfWaitingEngine",
    "ValueOfWaitingInputs", "enrich_forward_decision_context", "expectation_observations_from_snapshot",
    "nowcast_observations_from_snapshot", "positioning_observations_from_snapshot",
]
