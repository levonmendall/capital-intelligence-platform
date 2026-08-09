"""Global bull-market rotation discovery and governed exposure mapping.

This module searches the complete point-in-time research universe for persistent
leadership and rotation. It is intentionally upstream and advisory: it can create
research nominations and forward evidence, but it cannot qualify a candidate,
authorize capital, size a portfolio, or place an order.

The canonical exposure graph only records relationships supported by governed
instrument metadata or explicitly supplied reviewed edges. It never infers a
supplier/customer/theme relationship from text or price action.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite, tanh
from typing import Iterable, Mapping, Sequence

from cio.models import CandidateAssetClass
from intelligence.event_market_forward import EventMarketAssessment
from intelligence.forward import ForwardIntelligenceBundle, ForwardSignal, TrendStage
from intelligence.forward_research import (
    ForwardOpportunityDiscoveryEngine,
    ForwardOpportunityHypothesis,
    ResearchExposure,
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


def _number(
    value: object,
    *,
    field_name: str,
    low: float | None = None,
    high: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    if low is not None and result < low:
        raise ValueError(f"{field_name} must be at least {low}")
    if high is not None and result > high:
        raise ValueError(f"{field_name} must be at most {high}")
    return round(result, 8)


def _ratio(value: object, *, field_name: str) -> float:
    return _number(value, field_name=field_name, low=0.0, high=1.0)


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, float(value))), 8)


def _texts(values: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    result = tuple(_text(item, field_name=field_name) for item in values)
    if len(result) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


class BullMarketStage(str, Enum):
    EMERGING = "emerging_bull"
    CONFIRMED = "confirmed_bull"
    MATURE = "mature_bull"
    CROWDED_FRAGILE = "crowded_fragile_bull"
    DETERIORATING = "deteriorating"
    BEAR = "bear"


class ExposureNodeKind(str, Enum):
    INSTRUMENT = "instrument"
    ASSET_CLASS = "asset_class"
    ECONOMIC_EXPOSURE = "economic_exposure"
    COUNTRY = "country"
    CURRENCY = "currency"
    VENUE = "venue"
    UNDERLYING = "underlying"
    SECTOR = "sector"
    INDUSTRY = "industry"
    THEME = "theme"
    ISSUER = "issuer"
    PRODUCT = "product"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    COMMODITY = "commodity"


@dataclass(frozen=True, slots=True)
class RadarObservation:
    candidate_identifier: str
    instrument_identifier: str
    symbol: str
    as_of: datetime
    asset_class: CandidateAssetClass
    economic_exposure: str
    country_code: str
    currency: str
    venue: str
    one_month_return: float
    three_month_return: float
    six_month_return: float
    twelve_month_return: float
    annualized_volatility: float
    maximum_drawdown: float
    liquidity_score: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "candidate_identifier",
            "instrument_identifier",
            "symbol",
            "economic_exposure",
            "country_code",
            "currency",
            "venue",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "country_code", self.country_code.upper())
        object.__setattr__(self, "currency", self.currency.upper())
        object.__setattr__(self, "venue", self.venue.upper())
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        for name in (
            "one_month_return",
            "three_month_return",
            "six_month_return",
            "twelve_month_return",
            "annualized_volatility",
            "maximum_drawdown",
        ):
            object.__setattr__(
                self,
                name,
                _number(getattr(self, name), field_name=name, low=-5.0, high=10.0),
            )
        object.__setattr__(
            self,
            "liquidity_score",
            _ratio(self.liquidity_score, field_name="liquidity_score"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )

    @property
    def weighted_return(self) -> float:
        return round(
            0.15 * self.one_month_return
            + 0.25 * self.three_month_return
            + 0.25 * self.six_month_return
            + 0.35 * self.twelve_month_return,
            8,
        )


@dataclass(frozen=True, slots=True)
class BullMarketAssessment:
    candidate_identifier: str
    instrument_identifier: str
    symbol: str
    as_of: datetime
    stage: BullMarketStage
    score: float
    rank: int
    trend_score: float
    relative_strength: float
    breadth: float
    acceleration: float
    durability: float
    drawdown_resilience: float
    liquidity_score: float
    trend_crowding_proxy: float
    horizon_scores: tuple[tuple[str, float], ...]
    evidence_identifiers: tuple[str, ...]
    research_only: bool = True
    authorizes_capital: bool = False
    schema_version: str = "global-bull-market-assessment.v1"

    def __post_init__(self) -> None:
        for name in ("candidate_identifier", "instrument_identifier", "symbol", "schema_version"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        object.__setattr__(self, "symbol", self.symbol.upper())
        _aware(self.as_of, field_name="as_of")
        if not isinstance(self.stage, BullMarketStage):
            raise TypeError("stage must be BullMarketStage")
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        for name in (
            "score",
            "trend_score",
            "relative_strength",
            "breadth",
            "durability",
            "drawdown_resilience",
            "liquidity_score",
            "trend_crowding_proxy",
        ):
            object.__setattr__(self, name, _ratio(getattr(self, name), field_name=name))
        object.__setattr__(
            self,
            "acceleration",
            _number(self.acceleration, field_name="acceleration", low=-1.0, high=1.0),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class GlobalOpportunityRadarReport:
    as_of: datetime
    assessments: tuple[BullMarketAssessment, ...]
    exposure_breadth: tuple[tuple[str, float], ...]
    asset_class_breadth: tuple[tuple[str, float], ...]
    evidence_identifiers: tuple[str, ...]
    diagnostics: tuple[str, ...]
    authorizes_capital: bool = False
    version: str = "global-opportunity-radar.v1"

    @property
    def by_candidate(self) -> dict[str, BullMarketAssessment]:
        return {item.candidate_identifier: item for item in self.assessments}


class GlobalBullMarketRadarEngine:
    """Rank global leadership without creating a portfolio action."""

    version = "global-opportunity-radar.v1"

    _SCALES = {
        "1m": 0.08,
        "3m": 0.15,
        "6m": 0.25,
        "12m": 0.40,
    }

    @staticmethod
    def _return_score(value: float, scale: float) -> float:
        return _clip(0.5 + 0.5 * tanh(value / max(scale, 1e-9)))

    @staticmethod
    def _percentiles(values: Mapping[str, float]) -> dict[str, float]:
        ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
        if len(ordered) <= 1:
            return {key: 0.5 for key, _ in ordered}
        return {
            key: round(index / (len(ordered) - 1), 8)
            for index, (key, _value) in enumerate(ordered)
        }

    @staticmethod
    def _breadth(observations: Sequence[RadarObservation], attribute: str) -> dict[str, float]:
        grouped: dict[str, list[RadarObservation]] = {}
        for item in observations:
            grouped.setdefault(str(getattr(item, attribute)), []).append(item)
        result: dict[str, float] = {}
        for key, values in grouped.items():
            positive = sum(
                1
                for item in values
                if item.three_month_return > 0.0 and item.twelve_month_return > 0.0
            )
            result[key] = round(positive / len(values), 8)
        return result

    @staticmethod
    def _stage(
        item: RadarObservation,
        *,
        score: float,
        breadth: float,
        acceleration: float,
        crowding: float,
    ) -> BullMarketStage:
        long_positive = item.six_month_return > 0.0 and item.twelve_month_return > 0.0
        short_positive = item.one_month_return > 0.0 and item.three_month_return > 0.0
        if item.three_month_return < 0.0 and item.twelve_month_return < 0.0:
            return BullMarketStage.BEAR
        if long_positive and item.one_month_return < 0.0 and acceleration < -0.10:
            return BullMarketStage.DETERIORATING
        if short_positive and acceleration > 0.12 and score >= 0.55 and not long_positive:
            return BullMarketStage.EMERGING
        if long_positive and short_positive and score >= 0.67:
            if crowding >= 0.82 and acceleration <= 0.08:
                return BullMarketStage.CROWDED_FRAGILE
            if acceleration < -0.05:
                return BullMarketStage.MATURE
            return BullMarketStage.CONFIRMED
        if long_positive and score >= 0.56 and breadth >= 0.45:
            return BullMarketStage.MATURE
        if score < 0.38:
            return BullMarketStage.BEAR
        return BullMarketStage.DETERIORATING

    def scan(self, observations: tuple[RadarObservation, ...]) -> GlobalOpportunityRadarReport:
        if not observations:
            raise ValueError("global radar requires at least one observation")
        as_of = observations[0].as_of
        if any(item.as_of != as_of for item in observations):
            raise ValueError("global radar observations must share as_of")
        candidate_ids = tuple(item.candidate_identifier for item in observations)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("global radar candidate identifiers must be unique")

        exposure_breadth = self._breadth(observations, "economic_exposure")
        asset_breadth = self._breadth(observations, "asset_class")
        relative = self._percentiles(
            {item.candidate_identifier: item.weighted_return for item in observations}
        )
        raw: list[tuple[RadarObservation, dict[str, float]]] = []
        for item in observations:
            horizon = {
                "1m": self._return_score(item.one_month_return, self._SCALES["1m"]),
                "3m": self._return_score(item.three_month_return, self._SCALES["3m"]),
                "6m": self._return_score(item.six_month_return, self._SCALES["6m"]),
                "12m": self._return_score(item.twelve_month_return, self._SCALES["12m"]),
            }
            trend = round(
                0.15 * horizon["1m"]
                + 0.25 * horizon["3m"]
                + 0.25 * horizon["6m"]
                + 0.35 * horizon["12m"],
                8,
            )
            acceleration = _clip(
                (
                    0.55 * item.one_month_return
                    + 0.45 * item.three_month_return
                    - 0.35 * item.six_month_return
                    - 0.25 * item.twelve_month_return
                ) / 0.25,
                -1.0,
                1.0,
            )
            positive_horizons = sum(
                value > 0.0
                for value in (
                    item.one_month_return,
                    item.three_month_return,
                    item.six_month_return,
                    item.twelve_month_return,
                )
            )
            volatility_penalty = _clip(item.annualized_volatility / 1.0)
            durability = _clip(positive_horizons / 4.0 * (1.0 - 0.25 * volatility_penalty))
            drawdown_resilience = _clip(1.0 - abs(min(0.0, item.maximum_drawdown)) / 0.60)
            group_breadth = round(
                0.6 * exposure_breadth[item.economic_exposure]
                + 0.4 * asset_breadth[str(item.asset_class)],
                8,
            )
            rel = relative[item.candidate_identifier]
            acceleration_score = _clip(0.5 + 0.5 * acceleration)
            crowding = _clip(
                0.55 * rel
                + 0.25 * horizon["1m"]
                + 0.20 * volatility_penalty
            )
            score = round(
                0.22 * trend
                + 0.18 * rel
                + 0.15 * group_breadth
                + 0.14 * acceleration_score
                + 0.12 * durability
                + 0.10 * drawdown_resilience
                + 0.09 * item.liquidity_score,
                8,
            )
            raw.append(
                (
                    item,
                    {
                        "trend": trend,
                        "relative": rel,
                        "breadth": group_breadth,
                        "acceleration": acceleration,
                        "durability": durability,
                        "drawdown": drawdown_resilience,
                        "crowding": crowding,
                        "score": score,
                        **horizon,
                    },
                )
            )
        raw.sort(key=lambda value: (value[1]["score"], value[0].symbol), reverse=True)
        assessments: list[BullMarketAssessment] = []
        for rank, (item, metrics) in enumerate(raw, start=1):
            stage = self._stage(
                item,
                score=metrics["score"],
                breadth=metrics["breadth"],
                acceleration=metrics["acceleration"],
                crowding=metrics["crowding"],
            )
            assessments.append(
                BullMarketAssessment(
                    candidate_identifier=item.candidate_identifier,
                    instrument_identifier=item.instrument_identifier,
                    symbol=item.symbol,
                    as_of=as_of,
                    stage=stage,
                    score=metrics["score"],
                    rank=rank,
                    trend_score=metrics["trend"],
                    relative_strength=metrics["relative"],
                    breadth=metrics["breadth"],
                    acceleration=metrics["acceleration"],
                    durability=metrics["durability"],
                    drawdown_resilience=metrics["drawdown"],
                    liquidity_score=item.liquidity_score,
                    trend_crowding_proxy=metrics["crowding"],
                    horizon_scores=tuple((name, metrics[name]) for name in ("1m", "3m", "6m", "12m")),
                    evidence_identifiers=item.evidence_identifiers,
                )
            )
        all_evidence = tuple(
            dict.fromkeys(
                identifier
                for item in observations
                for identifier in item.evidence_identifiers
            )
        )
        return GlobalOpportunityRadarReport(
            as_of=as_of,
            assessments=tuple(assessments),
            exposure_breadth=tuple(sorted(exposure_breadth.items())),
            asset_class_breadth=tuple(sorted(asset_breadth.items())),
            evidence_identifiers=all_evidence,
            diagnostics=(
                f"Scanned {len(observations)} point-in-time instruments across the active research universe.",
                "Leadership score combines trend, cross-sectional relative strength, breadth, acceleration, durability, drawdown resilience and liquidity.",
                "Trend crowding is a price/volatility proxy and is not represented as institutional positioning evidence.",
                "Radar output is research-only and cannot qualify, size or authorize capital.",
            ),
        )


@dataclass(frozen=True, slots=True)
class ExposureGraphNode:
    identifier: str
    kind: ExposureNodeKind
    label: str
    as_of: datetime
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        object.__setattr__(self, "label", _text(self.label, field_name="label"))
        if not isinstance(self.kind, ExposureNodeKind):
            raise TypeError("kind must be ExposureNodeKind")
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class ExposureGraphEdge:
    identifier: str
    source_identifier: str
    target_identifier: str
    relationship: str
    as_of: datetime
    confidence: float
    evidence_identifiers: tuple[str, ...]
    explicit_reviewed: bool = False

    def __post_init__(self) -> None:
        for name in ("identifier", "source_identifier", "target_identifier", "relationship"):
            object.__setattr__(self, name, _text(getattr(self, name), field_name=name))
        if self.source_identifier == self.target_identifier:
            raise ValueError("exposure graph edge cannot reference itself")
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(self, "confidence", _ratio(self.confidence, field_name="confidence"))
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class CanonicalExposureGraph:
    as_of: datetime
    nodes: tuple[ExposureGraphNode, ...]
    edges: tuple[ExposureGraphEdge, ...]
    version: str = "canonical-global-exposure-graph.v1"
    authorizes_capital: bool = False

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        node_ids = tuple(item.identifier for item in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("exposure graph node identifiers must be unique")
        edge_ids = tuple(item.identifier for item in self.edges)
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("exposure graph edge identifiers must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.as_of != self.as_of:
                raise ValueError("exposure graph edges must share graph as_of")
            if edge.source_identifier not in known or edge.target_identifier not in known:
                raise ValueError("exposure graph edges must reference known nodes")
        if any(item.as_of != self.as_of for item in self.nodes):
            raise ValueError("exposure graph nodes must share graph as_of")

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [identifier for item in self.nodes for identifier in item.evidence_identifiers]
                + [identifier for item in self.edges for identifier in item.evidence_identifiers]
            )
        )

    @staticmethod
    def _node_id(kind: ExposureNodeKind, label: str) -> str:
        return f"{kind.value}:{label.strip().lower()}"

    @classmethod
    def from_instruments(
        cls,
        instruments: Sequence[object],
        *,
        as_of: datetime,
        explicit_nodes: tuple[ExposureGraphNode, ...] = (),
        explicit_edges: tuple[ExposureGraphEdge, ...] = (),
    ) -> "CanonicalExposureGraph":
        timestamp = _aware(as_of, field_name="as_of")
        nodes: dict[str, ExposureGraphNode] = {item.identifier: item for item in explicit_nodes}
        edges: dict[str, ExposureGraphEdge] = {item.identifier: item for item in explicit_edges}

        def add_node(kind: ExposureNodeKind, label: str, evidence: tuple[str, ...]) -> str:
            identifier = cls._node_id(kind, label)
            if identifier not in nodes:
                nodes[identifier] = ExposureGraphNode(identifier, kind, label, timestamp, evidence)
            return identifier

        def add_edge(source: str, target: str, relationship: str, evidence: tuple[str, ...]) -> None:
            digest = hashlib.sha256(f"{source}|{target}|{relationship}|{timestamp.isoformat()}".encode()).hexdigest()[:20]
            identifier = f"exposure-edge:{digest}"
            edges.setdefault(
                identifier,
                ExposureGraphEdge(
                    identifier=identifier,
                    source_identifier=source,
                    target_identifier=target,
                    relationship=relationship,
                    as_of=timestamp,
                    confidence=1.0,
                    evidence_identifiers=evidence,
                    explicit_reviewed=False,
                ),
            )

        for instrument in instruments:
            instrument_id = _text(getattr(instrument, "instrument_identifier"), field_name="instrument_identifier")
            symbol = _text(getattr(instrument, "symbol"), field_name="symbol").upper()
            asset_class = getattr(instrument, "execution_asset_class")
            if not isinstance(asset_class, CandidateAssetClass):
                raise TypeError("instrument execution_asset_class must be CandidateAssetClass")
            evidence = (f"governed-universe:{instrument_id}",)
            instrument_node = add_node(ExposureNodeKind.INSTRUMENT, instrument_id, evidence)
            relationships = (
                (ExposureNodeKind.ASSET_CLASS, asset_class.value, "classified_as"),
                (ExposureNodeKind.ECONOMIC_EXPOSURE, _text(getattr(instrument, "economic_exposure"), field_name="economic_exposure"), "has_economic_exposure"),
                (ExposureNodeKind.COUNTRY, _text(getattr(instrument, "country_code"), field_name="country_code").upper(), "listed_in_country"),
                (ExposureNodeKind.CURRENCY, _text(getattr(instrument, "currency"), field_name="currency").upper(), "denominated_in"),
                (ExposureNodeKind.VENUE, _text(getattr(instrument, "venue"), field_name="venue").upper(), "traded_on"),
            )
            for kind, label, relationship in relationships:
                target = add_node(kind, label, evidence)
                add_edge(instrument_node, target, relationship, evidence)
            underlying = getattr(instrument, "underlying_symbol", None)
            if underlying is not None and str(underlying).strip():
                target = add_node(ExposureNodeKind.UNDERLYING, str(underlying).strip().upper(), evidence)
                add_edge(instrument_node, target, "derives_from", evidence)
            # Preserve the symbol as a reviewed alias in evidence without creating
            # a second instrument node that could be mistaken for security identity.
            nodes[instrument_node] = ExposureGraphNode(
                instrument_node,
                ExposureNodeKind.INSTRUMENT,
                f"{instrument_id}|{symbol}",
                timestamp,
                evidence,
            )
        return cls(timestamp, tuple(sorted(nodes.values(), key=lambda item: item.identifier)), tuple(sorted(edges.values(), key=lambda item: item.identifier)))

    def research_exposures(self, exposure_identifier: str) -> tuple[ResearchExposure, ...]:
        normalized = _text(exposure_identifier, field_name="exposure_identifier").lower()
        candidate_targets = {
            node.identifier
            for node in self.nodes
            if node.kind is not ExposureNodeKind.INSTRUMENT
            and (node.label.lower() == normalized or node.identifier.lower().endswith(f":{normalized}"))
        }
        instrument_nodes = {item.identifier: item for item in self.nodes if item.kind is ExposureNodeKind.INSTRUMENT}
        result: list[ResearchExposure] = []
        for edge in self.edges:
            if edge.source_identifier not in instrument_nodes or edge.target_identifier not in candidate_targets:
                continue
            node = instrument_nodes[edge.source_identifier]
            instrument_id, _, symbol = node.label.partition("|")
            asset_class = None
            liquidity = 1.0
            evidence = list(node.evidence_identifiers)
            for related in self.edges:
                if related.source_identifier != node.identifier:
                    continue
                target = next((item for item in self.nodes if item.identifier == related.target_identifier), None)
                if target is None:
                    continue
                evidence.extend(related.evidence_identifiers)
                if target.kind is ExposureNodeKind.ASSET_CLASS:
                    asset_class = CandidateAssetClass(target.label)
            if asset_class is None:
                continue
            result.append(
                ResearchExposure(
                    exposure_identifier=normalized,
                    instrument_identifier=instrument_id,
                    symbol=symbol or instrument_id,
                    asset_class=asset_class,
                    liquidity_score=liquidity,
                    evidence_identifiers=tuple(dict.fromkeys(evidence)),
                )
            )
        return tuple(result)

    def discover_event_opportunities(
        self,
        assessment: EventMarketAssessment,
    ) -> tuple[ForwardOpportunityHypothesis, ...]:
        exposures: list[ResearchExposure] = []
        for transmission in assessment.transmissions:
            exposures.extend(self.research_exposures(transmission.target_identifier))
        unique = {
            (item.exposure_identifier, item.instrument_identifier): item
            for item in exposures
        }
        return ForwardOpportunityDiscoveryEngine().discover(
            assessment,
            eligible_exposures=tuple(unique.values()),
        )


@dataclass(frozen=True, slots=True)
class OpportunitySweepNomination:
    candidate_identifier: str
    instrument_identifier: str
    symbol: str
    stage: BullMarketStage
    priority: float
    radar_rank: int
    evidence_identifiers: tuple[str, ...]
    research_only: bool = True
    authorizes_capital: bool = False
    schema_version: str = "persistent-opportunity-sweep-nomination.v1"


@dataclass(frozen=True, slots=True)
class PersistentOpportunitySweepResult:
    as_of: datetime
    nominations: tuple[OpportunitySweepNomination, ...]
    radar: GlobalOpportunityRadarReport
    exposure_graph: CanonicalExposureGraph
    authorizes_capital: bool = False
    version: str = "persistent-global-opportunity-sweep.v1"

    @property
    def by_candidate(self) -> dict[str, OpportunitySweepNomination]:
        return {item.candidate_identifier: item for item in self.nominations}


class PersistentOpportunitySweep:
    """Convert global leadership into research attention every evidence cycle."""

    version = "persistent-global-opportunity-sweep.v1"

    _STAGE_MULTIPLIER = {
        BullMarketStage.EMERGING: 1.00,
        BullMarketStage.CONFIRMED: 1.00,
        BullMarketStage.MATURE: 0.90,
        BullMarketStage.CROWDED_FRAGILE: 0.65,
    }

    def run(
        self,
        radar: GlobalOpportunityRadarReport,
        exposure_graph: CanonicalExposureGraph,
        *,
        minimum_priority: float = 0.55,
    ) -> PersistentOpportunitySweepResult:
        if radar.as_of != exposure_graph.as_of:
            raise ValueError("radar and exposure graph must share as_of")
        threshold = _ratio(minimum_priority, field_name="minimum_priority")
        graph_instruments = {
            node.label.partition("|")[0]
            for node in exposure_graph.nodes
            if node.kind is ExposureNodeKind.INSTRUMENT
        }
        nominations = []
        for assessment in radar.assessments:
            multiplier = self._STAGE_MULTIPLIER.get(assessment.stage)
            if multiplier is None or assessment.instrument_identifier not in graph_instruments:
                continue
            priority = round(assessment.score * multiplier, 8)
            if priority < threshold:
                continue
            nominations.append(
                OpportunitySweepNomination(
                    candidate_identifier=assessment.candidate_identifier,
                    instrument_identifier=assessment.instrument_identifier,
                    symbol=assessment.symbol,
                    stage=assessment.stage,
                    priority=priority,
                    radar_rank=assessment.rank,
                    evidence_identifiers=tuple(
                        dict.fromkeys(
                            (*assessment.evidence_identifiers, *exposure_graph.evidence_identifiers)
                        )
                    ),
                )
            )
        nominations.sort(key=lambda item: (item.priority, -item.radar_rank, item.symbol), reverse=True)
        return PersistentOpportunitySweepResult(
            as_of=radar.as_of,
            nominations=tuple(nominations),
            radar=radar,
            exposure_graph=exposure_graph,
        )

    def forward_bundle(
        self,
        nomination: OpportunitySweepNomination,
        assessment: BullMarketAssessment,
    ) -> ForwardIntelligenceBundle:
        if nomination.candidate_identifier != assessment.candidate_identifier:
            raise ValueError("nomination and assessment must identify the same candidate")
        trend_stage = {
            BullMarketStage.EMERGING: TrendStage.EARLY,
            BullMarketStage.CONFIRMED: TrendStage.CONFIRMED,
            BullMarketStage.MATURE: TrendStage.MATURE,
            BullMarketStage.CROWDED_FRAGILE: TrendStage.CROWDED,
            BullMarketStage.DETERIORATING: TrendStage.DETERIORATING,
            BullMarketStage.BEAR: TrendStage.DETERIORATING,
        }[assessment.stage]
        signal = ForwardSignal(
            identifier=f"signal:global-opportunity-radar:{assessment.candidate_identifier}:{assessment.as_of.isoformat()}",
            as_of=assessment.as_of,
            name="global bull-market and rotation leadership",
            channels=("market", "forecast"),
            # Discovery evidence deliberately does not rewrite pre-committee economics.
            # Specialists see the cross-sectional leadership evidence and may challenge it.
            expected_return_impact=0.0,
            confidence=_clip(0.45 + 0.45 * assessment.score),
            evidence=(
                f"Global radar rank={assessment.rank}; score={assessment.score:.0%}; stage={assessment.stage.value}",
                f"Relative strength={assessment.relative_strength:.0%}; breadth={assessment.breadth:.0%}; durability={assessment.durability:.0%}",
                f"Acceleration={assessment.acceleration:+.2f}; drawdown resilience={assessment.drawdown_resilience:.0%}",
            ),
            contradictory_evidence=(
                (f"Trend crowding proxy is elevated at {assessment.trend_crowding_proxy:.0%}.",)
                if assessment.trend_crowding_proxy >= 0.80
                else ()
            ),
            assumptions=(
                "Cross-sectional leadership remains observable with complete point-in-time market evidence.",
                "Leadership is research attention, not proof that expected return exceeds cash or competing opportunities.",
            ),
            risks=(
                "Fast rotations can reverse before the next CIO cycle.",
                "Price-based breadth and crowding proxies do not substitute for certified institutional flow or positioning evidence.",
            ),
            change_conditions=(
                "Reassess when short-horizon returns, breadth, relative strength, liquidity or drawdown regime changes materially.",
            ),
            evidence_identifiers=nomination.evidence_identifiers,
        )
        return ForwardIntelligenceBundle(
            identifier=f"forward:global-opportunity-radar:{assessment.candidate_identifier}:{assessment.as_of.isoformat()}",
            candidate_identifier=assessment.candidate_identifier,
            as_of=assessment.as_of,
            signals=(signal,),
            scenarios=(),
            diagnostics=(
                f"Persistent global sweep nominated {assessment.symbol} at research priority {nomination.priority:.0%}.",
                "The nomination cannot bypass opportunity qualification, the six specialists, CIO authority or construction.",
            ),
            model_versions=(GlobalBullMarketRadarEngine.version, self.version, "canonical-global-exposure-graph.v1"),
            trend_stage=trend_stage,
        )


__all__ = [
    "BullMarketAssessment",
    "BullMarketStage",
    "CanonicalExposureGraph",
    "ExposureGraphEdge",
    "ExposureGraphNode",
    "ExposureNodeKind",
    "GlobalBullMarketRadarEngine",
    "GlobalOpportunityRadarReport",
    "OpportunitySweepNomination",
    "PersistentOpportunitySweep",
    "PersistentOpportunitySweepResult",
    "RadarObservation",
]
