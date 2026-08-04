"""Temporal semantic investment and exposure graph.

The graph is an advisory research representation. It cannot expand the eligible
universe, create a candidate, cast a specialist vote, size a position, or authorize
portfolio action. Every relationship is point-in-time, provenance-bearing, and
explicitly classified as verified or inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterable


class InvestmentEntityType(str, Enum):
    COMPANY = "company"
    ISSUER = "issuer"
    INSTRUMENT = "instrument"
    INDUSTRY = "industry"
    COUNTRY = "country"
    CURRENCY = "currency"
    COMMODITY = "commodity"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    PRODUCT = "product"
    TECHNOLOGY = "technology"
    INTEREST_RATE = "interest_rate"
    CREDIT_MARKET = "credit_market"
    POLICY = "policy"
    ECONOMIC_INDICATOR = "economic_indicator"
    MANAGEMENT_TEAM = "management_team"
    EVENT = "event"
    THESIS = "investment_thesis"
    HOLDING = "holding"
    CANDIDATE = "candidate"
    FACTOR = "factor"


class RelationshipConfidence(str, Enum):
    VERIFIED = "verified"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class InvestmentEntity:
    identifier: str
    entity_type: InvestmentEntityType
    name: str
    effective_at: datetime
    source_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.name.strip():
            raise ValueError("entity identifier and name are required")
        if not isinstance(self.entity_type, InvestmentEntityType):
            raise TypeError("entity_type must be InvestmentEntityType")
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must be timezone-aware")
        if not self.source_identifiers:
            raise ValueError("entity provenance is required")
        if len(self.source_identifiers) != len(set(self.source_identifiers)):
            raise ValueError("entity source identifiers cannot contain duplicates")


@dataclass(frozen=True, slots=True)
class InvestmentRelationship:
    identifier: str
    source_entity_identifier: str
    predicate: str
    target_entity_identifier: str
    confidence_type: RelationshipConfidence
    confidence: float
    direction: float
    effective_at: datetime
    observed_at: datetime
    source_identifiers: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "source_entity_identifier",
            "predicate",
            "target_entity_identifier",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not isinstance(self.confidence_type, RelationshipConfidence):
            raise TypeError("confidence_type must be RelationshipConfidence")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between zero and one")
        if not -1.0 <= float(self.direction) <= 1.0:
            raise ValueError("direction must be between -1 and 1")
        for name in ("effective_at", "observed_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.effective_at > self.observed_at:
            raise ValueError("effective_at cannot be after observed_at")
        if not self.source_identifiers:
            raise ValueError("relationship provenance is required")
        if self.confidence_type is RelationshipConfidence.INFERRED and not self.invalidation_conditions:
            raise ValueError("inferred relationships require invalidation conditions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "source_entity_identifier": self.source_entity_identifier,
            "predicate": self.predicate,
            "target_entity_identifier": self.target_entity_identifier,
            "confidence_type": self.confidence_type.value,
            "confidence": float(self.confidence),
            "direction": float(self.direction),
            "effective_at": self.effective_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "source_identifiers": list(self.source_identifiers),
            "invalidation_conditions": list(self.invalidation_conditions),
            "authorizes_portfolio_change": False,
        }


@dataclass(frozen=True, slots=True)
class ExposurePath:
    entity_identifiers: tuple[str, ...]
    relationship_identifiers: tuple[str, ...]
    cumulative_direction: float
    minimum_confidence: float
    contains_inference: bool


@dataclass(frozen=True, slots=True)
class ExposureQueryResult:
    origin_identifier: str
    target_identifier: str
    as_of: datetime
    paths: tuple[ExposurePath, ...]
    exposure_known: bool
    limitation: str | None
    schema_version: str = "investment-graph-query.v1"

    @property
    def zero_exposure_established(self) -> bool:
        return False


class SemanticInvestmentGraph:
    """Immutable-in-use graph snapshot with temporal path queries."""

    def __init__(
        self,
        entities: Iterable[InvestmentEntity] = (),
        relationships: Iterable[InvestmentRelationship] = (),
    ) -> None:
        entity_values = tuple(entities)
        self._entities = {item.identifier: item for item in entity_values}
        self._relationships = tuple(relationships)
        if len(self._entities) != len(entity_values):
            raise ValueError("entity identifiers must be unique")
        relationship_ids = tuple(item.identifier for item in self._relationships)
        if len(relationship_ids) != len(set(relationship_ids)):
            raise ValueError("relationship identifiers must be unique")
        missing = {
            endpoint
            for item in self._relationships
            for endpoint in (
                item.source_entity_identifier,
                item.target_entity_identifier,
            )
            if endpoint not in self._entities
        }
        if missing:
            raise ValueError(f"relationship endpoints are missing: {sorted(missing)!r}")

    @property
    def entities(self) -> tuple[InvestmentEntity, ...]:
        return tuple(self._entities.values())

    @property
    def relationships(self) -> tuple[InvestmentRelationship, ...]:
        return self._relationships

    def query(
        self,
        origin_identifier: str,
        target_identifier: str,
        *,
        as_of: datetime,
        maximum_depth: int = 4,
    ) -> ExposureQueryResult:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if maximum_depth < 1 or maximum_depth > 8:
            raise ValueError("maximum_depth must be between 1 and 8")
        if origin_identifier not in self._entities or target_identifier not in self._entities:
            return ExposureQueryResult(
                origin_identifier=origin_identifier,
                target_identifier=target_identifier,
                as_of=as_of,
                paths=(),
                exposure_known=False,
                limitation="One or both graph entities are unknown; exposure cannot be treated as zero.",
            )
        adjacency: dict[str, list[InvestmentRelationship]] = {}
        for relationship in self._relationships:
            if relationship.effective_at <= as_of and relationship.observed_at <= as_of:
                adjacency.setdefault(relationship.source_entity_identifier, []).append(relationship)
        paths: list[ExposurePath] = []
        stack: list[tuple[str, tuple[str, ...], tuple[InvestmentRelationship, ...]]] = [
            (origin_identifier, (origin_identifier,), ())
        ]
        while stack:
            current, entities, edges = stack.pop()
            if len(edges) >= maximum_depth:
                continue
            for edge in adjacency.get(current, ()):
                if edge.target_entity_identifier in entities:
                    continue
                next_entities = (*entities, edge.target_entity_identifier)
                next_edges = (*edges, edge)
                if edge.target_entity_identifier == target_identifier:
                    direction = 1.0
                    for item in next_edges:
                        direction *= item.direction
                    paths.append(
                        ExposurePath(
                            entity_identifiers=next_entities,
                            relationship_identifiers=tuple(item.identifier for item in next_edges),
                            cumulative_direction=round(direction, 8),
                            minimum_confidence=min(item.confidence for item in next_edges),
                            contains_inference=any(
                                item.confidence_type is RelationshipConfidence.INFERRED
                                for item in next_edges
                            ),
                        )
                    )
                else:
                    stack.append((edge.target_entity_identifier, next_entities, next_edges))
        ordered = tuple(
            sorted(
                paths,
                key=lambda item: (
                    item.contains_inference,
                    -item.minimum_confidence,
                    len(item.relationship_identifiers),
                    item.relationship_identifiers,
                ),
            )
        )
        return ExposureQueryResult(
            origin_identifier=origin_identifier,
            target_identifier=target_identifier,
            as_of=as_of,
            paths=ordered,
            exposure_known=bool(ordered),
            limitation=None if ordered else "No governed relationship path is known; exposure is unknown rather than zero.",
        )

    def shared_dependencies(
        self,
        instrument_identifiers: tuple[str, ...],
        *,
        as_of: datetime,
    ) -> dict[str, tuple[str, ...]]:
        reverse: dict[str, set[str]] = {}
        for instrument in instrument_identifiers:
            for target in self._entities:
                result = self.query(instrument, target, as_of=as_of)
                if result.exposure_known:
                    reverse.setdefault(target, set()).add(instrument)
        return {
            dependency: tuple(sorted(instruments))
            for dependency, instruments in sorted(reverse.items())
            if len(instruments) > 1
        }


__all__ = [
    "ExposurePath",
    "ExposureQueryResult",
    "InvestmentEntity",
    "InvestmentEntityType",
    "InvestmentRelationship",
    "RelationshipConfidence",
    "SemanticInvestmentGraph",
]
