"""Governed event-to-market causal evidence for the existing forward-intelligence path.

This module analyzes source-qualified public events, preserves unresolved or mixed
causal conclusions, tests directional hypotheses against point-in-time market
observations, and converts only strictly escalated event evidence into the
existing :class:`ForwardIntelligenceBundle` contract.

It cannot create a candidate, alter qualification thresholds, authorize capital,
construct a portfolio, create an order, or enable real-money execution.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from data.decision_information import (
    DecisionInformationRecord,
    InformationQualityState,
    PortfolioImpactChannel,
)
from intelligence.event_quality import EventClusterAssessment
from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal


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


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if str(value).strip()))


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


class TransmissionDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"

    @property
    def sign(self) -> float:
        if self is TransmissionDirection.POSITIVE:
            return 1.0
        if self is TransmissionDirection.NEGATIVE:
            return -1.0
        return 0.0


class EventCausalState(str, Enum):
    MAPPED = "mapped"
    MIXED = "mixed"
    UNRESOLVED_MAJOR_EVENT = "unresolved_major_event"
    ANALYSIS_BLOCKED = "analysis_blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EventMarketPolicy:
    version: str = "event-market-forward.v1"
    minimum_rule_score: float = 0.45
    minimum_major_event_materiality: float = 0.50
    minimum_observed_move: float = 0.001
    full_confirmation_move: float = 0.02
    mixed_direction_conflict_ratio: float = 0.35
    minimum_market_confirmation: float = 0.10
    minimum_confirmation_coverage: float = 0.50
    minimum_assessment_confidence: float = 0.45


@dataclass(frozen=True, slots=True)
class MarketObservation:
    identifier: str
    exposure_identifier: str
    observed_at: datetime
    return_change: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "exposure_identifier"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.observed_at, field_name="observed_at")
        object.__setattr__(
            self,
            "return_change",
            _number(
                self.return_change,
                field_name="return_change",
                minimum=-1.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )


@dataclass(frozen=True, slots=True)
class RuleTransmission:
    target_identifier: str
    direction: TransmissionDirection
    magnitude: float
    mechanism: str
    horizon: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_identifier",
            _text(self.target_identifier, field_name="target_identifier"),
        )
        if not isinstance(self.direction, TransmissionDirection):
            raise TypeError("direction must be TransmissionDirection")
        object.__setattr__(
            self,
            "magnitude",
            _ratio(self.magnitude, field_name="magnitude"),
        )
        for field_name in ("mechanism", "horizon"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class EventCausalRule:
    identifier: str
    name: str
    channels: tuple[PortfolioImpactChannel, ...]
    keywords: tuple[str, ...]
    causal_chain: tuple[str, ...]
    transmissions: tuple[RuleTransmission, ...]
    alternatives: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in ("identifier", "name"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.channels, tuple) or not all(
            isinstance(item, PortfolioImpactChannel) for item in self.channels
        ):
            raise TypeError("channels must contain PortfolioImpactChannel values")
        object.__setattr__(
            self,
            "keywords",
            tuple(_text(item, field_name="keywords").lower() for item in self.keywords),
        )
        for field_name in ("causal_chain", "alternatives"):
            object.__setattr__(
                self,
                field_name,
                _texts(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=1,
                ),
            )
        if not isinstance(self.transmissions, tuple) or not all(
            isinstance(item, RuleTransmission) for item in self.transmissions
        ):
            raise TypeError("transmissions must contain RuleTransmission values")
        if not self.transmissions:
            raise ValueError("transmissions cannot be empty")

    def score(self, record: DecisionInformationRecord) -> float:
        text = " ".join(
            (
                record.topic,
                record.summary,
                *record.tags,
                *record.entities,
                *record.sectors,
            )
        ).lower()
        keyword_hits = sum(keyword in text for keyword in self.keywords)
        if keyword_hits == 0:
            return 0.0
        channel_hits = len(set(self.channels).intersection(record.impact_channels))
        keyword_score = min(0.65 + 0.15 * max(keyword_hits - 1, 0), 1.0)
        channel_score = min(channel_hits / max(min(len(self.channels), 2), 1), 1.0)
        return round(0.70 * keyword_score + 0.30 * channel_score, 8)


@dataclass(frozen=True, slots=True)
class CausalDriver:
    rule_identifier: str
    name: str
    confidence: float
    causal_chain: tuple[str, ...]
    transmissions: tuple[RuleTransmission, ...]
    alternatives: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketTransmission:
    target_identifier: str
    direction: TransmissionDirection
    magnitude: float
    confidence: float
    mechanism: str
    horizon: str
    contributing_driver_identifiers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]

    @property
    def directional_score(self) -> float:
        return round(self.direction.sign * self.magnitude * self.confidence, 8)


@dataclass(frozen=True, slots=True)
class EventMarketAssessment:
    identifier: str
    information_identifier: str
    event_cluster_identifier: str
    assessed_at: datetime
    state: EventCausalState
    drivers: tuple[CausalDriver, ...]
    causal_chain: tuple[str, ...]
    transmissions: tuple[MarketTransmission, ...]
    market_confirmation: float
    confirmation_coverage: float
    confidence: float
    major_event: bool
    requires_causal_review: bool
    contradictory_evidence: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    eligible_for_analysis: bool
    eligible_for_cio_context: bool
    policy_version: str
    schema_version: str = "event-market-assessment.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "information_identifier": self.information_identifier,
            "event_cluster_identifier": self.event_cluster_identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "state": self.state.value,
            "drivers": [
                {
                    "rule_identifier": item.rule_identifier,
                    "name": item.name,
                    "confidence": item.confidence,
                    "causal_chain": list(item.causal_chain),
                    "alternatives": list(item.alternatives),
                }
                for item in self.drivers
            ],
            "causal_chain": list(self.causal_chain),
            "transmissions": [
                {
                    "target_identifier": item.target_identifier,
                    "direction": item.direction.value,
                    "magnitude": item.magnitude,
                    "confidence": item.confidence,
                    "mechanism": item.mechanism,
                    "horizon": item.horizon,
                    "contributing_driver_identifiers": list(
                        item.contributing_driver_identifiers
                    ),
                    "evidence_identifiers": list(item.evidence_identifiers),
                }
                for item in self.transmissions
            ],
            "market_confirmation": self.market_confirmation,
            "confirmation_coverage": self.confirmation_coverage,
            "confidence": self.confidence,
            "major_event": self.major_event,
            "requires_causal_review": self.requires_causal_review,
            "contradictory_evidence": list(self.contradictory_evidence),
            "alternative_explanations": list(self.alternative_explanations),
            "unresolved_questions": list(self.unresolved_questions),
            "evidence_identifiers": list(self.evidence_identifiers),
            "eligible_for_analysis": self.eligible_for_analysis,
            "eligible_for_cio_context": self.eligible_for_cio_context,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
            "authorizes_portfolio_change": False,
            "real_money_authorized": False,
        }


class EventRuleCatalog:
    def __init__(
        self,
        rules: tuple[EventCausalRule, ...] | None = None,
        *,
        version: str = "event-causal-rules.2026-08.v1",
    ) -> None:
        self.version = _text(version, field_name="version")
        self.rules = rules or default_event_rules()
        identifiers = tuple(item.identifier for item in self.rules)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("event rule identifiers must be unique")

    def match(
        self,
        record: DecisionInformationRecord,
        *,
        minimum_score: float,
    ) -> tuple[CausalDriver, ...]:
        drivers = []
        for rule in self.rules:
            score = rule.score(record)
            if score < minimum_score:
                continue
            drivers.append(
                CausalDriver(
                    rule_identifier=rule.identifier,
                    name=rule.name,
                    confidence=score,
                    causal_chain=rule.causal_chain,
                    transmissions=rule.transmissions,
                    alternatives=rule.alternatives,
                )
            )
        return tuple(
            sorted(
                drivers,
                key=lambda item: (item.confidence, item.rule_identifier),
                reverse=True,
            )
        )


def _t(
    target: str,
    direction: TransmissionDirection,
    magnitude: float,
    mechanism: str,
    horizon: str = "near_to_medium_term",
) -> RuleTransmission:
    return RuleTransmission(target, direction, magnitude, mechanism, horizon)


def default_event_rules() -> tuple[EventCausalRule, ...]:
    positive = TransmissionDirection.POSITIVE
    negative = TransmissionDirection.NEGATIVE
    return (
        EventCausalRule(
            "geopolitical-deescalation",
            "geopolitical de-escalation",
            (PortfolioImpactChannel.GEOPOLITICAL, PortfolioImpactChannel.SUPPLY),
            ("ceasefire", "truce", "de-escalation", "peace agreement", "shipping restored"),
            (
                "Conflict probability or physical-disruption risk declines.",
                "Commodity and transport risk premia may compress.",
            ),
            (
                _t("broad_equities", positive, 0.45, "Lower geopolitical risk can support risk appetite and expected activity."),
                _t("volatility", negative, 0.55, "Lower event uncertainty can reduce demanded volatility premia."),
                _t("affected_commodity", negative, 0.55, "Lower disruption risk can reduce the supply-risk premium."),
                _t("commodity_consumers", positive, 0.45, "Lower input and transport costs can improve margins."),
                _t("commodity_producers", negative, 0.35, "Lower scarcity pricing can pressure producer cash flow."),
            ),
            (
                "The agreement may be temporary or unenforced.",
                "Commodity weakness may instead reflect deteriorating demand.",
            ),
        ),
        EventCausalRule(
            "geopolitical-escalation",
            "geopolitical escalation",
            (PortfolioImpactChannel.GEOPOLITICAL, PortfolioImpactChannel.SUPPLY),
            ("attack", "blockade", "invasion", "sanctions escalation", "shipping disruption"),
            (
                "Conflict or physical-disruption probability rises.",
                "Risk premia, transport costs, or supply scarcity may increase.",
            ),
            (
                _t("broad_equities", negative, 0.45, "Higher uncertainty and costs can pressure expected activity."),
                _t("volatility", positive, 0.60, "Higher event uncertainty can raise volatility premia."),
                _t("affected_commodity", positive, 0.60, "Higher disruption risk can raise scarcity pricing."),
                _t("commodity_consumers", negative, 0.45, "Higher input and transport costs can compress margins."),
                _t("commodity_producers", positive, 0.40, "Higher realized pricing can support producer cash flow."),
            ),
            (
                "Available spare capacity or inventories may absorb the disruption.",
                "The event may remain geographically contained.",
            ),
        ),
        EventCausalRule(
            "physical-supply-restoration",
            "physical supply restoration",
            (PortfolioImpactChannel.SUPPLY, PortfolioImpactChannel.COMMODITY),
            ("reopened", "resumed production", "restored capacity", "outage resolved", "inventory build"),
            ("Available supply or transport capacity rises.", "Scarcity and input-cost pressure may ease."),
            (
                _t("affected_commodity", negative, 0.55, "Higher available supply can reduce scarcity pricing."),
                _t("commodity_consumers", positive, 0.45, "Lower input costs can support margins and demand."),
                _t("commodity_producers", negative, 0.35, "Lower realized pricing can pressure producer economics."),
            ),
            ("Demand may be rising faster than restored capacity.", "The restoration may be temporary."),
        ),
        EventCausalRule(
            "physical-supply-disruption",
            "physical supply disruption",
            (PortfolioImpactChannel.SUPPLY, PortfolioImpactChannel.COMMODITY),
            ("production cut", "shutdown", "outage", "inventory draw", "export ban"),
            ("Available supply or transport capacity falls.", "Scarcity and input-cost pressure may rise."),
            (
                _t("affected_commodity", positive, 0.55, "Lower available supply can increase scarcity pricing."),
                _t("commodity_consumers", negative, 0.45, "Higher input costs can pressure margins and demand."),
                _t("commodity_producers", positive, 0.35, "Higher realized pricing can support producer economics."),
            ),
            ("Inventories or substitute supply may offset the disruption.", "Demand may weaken concurrently."),
        ),
        EventCausalRule(
            "inflation-upside",
            "inflation upside surprise",
            (PortfolioImpactChannel.INFLATION, PortfolioImpactChannel.DISCOUNT_RATE),
            ("inflation accelerated", "hotter inflation", "cpi above", "ppi above", "wage pressure"),
            ("Expected inflation or policy persistence rises.", "Real and nominal discount-rate pressure may increase."),
            (
                _t("inflation_expectations", positive, 0.60, "Stronger price pressure can lift expected inflation."),
                _t("bond_prices", negative, 0.55, "Higher expected rates can pressure duration."),
                _t("growth_equities", negative, 0.50, "Higher discount rates can reduce long-duration valuations."),
            ),
            ("The increase may be concentrated or temporary.", "Growth deterioration may dominate the rate effect."),
        ),
        EventCausalRule(
            "inflation-downside",
            "inflation downside surprise",
            (PortfolioImpactChannel.INFLATION, PortfolioImpactChannel.DISCOUNT_RATE),
            ("inflation cooled", "disinflation", "cpi below", "ppi below", "price pressure eased"),
            ("Expected inflation or policy persistence declines.", "Discount-rate pressure may ease."),
            (
                _t("inflation_expectations", negative, 0.55, "Cooling price pressure can lower expected inflation."),
                _t("bond_prices", positive, 0.55, "Lower expected rates can support duration."),
                _t("growth_equities", positive, 0.45, "Lower discount rates can support long-duration valuations."),
            ),
            ("Cooling inflation may reflect weakening demand.", "Policy may remain restrictive despite one release."),
        ),
        EventCausalRule(
            "monetary-easing",
            "monetary-policy easing",
            (PortfolioImpactChannel.POLICY, PortfolioImpactChannel.LIQUIDITY),
            ("rate cut", "policy easing", "quantitative easing", "liquidity facility", "dovish guidance"),
            ("Policy or liquidity restraint declines.", "Financing and discount-rate pressure may ease."),
            (
                _t("bond_prices", positive, 0.50, "Lower expected policy rates can support duration."),
                _t("growth_equities", positive, 0.40, "Lower discount rates can support valuations."),
                _t("credit", positive, 0.35, "Improved financing conditions can support credit."),
                _t("us_dollar", negative, 0.25, "Lower relative yields may reduce currency support."),
            ),
            ("Easing may respond to severe growth or financial stress.", "Markets may have fully priced the action."),
        ),
        EventCausalRule(
            "monetary-tightening",
            "monetary-policy tightening",
            (PortfolioImpactChannel.POLICY, PortfolioImpactChannel.LIQUIDITY),
            ("rate hike", "quantitative tightening", "hawkish guidance", "liquidity withdrawal", "higher for longer"),
            ("Policy or liquidity restraint rises.", "Financing and discount-rate pressure may increase."),
            (
                _t("bond_prices", negative, 0.50, "Higher expected policy rates can pressure duration."),
                _t("growth_equities", negative, 0.45, "Higher discount rates can pressure valuations."),
                _t("credit", negative, 0.35, "Tighter financing conditions can pressure credit."),
                _t("us_dollar", positive, 0.25, "Higher relative yields may support the currency."),
            ),
            ("Tightening may validate strong nominal growth.", "Markets may have fully priced the action."),
        ),
        EventCausalRule(
            "growth-improvement",
            "growth improvement",
            (PortfolioImpactChannel.GROWTH, PortfolioImpactChannel.DEMAND),
            ("growth accelerated", "gdp above", "payrolls above", "orders rose", "demand improved"),
            ("Expected activity and cash flow improve.", "Cyclical demand and credit quality may strengthen."),
            (
                _t("broad_equities", positive, 0.45, "Higher expected activity can support earnings."),
                _t("cyclical_equities", positive, 0.55, "Cyclicals are directly exposed to activity improvement."),
                _t("credit", positive, 0.40, "Stronger cash flow can improve debt service capacity."),
                _t("bond_prices", negative, 0.20, "Stronger growth can increase expected yields."),
            ),
            ("The improvement may be inventory- or stimulus-driven.", "Inflation or rates may offset the earnings benefit."),
        ),
        EventCausalRule(
            "growth-deterioration",
            "growth deterioration",
            (PortfolioImpactChannel.GROWTH, PortfolioImpactChannel.DEMAND),
            ("recession", "contraction", "layoffs", "gdp below", "orders fell", "demand weakened"),
            ("Expected activity and cash flow weaken.", "Cyclical demand and credit quality may deteriorate."),
            (
                _t("broad_equities", negative, 0.50, "Lower expected activity can pressure earnings."),
                _t("cyclical_equities", negative, 0.60, "Cyclicals are directly exposed to activity weakness."),
                _t("credit", negative, 0.45, "Weaker cash flow can pressure debt service capacity."),
                _t("bond_prices", positive, 0.30, "Lower growth can reduce expected yields and support safe duration."),
            ),
            ("Policy support may offset the slowdown.", "The weakness may be temporary or narrowly concentrated."),
        ),
        EventCausalRule(
            "corporate-upside",
            "corporate earnings or guidance upside",
            (PortfolioImpactChannel.EARNINGS,),
            ("earnings beat", "raised guidance", "revenue beat", "margin expansion", "contract award"),
            ("Expected issuer cash flow improves.", "Peers, suppliers, or customers may receive read-through effects."),
            (
                _t("affected_issuer", positive, 0.65, "Higher expected cash flow can support issuer value."),
                _t("affected_sector", positive, 0.25, "The result may improve sector expectations."),
                _t("issuer_credit", positive, 0.30, "Improved cash flow can support credit quality."),
            ),
            ("The upside may already be priced.", "One-time items may explain the result."),
        ),
        EventCausalRule(
            "corporate-downside",
            "corporate earnings or guidance downside",
            (PortfolioImpactChannel.EARNINGS,),
            ("earnings miss", "cut guidance", "revenue miss", "margin pressure", "contract loss"),
            ("Expected issuer cash flow weakens.", "Peers, suppliers, or customers may receive read-through effects."),
            (
                _t("affected_issuer", negative, 0.65, "Lower expected cash flow can pressure issuer value."),
                _t("affected_sector", negative, 0.25, "The result may weaken sector expectations."),
                _t("issuer_credit", negative, 0.30, "Weaker cash flow can pressure credit quality."),
            ),
            ("The disappointment may be temporary.", "Expectations may already be sufficiently low."),
        ),
        EventCausalRule(
            "financial-stress",
            "financial-system or credit stress",
            (PortfolioImpactChannel.CREDIT, PortfolioImpactChannel.COUNTERPARTY),
            ("bank run", "default", "funding stress", "rescue", "credit event", "liquidity crisis"),
            ("Counterparty or refinancing risk rises.", "Risk appetite and credit availability may contract."),
            (
                _t("financials", negative, 0.60, "Higher funding and loss risk can pressure financial institutions."),
                _t("credit", negative, 0.55, "Higher default and liquidity risk can widen spreads."),
                _t("volatility", positive, 0.55, "System uncertainty can raise volatility premia."),
                _t("bond_prices", positive, 0.25, "Safe-duration demand may rise."),
            ),
            ("A credible backstop may contain contagion.", "The event may be issuer-specific rather than systemic."),
        ),
        EventCausalRule(
            "operational-cyber-disruption",
            "operational or cyber disruption",
            (PortfolioImpactChannel.OPERATIONAL, PortfolioImpactChannel.CYBER),
            ("ransomware", "cyberattack", "data breach", "factory shutdown", "service outage"),
            ("Operations, customer access, or production capacity are impaired.", "Direct costs and reputational risk may rise."),
            (
                _t("affected_issuer", negative, 0.50, "Operational interruption can reduce cash flow and raise costs."),
                _t("affected_customers", negative, 0.25, "Dependent customers may experience delays or losses."),
                _t("cybersecurity_vendors", positive, 0.20, "Security demand may increase after a material incident."),
            ),
            ("The disruption may be rapidly contained.", "Insurance or redundancy may limit economic damage."),
        ),
        EventCausalRule(
            "regulatory-approval",
            "regulatory approval or permit",
            (PortfolioImpactChannel.REGULATION,),
            ("approved", "permit granted", "authorization granted", "cleared by regulator"),
            ("A legal or operational constraint is removed.", "Expected commercialization or capacity may improve."),
            (
                _t("affected_issuer", positive, 0.50, "Approval can improve expected cash flow or reduce uncertainty."),
                _t("affected_sector", positive, 0.20, "The decision may improve sector precedent."),
            ),
            ("Commercial adoption or economics may still disappoint.", "Conditions attached to approval may be material."),
        ),
        EventCausalRule(
            "regulatory-enforcement",
            "regulatory enforcement or adverse ruling",
            (PortfolioImpactChannel.REGULATION,),
            ("enforcement action", "fine", "injunction", "approval denied", "permit revoked", "antitrust action"),
            ("A legal, cost, or operating constraint increases.", "Expected cash flow or strategic flexibility may decline."),
            (
                _t("affected_issuer", negative, 0.50, "Enforcement can reduce cash flow or strategic flexibility."),
                _t("affected_sector", negative, 0.20, "The decision may create adverse sector precedent."),
            ),
            ("The action may be appealed or financially immaterial.", "Competitors may benefit from the constraint."),
        ),
    )


class EventToForwardEngine:
    """Analyze public events and emit only governed forward-intelligence evidence."""

    def __init__(
        self,
        policy: EventMarketPolicy | None = None,
        *,
        catalog: EventRuleCatalog | None = None,
    ) -> None:
        self.policy = policy or EventMarketPolicy()
        self.catalog = catalog or EventRuleCatalog()

    def assess(
        self,
        record: DecisionInformationRecord,
        *,
        event_cluster: EventClusterAssessment,
        observations: tuple[MarketObservation, ...],
        assessed_at: datetime,
    ) -> EventMarketAssessment:
        if not isinstance(record, DecisionInformationRecord):
            raise TypeError("record must be DecisionInformationRecord")
        if not isinstance(event_cluster, EventClusterAssessment):
            raise TypeError("event_cluster must be EventClusterAssessment")
        timestamp = _aware(assessed_at, field_name="assessed_at")
        record.require_available_to(timestamp)
        if not isinstance(observations, tuple) or not all(
            isinstance(item, MarketObservation) for item in observations
        ):
            raise TypeError("observations must contain MarketObservation values")
        if any(item.observed_at > timestamp for item in observations):
            raise ValueError("market observations cannot be future-known")

        base_evidence = _unique(
            (
                record.identifier,
                record.provenance.source_identifier,
                *record.corroborating_source_identifiers,
                *event_cluster.source_identifiers,
            )
        )
        quality_blocked = record.provenance.quality_state in {
            InformationQualityState.DISPUTED,
            InformationQualityState.UNVERIFIED,
            InformationQualityState.MISSING,
        }
        eligible_for_analysis = event_cluster.eligible_for_analysis and not quality_blocked
        major_event = (
            record.materiality >= self.policy.minimum_major_event_materiality
            or event_cluster.materiality >= self.policy.minimum_major_event_materiality
        )
        drivers = (
            self.catalog.match(record, minimum_score=self.policy.minimum_rule_score)
            if eligible_for_analysis
            else ()
        )
        predicted = self._aggregate_transmissions(drivers)
        unresolved_questions: tuple[str, ...] = ()
        alternatives = _unique(item for driver in drivers for item in driver.alternatives)
        causal_chain = _unique(item for driver in drivers for item in driver.causal_chain)

        if not eligible_for_analysis:
            state = EventCausalState.ANALYSIS_BLOCKED
            unresolved_questions = (
                "Which reliability, relevance, materiality, or evidence-quality condition must improve?",
            )
        elif not drivers and major_event:
            state = EventCausalState.UNRESOLVED_MAJOR_EVENT
            causal_chain = (
                "A material event was detected, but the available evidence does not establish a defensible directional causal chain.",
                "The event remains monitored without fabricated market direction.",
            )
            alternatives = (
                "The event may operate through a mechanism outside the current versioned rule catalog.",
                "The headline may omit facts needed to determine direction, magnitude, timing, or exposure.",
            )
            unresolved_questions = (
                "What economic variable, cash flow, risk premium, or physical constraint changed?",
                "Which issuers, sectors, regions, commodities, or counterparties are directly exposed?",
                "What point-in-time market evidence confirms the proposed direction?",
            )
            predicted = self._fallback_transmissions(record)
        elif not drivers:
            state = EventCausalState.UNKNOWN
        else:
            state = EventCausalState.MAPPED

        transmissions, confirmation, coverage, contradictions = self._confirm(
            predicted,
            observations,
            base_evidence=base_evidence,
        )
        if drivers and any(
            item.direction is TransmissionDirection.MIXED for item in transmissions
        ):
            state = EventCausalState.MIXED
        driver_confidence = (
            sum(item.confidence for item in drivers) / len(drivers)
            if drivers
            else 0.0
        )
        confidence = round(
            min(
                1.0,
                0.30 * record.evidence_strength
                + 0.25 * event_cluster.quality_score
                + 0.25 * driver_confidence
                + 0.20 * confirmation,
            ),
            8,
        )
        material_directional = any(
            item.direction in {
                TransmissionDirection.POSITIVE,
                TransmissionDirection.NEGATIVE,
                TransmissionDirection.MIXED,
            }
            and item.magnitude >= 0.20
            for item in transmissions
        )
        eligible_for_cio_context = (
            eligible_for_analysis
            and bool(drivers)
            and material_directional
            and event_cluster.eligible_for_cio_context
            and confirmation >= self.policy.minimum_market_confirmation
            and coverage >= self.policy.minimum_confirmation_coverage
            and confidence >= self.policy.minimum_assessment_confidence
        )
        requires_causal_review = (
            major_event
            and (
                not drivers
                or bool(contradictions)
                or coverage < self.policy.minimum_confirmation_coverage
            )
        )
        material = "|".join(
            (
                record.identifier,
                event_cluster.identifier,
                self.catalog.version,
                *(item.rule_identifier for item in drivers),
                *(item.identifier for item in observations),
            )
        )
        identifier = "event-market:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        evidence_identifiers = _unique(
            (
                *base_evidence,
                *(item.identifier for item in observations),
                *(
                    evidence
                    for observation in observations
                    for evidence in observation.evidence_identifiers
                ),
            )
        )
        return EventMarketAssessment(
            identifier=identifier,
            information_identifier=record.identifier,
            event_cluster_identifier=event_cluster.identifier,
            assessed_at=timestamp,
            state=state,
            drivers=drivers,
            causal_chain=causal_chain,
            transmissions=transmissions,
            market_confirmation=confirmation,
            confirmation_coverage=coverage,
            confidence=confidence,
            major_event=major_event,
            requires_causal_review=requires_causal_review,
            contradictory_evidence=contradictions,
            alternative_explanations=alternatives,
            unresolved_questions=unresolved_questions,
            evidence_identifiers=evidence_identifiers,
            eligible_for_analysis=eligible_for_analysis,
            eligible_for_cio_context=eligible_for_cio_context,
            policy_version=self.policy.version,
        )

    def build_forward_bundles(
        self,
        assessment: EventMarketAssessment,
        *,
        candidate_exposure_map: Mapping[str, Sequence[str]],
    ) -> tuple[ForwardIntelligenceBundle, ...]:
        """Map strictly escalated event evidence into the active specialist contract."""

        if not isinstance(assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        if not assessment.eligible_for_cio_context:
            return ()
        by_candidate: dict[str, list[MarketTransmission]] = {}
        for transmission in assessment.transmissions:
            for raw_candidate in candidate_exposure_map.get(
                transmission.target_identifier,
                (),
            ):
                candidate = _text(raw_candidate, field_name="candidate identifier")
                by_candidate.setdefault(candidate, []).append(transmission)

        bundles = []
        for candidate_identifier, transmissions in sorted(by_candidate.items()):
            weight = sum(max(item.confidence * item.magnitude, 0.01) for item in transmissions)
            impact = (
                sum(
                    item.directional_score
                    * max(item.confidence * item.magnitude, 0.01)
                    for item in transmissions
                )
                / weight
                if weight
                else 0.0
            )
            confidence = min(item.confidence for item in transmissions)
            channels = self._specialist_channels(transmissions)
            signal = ForwardSignal(
                identifier=f"signal:event:{assessment.identifier}:{candidate_identifier}",
                as_of=assessment.assessed_at,
                name="governed event-to-market transmission",
                channels=channels,
                expected_return_impact=_clamp(impact, -0.25, 0.25),
                confidence=confidence,
                evidence=_unique(
                    (
                        *assessment.causal_chain,
                        *(
                            f"{item.target_identifier}: {item.direction.value}; {item.mechanism}"
                            for item in transmissions
                        ),
                    )
                ),
                contradictory_evidence=assessment.contradictory_evidence,
                assumptions=(
                    "The identified causal mechanism remains applicable to the candidate exposure.",
                    "Market observations are contemporaneous and not dominated by an unrelated cause.",
                ),
                risks=_unique(
                    (
                        *assessment.alternative_explanations,
                        "Event effects can change as facts, implementation, positioning, and market pricing evolve.",
                    )
                ),
                change_conditions=(
                    "Reassess when the event is corrected, superseded, contradicted, implemented differently, or no longer confirmed by exposed markets.",
                ),
                evidence_identifiers=assessment.evidence_identifiers,
            )
            bundles.append(
                ForwardIntelligenceBundle(
                    identifier=f"forward:event:{assessment.identifier}:{candidate_identifier}",
                    candidate_identifier=candidate_identifier,
                    as_of=assessment.assessed_at,
                    signals=(signal,),
                    scenarios=(),
                    diagnostics=(
                        f"Event state={assessment.state.value}",
                        f"Market confirmation={assessment.market_confirmation:.0%}",
                        f"Confirmation coverage={assessment.confirmation_coverage:.0%}",
                        "Event evidence is advisory to the existing six specialists and CIO-only process.",
                    ),
                    model_versions=(
                        assessment.policy_version,
                        self.catalog.version,
                    ),
                )
            )
        return tuple(bundles)

    @staticmethod
    def _specialist_channels(
        transmissions: Sequence[MarketTransmission],
    ) -> tuple[str, ...]:
        channels: list[str] = ["market", "forecast"]
        macro_targets = {
            "broad_equities",
            "cyclical_equities",
            "bond_prices",
            "credit",
            "inflation_expectations",
            "us_dollar",
            "affected_commodity",
            "volatility",
        }
        fundamental_targets = {
            "affected_issuer",
            "affected_sector",
            "issuer_credit",
            "commodity_consumers",
            "commodity_producers",
            "financials",
            "affected_customers",
            "cybersecurity_vendors",
        }
        targets = {item.target_identifier for item in transmissions}
        if targets.intersection(macro_targets):
            channels.append("macro")
        if targets.intersection(fundamental_targets):
            channels.append("fundamental")
        return tuple(dict.fromkeys(channels))

    def _fallback_transmissions(
        self,
        record: DecisionInformationRecord,
    ) -> tuple[RuleTransmission, ...]:
        target_by_channel = {
            PortfolioImpactChannel.GROWTH: ("broad_equities", "credit"),
            PortfolioImpactChannel.INFLATION: ("bond_prices", "inflation_expectations"),
            PortfolioImpactChannel.POLICY: ("bond_prices", "us_dollar"),
            PortfolioImpactChannel.LIQUIDITY: ("credit", "volatility"),
            PortfolioImpactChannel.EARNINGS: ("affected_issuer", "affected_sector"),
            PortfolioImpactChannel.CREDIT: ("credit", "financials"),
            PortfolioImpactChannel.SUPPLY: ("affected_commodity", "commodity_consumers"),
            PortfolioImpactChannel.DEMAND: ("cyclical_equities", "credit"),
            PortfolioImpactChannel.COMMODITY: ("affected_commodity",),
            PortfolioImpactChannel.CURRENCY: ("us_dollar",),
            PortfolioImpactChannel.VOLATILITY: ("volatility", "broad_equities"),
            PortfolioImpactChannel.REGULATION: ("affected_issuer", "affected_sector"),
            PortfolioImpactChannel.GEOPOLITICAL: ("volatility", "affected_commodity"),
            PortfolioImpactChannel.OPERATIONAL: ("affected_issuer",),
            PortfolioImpactChannel.CYBER: ("affected_issuer", "cybersecurity_vendors"),
            PortfolioImpactChannel.CLIMATE_WEATHER: ("affected_commodity", "affected_sector"),
            PortfolioImpactChannel.POSITIONING: ("volatility",),
            PortfolioImpactChannel.SENTIMENT: ("affected_issuer", "broad_equities"),
            PortfolioImpactChannel.COUNTERPARTY: ("credit", "financials"),
            PortfolioImpactChannel.DISCOUNT_RATE: ("bond_prices", "growth_equities"),
        }
        targets = _unique(
            target
            for channel in record.impact_channels
            for target in target_by_channel.get(channel, ())
        ) or ("broad_equities",)
        return tuple(
            RuleTransmission(
                target_identifier=target,
                direction=TransmissionDirection.NEUTRAL,
                magnitude=0.10,
                mechanism="Direction is unresolved; additional causal evidence is required.",
                horizon="unresolved",
            )
            for target in targets
        )

    def _aggregate_transmissions(
        self,
        drivers: tuple[CausalDriver, ...],
    ) -> tuple[RuleTransmission, ...]:
        grouped: dict[str, list[tuple[CausalDriver, RuleTransmission]]] = {}
        for driver in drivers:
            for transmission in driver.transmissions:
                grouped.setdefault(transmission.target_identifier, []).append(
                    (driver, transmission)
                )
        result = []
        for target, values in sorted(grouped.items()):
            positive = sum(
                transmission.magnitude * driver.confidence
                for driver, transmission in values
                if transmission.direction is TransmissionDirection.POSITIVE
            )
            negative = sum(
                transmission.magnitude * driver.confidence
                for driver, transmission in values
                if transmission.direction is TransmissionDirection.NEGATIVE
            )
            total = positive + negative
            if total <= 0.0:
                direction = TransmissionDirection.NEUTRAL
                magnitude = 0.0
            elif (
                positive > 0.0
                and negative > 0.0
                and min(positive, negative) / max(positive, negative)
                >= self.policy.mixed_direction_conflict_ratio
            ):
                direction = TransmissionDirection.MIXED
                magnitude = min(1.0, max(positive, negative) / max(len(values), 1))
            elif positive > negative:
                direction = TransmissionDirection.POSITIVE
                magnitude = min(1.0, (positive - negative) / max(len(values), 1))
            elif negative > positive:
                direction = TransmissionDirection.NEGATIVE
                magnitude = min(1.0, (negative - positive) / max(len(values), 1))
            else:
                direction = TransmissionDirection.NEUTRAL
                magnitude = 0.0
            result.append(
                RuleTransmission(
                    target_identifier=target,
                    direction=direction,
                    magnitude=round(magnitude, 8),
                    mechanism=" | ".join(
                        _unique(item.mechanism for _, item in values)
                    ),
                    horizon=",".join(_unique(item.horizon for _, item in values)),
                )
            )
        return tuple(result)

    def _confirm(
        self,
        predicted: tuple[RuleTransmission, ...],
        observations: tuple[MarketObservation, ...],
        *,
        base_evidence: tuple[str, ...],
    ) -> tuple[tuple[MarketTransmission, ...], float, float, tuple[str, ...]]:
        by_target: dict[str, list[MarketObservation]] = {}
        for item in observations:
            by_target.setdefault(item.exposure_identifier, []).append(item)
        transmissions = []
        confirmation_values: list[tuple[float, float]] = []
        observable_weight = sum(
            item.magnitude
            for item in predicted
            if item.direction in {
                TransmissionDirection.POSITIVE,
                TransmissionDirection.NEGATIVE,
            }
            and item.magnitude > 0.0
        )
        observed_weight = 0.0
        contradictions = []
        for item in predicted:
            relevant = by_target.get(item.target_identifier, [])
            target_values = []
            if item.direction.sign != 0.0:
                for observation in relevant:
                    strength = min(
                        abs(observation.return_change)
                        / self.policy.full_confirmation_move,
                        1.0,
                    )
                    if abs(observation.return_change) < self.policy.minimum_observed_move:
                        strength = 0.0
                    if observation.return_change * item.direction.sign > 0.0:
                        target_values.append(strength)
                    elif observation.return_change * item.direction.sign < 0.0:
                        target_values.append(0.0)
                        contradictions.append(
                            f"{item.target_identifier} moved {observation.return_change:+.4f}, opposite the expected {item.direction.value} direction."
                        )
                if relevant:
                    observed_weight += item.magnitude
            target_confirmation = (
                sum(target_values) / len(target_values) if target_values else 0.0
            )
            if relevant and item.direction.sign != 0.0:
                confirmation_values.append((target_confirmation, item.magnitude))
            evidence = _unique(
                (
                    *base_evidence,
                    *(observation.identifier for observation in relevant),
                    *(
                        identifier
                        for observation in relevant
                        for identifier in observation.evidence_identifiers
                    ),
                )
            )
            confidence = min(
                1.0,
                0.50 + 0.30 * item.magnitude + 0.20 * target_confirmation,
            )
            transmissions.append(
                MarketTransmission(
                    target_identifier=item.target_identifier,
                    direction=item.direction,
                    magnitude=item.magnitude,
                    confidence=round(confidence, 8),
                    mechanism=item.mechanism,
                    horizon=item.horizon,
                    contributing_driver_identifiers=(),
                    evidence_identifiers=evidence,
                )
            )
        total_weight = sum(weight for _, weight in confirmation_values)
        confirmation = (
            sum(value * weight for value, weight in confirmation_values) / total_weight
            if total_weight
            else 0.0
        )
        coverage = (
            min(1.0, observed_weight / observable_weight)
            if observable_weight > 0.0
            else 0.0
        )
        return (
            tuple(transmissions),
            round(confirmation, 8),
            round(coverage, 8),
            _unique(contradictions),
        )


class SQLiteEventMarketStore:
    """Idempotent append-only persistence for event-market assessments."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_market_assessments (
                    identifier TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS event_market_no_update
                BEFORE UPDATE ON event_market_assessments
                BEGIN SELECT RAISE(ABORT, 'event-market assessments are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS event_market_no_delete
                BEFORE DELETE ON event_market_assessments
                BEGIN SELECT RAISE(ABORT, 'event-market assessments are append-only'); END;
                """
            )

    def append(
        self,
        assessment: EventMarketAssessment,
        *,
        recorded_at: datetime,
    ) -> None:
        if not isinstance(assessment, EventMarketAssessment):
            raise TypeError("assessment must be EventMarketAssessment")
        timestamp = _aware(recorded_at, field_name="recorded_at")
        payload = json.dumps(
            assessment.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT payload_hash FROM event_market_assessments WHERE identifier = ?",
                (assessment.identifier,),
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ValueError(
                        "event-market identifier already exists with different content"
                    )
                return
            connection.execute(
                "INSERT INTO event_market_assessments VALUES (?, ?, ?, ?)",
                (assessment.identifier, timestamp.isoformat(), payload, digest),
            )


__all__ = [
    "CausalDriver",
    "EventCausalRule",
    "EventCausalState",
    "EventMarketAssessment",
    "EventMarketPolicy",
    "EventRuleCatalog",
    "EventToForwardEngine",
    "MarketObservation",
    "MarketTransmission",
    "RuleTransmission",
    "SQLiteEventMarketStore",
    "TransmissionDirection",
    "default_event_rules",
]
