"""Persistent causal-investment graph and empirical transmission calibration.

The graph records causal hypotheses already produced by the governed event-market
engine. It does not discover candidates or authorize capital. Its purpose is to make
causal reasoning persistent, traceable, and empirically resolvable so future confidence
can be calibrated through the existing analytical-promotion process.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping

from intelligence.event_market_forward import EventMarketAssessment, TransmissionDirection


class CausalNodeKind(str, Enum):
    EVENT = "event"
    DRIVER = "driver"
    EXPOSURE = "exposure"
    CANDIDATE = "candidate"


@dataclass(frozen=True, slots=True)
class CausalGraphNode:
    identifier: str
    kind: CausalNodeKind
    label: str
    as_of: datetime
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.identifier.strip() or not self.label.strip():
            raise ValueError("causal node identity cannot be empty")
        if not isinstance(self.kind, CausalNodeKind):
            raise TypeError("kind must be CausalNodeKind")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("causal node as_of must be timezone-aware")
        if not self.evidence_identifiers:
            raise ValueError("causal nodes require evidence lineage")


@dataclass(frozen=True, slots=True)
class CausalGraphEdge:
    identifier: str
    source_identifier: str
    target_identifier: str
    relationship: str
    direction: str
    magnitude: float
    confidence: float
    horizon: str
    mechanism: str
    as_of: datetime
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "source_identifier",
            "target_identifier",
            "relationship",
            "direction",
            "horizon",
            "mechanism",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("causal edge as_of must be timezone-aware")
        if not isfinite(float(self.magnitude)) or not 0.0 <= float(self.magnitude) <= 1.0:
            raise ValueError("causal edge magnitude must be between zero and one")
        if not isfinite(float(self.confidence)) or not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("causal edge confidence must be between zero and one")
        if not self.evidence_identifiers:
            raise ValueError("causal edges require evidence lineage")


@dataclass(frozen=True, slots=True)
class CausalInvestmentGraph:
    assessment_identifier: str
    as_of: datetime
    nodes: tuple[CausalGraphNode, ...]
    edges: tuple[CausalGraphEdge, ...]
    contradictory_evidence: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    investment_authority: bool = False
    schema_version: str = "causal-investment-graph.v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("causal graph as_of must be timezone-aware")
        if self.investment_authority:
            raise ValueError("causal graph cannot authorize capital")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_identifier": self.assessment_identifier,
            "as_of": self.as_of.isoformat(),
            "nodes": [
                {
                    "identifier": item.identifier,
                    "kind": item.kind.value,
                    "label": item.label,
                    "as_of": item.as_of.isoformat(),
                    "evidence_identifiers": list(item.evidence_identifiers),
                }
                for item in self.nodes
            ],
            "edges": [
                {
                    "identifier": item.identifier,
                    "source_identifier": item.source_identifier,
                    "target_identifier": item.target_identifier,
                    "relationship": item.relationship,
                    "direction": item.direction,
                    "magnitude": item.magnitude,
                    "confidence": item.confidence,
                    "horizon": item.horizon,
                    "mechanism": item.mechanism,
                    "as_of": item.as_of.isoformat(),
                    "evidence_identifiers": list(item.evidence_identifiers),
                }
                for item in self.edges
            ],
            "contradictory_evidence": list(self.contradictory_evidence),
            "alternative_explanations": list(self.alternative_explanations),
            "unresolved_questions": list(self.unresolved_questions),
            "investment_authority": False,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CausalTransmissionOutcome:
    edge_identifier: str
    observed_at: datetime
    realized_direction: str
    realized_magnitude: float
    evidence_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.edge_identifier.strip() or not self.realized_direction.strip():
            raise ValueError("causal outcome identity/direction cannot be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("causal outcome observed_at must be timezone-aware")
        if not isfinite(float(self.realized_magnitude)) or not 0.0 <= abs(float(self.realized_magnitude)) <= 1.0:
            raise ValueError("realized_magnitude must be finite and within [-1, 1]")
        if not self.evidence_identifiers:
            raise ValueError("causal outcomes require evidence lineage")

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_identifier": self.edge_identifier,
            "observed_at": self.observed_at.isoformat(),
            "realized_direction": self.realized_direction,
            "realized_magnitude": float(self.realized_magnitude),
            "evidence_identifiers": list(self.evidence_identifiers),
        }


@dataclass(frozen=True, slots=True)
class CausalCalibrationReport:
    as_of: datetime
    resolved_count: int
    directional_accuracy: float
    magnitude_mean_absolute_error: float
    magnitude_interval_coverage: float
    mean_confidence: float
    suggested_confidence_ceiling: float
    policy_change_authorized: bool = False
    schema_version: str = "causal-calibration.v1"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("causal calibration as_of must be timezone-aware")
        if self.resolved_count < 1:
            raise ValueError("resolved_count must be positive")
        if self.policy_change_authorized:
            raise ValueError("causal calibration cannot change policy directly")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "resolved_count": self.resolved_count,
            "directional_accuracy": round(self.directional_accuracy, 8),
            "magnitude_mean_absolute_error": round(self.magnitude_mean_absolute_error, 8),
            "magnitude_interval_coverage": round(self.magnitude_interval_coverage, 8),
            "mean_confidence": round(self.mean_confidence, 8),
            "suggested_confidence_ceiling": round(self.suggested_confidence_ceiling, 8),
            "policy_change_authorized": False,
            "schema_version": self.schema_version,
        }


def build_causal_investment_graph(
    assessment: EventMarketAssessment,
    *,
    candidate_exposure_links: tuple[tuple[str, str], ...] = (),
) -> CausalInvestmentGraph:
    """Convert one governed assessment into a typed persistent graph.

    ``candidate_exposure_links`` contains ``(target_identifier,
    candidate_identifier)`` pairs established by the canonical exposure graph.
    """
    if not isinstance(assessment, EventMarketAssessment):
        raise TypeError("assessment must be EventMarketAssessment")
    event_id = f"event:{assessment.identifier}"
    base_ids = tuple(assessment.evidence_identifiers)
    if not base_ids:
        raise ValueError("causal assessment requires evidence identifiers")
    nodes: list[CausalGraphNode] = [
        CausalGraphNode(
            identifier=event_id,
            kind=CausalNodeKind.EVENT,
            label=assessment.information_identifier,
            as_of=assessment.assessed_at,
            evidence_identifiers=base_ids,
        )
    ]
    edges: list[CausalGraphEdge] = []
    driver_ids: dict[str, str] = {}
    for driver in assessment.drivers:
        driver_id = f"driver:{assessment.identifier}:{driver.rule_identifier}"
        driver_ids[driver.rule_identifier] = driver_id
        driver_evidence = tuple(dict.fromkeys(base_ids))
        nodes.append(
            CausalGraphNode(
                identifier=driver_id,
                kind=CausalNodeKind.DRIVER,
                label=driver.name,
                as_of=assessment.assessed_at,
                evidence_identifiers=driver_evidence,
            )
        )
        edges.append(
            CausalGraphEdge(
                identifier=f"edge:{assessment.identifier}:event:{driver.rule_identifier}",
                source_identifier=event_id,
                target_identifier=driver_id,
                relationship="explained_by",
                direction="supporting",
                magnitude=driver.confidence,
                confidence=driver.confidence,
                horizon="assessment",
                mechanism=" -> ".join(driver.causal_chain),
                as_of=assessment.assessed_at,
                evidence_identifiers=driver_evidence,
            )
        )

    exposure_nodes: set[str] = set()
    for index, transmission in enumerate(assessment.transmissions, start=1):
        target_id = f"exposure:{transmission.target_identifier}"
        if target_id not in exposure_nodes:
            nodes.append(
                CausalGraphNode(
                    identifier=target_id,
                    kind=CausalNodeKind.EXPOSURE,
                    label=transmission.target_identifier,
                    as_of=assessment.assessed_at,
                    evidence_identifiers=tuple(transmission.evidence_identifiers),
                )
            )
            exposure_nodes.add(target_id)
        source_ids = tuple(
            driver_ids[item]
            for item in transmission.contributing_driver_identifiers
            if item in driver_ids
        ) or (event_id,)
        for source_id in source_ids:
            edges.append(
                CausalGraphEdge(
                    identifier=f"edge:{assessment.identifier}:transmission:{index}:{source_id}",
                    source_identifier=source_id,
                    target_identifier=target_id,
                    relationship="transmits_to",
                    direction=transmission.direction.value,
                    magnitude=transmission.magnitude,
                    confidence=transmission.confidence,
                    horizon=transmission.horizon,
                    mechanism=transmission.mechanism,
                    as_of=assessment.assessed_at,
                    evidence_identifiers=tuple(transmission.evidence_identifiers),
                )
            )

    for target_identifier, candidate_identifier in tuple(candidate_exposure_links):
        target_id = f"exposure:{target_identifier}"
        candidate_id = f"candidate:{candidate_identifier}"
        if target_id not in exposure_nodes:
            continue
        nodes.append(
            CausalGraphNode(
                identifier=candidate_id,
                kind=CausalNodeKind.CANDIDATE,
                label=candidate_identifier,
                as_of=assessment.assessed_at,
                evidence_identifiers=base_ids,
            )
        )
        edges.append(
            CausalGraphEdge(
                identifier=f"edge:{assessment.identifier}:candidate:{target_identifier}:{candidate_identifier}",
                source_identifier=target_id,
                target_identifier=candidate_id,
                relationship="exposed_to",
                direction="mapped",
                magnitude=1.0,
                confidence=assessment.confidence,
                horizon="portfolio_mapping",
                mechanism="canonical exposure graph mapping",
                as_of=assessment.assessed_at,
                evidence_identifiers=base_ids,
            )
        )

    unique_nodes = {item.identifier: item for item in nodes}
    unique_edges = {item.identifier: item for item in edges}
    return CausalInvestmentGraph(
        assessment_identifier=assessment.identifier,
        as_of=assessment.assessed_at,
        nodes=tuple(unique_nodes[key] for key in sorted(unique_nodes)),
        edges=tuple(unique_edges[key] for key in sorted(unique_edges)),
        contradictory_evidence=assessment.contradictory_evidence,
        alternative_explanations=assessment.alternative_explanations,
        unresolved_questions=assessment.unresolved_questions,
    )


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SQLiteCausalIntelligenceGraphStore:
    def __init__(self, path: str | Path = "database/causal-intelligence-graph.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS causal_graphs (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    assessment_identifier TEXT NOT NULL UNIQUE,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS causal_outcomes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    edge_identifier TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(edge_identifier, observed_at)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append_graph(self, graph: CausalInvestmentGraph) -> str:
        payload_json = _canonical(graph.to_dict())
        content_hash = _hash(payload_json)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM causal_graphs WHERE assessment_identifier = ?",
                (graph.assessment_identifier,),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != content_hash:
                    raise ValueError("assessment identifier already exists with different graph content")
                return content_hash
            connection.execute(
                "INSERT INTO causal_graphs(assessment_identifier, as_of, payload_json, content_hash, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    graph.assessment_identifier,
                    graph.as_of.isoformat(),
                    payload_json,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return content_hash

    def append_outcome(self, outcome: CausalTransmissionOutcome) -> str:
        payload_json = _canonical(outcome.to_dict())
        content_hash = _hash(payload_json)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM causal_outcomes WHERE edge_identifier = ? AND observed_at = ?",
                (outcome.edge_identifier, outcome.observed_at.isoformat()),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != content_hash:
                    raise ValueError("causal outcome exists with different content")
                return content_hash
            connection.execute(
                "INSERT INTO causal_outcomes(edge_identifier, observed_at, payload_json, content_hash, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    outcome.edge_identifier,
                    outcome.observed_at.isoformat(),
                    payload_json,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return content_hash

    def resolved_edges(self) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
        with self._connect() as connection:
            graphs = connection.execute(
                "SELECT payload_json FROM causal_graphs ORDER BY sequence ASC"
            ).fetchall()
            outcomes = connection.execute(
                "SELECT payload_json FROM causal_outcomes ORDER BY sequence ASC"
            ).fetchall()
        edge_by_id: dict[str, dict[str, Any]] = {}
        for row in graphs:
            graph = json.loads(str(row["payload_json"]))
            for edge in graph.get("edges", ()):
                if edge.get("relationship") == "transmits_to":
                    edge_by_id[str(edge["identifier"])] = dict(edge)
        pairs = []
        for row in outcomes:
            outcome = json.loads(str(row["payload_json"]))
            edge = edge_by_id.get(str(outcome["edge_identifier"]))
            if edge is not None:
                pairs.append((edge, outcome))
        return tuple(pairs)


def build_causal_calibration_report(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    as_of: datetime,
) -> CausalCalibrationReport:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    values = tuple(pairs)
    if not values:
        raise ValueError("causal calibration requires resolved transmissions")
    direction_hits = []
    magnitude_errors = []
    interval_hits = []
    confidences = []
    for edge, outcome in values:
        predicted_direction = str(edge["direction"])
        realized_direction = str(outcome["realized_direction"])
        direction_hits.append(predicted_direction == realized_direction)
        predicted = float(edge["magnitude"])
        realized = abs(float(outcome["realized_magnitude"]))
        magnitude_errors.append(abs(predicted - realized))
        low = max(0.0, predicted * 0.75)
        high = min(1.0, predicted * 1.25)
        interval_hits.append(low <= realized <= high)
        confidences.append(float(edge["confidence"]))
    count = len(values)
    directional_accuracy = sum(direction_hits) / count
    magnitude_mae = sum(magnitude_errors) / count
    coverage = sum(interval_hits) / count
    mean_confidence = sum(confidences) / count
    # Conservative calibration proposal only: evidence may lower confidence but never
    # raise it above the historically observed directional reliability.
    ceiling = min(mean_confidence, directional_accuracy, coverage)
    return CausalCalibrationReport(
        as_of=as_of,
        resolved_count=count,
        directional_accuracy=directional_accuracy,
        magnitude_mean_absolute_error=magnitude_mae,
        magnitude_interval_coverage=coverage,
        mean_confidence=mean_confidence,
        suggested_confidence_ceiling=max(0.0, min(1.0, ceiling)),
    )


__all__ = [
    "CausalCalibrationReport",
    "CausalGraphEdge",
    "CausalGraphNode",
    "CausalInvestmentGraph",
    "CausalNodeKind",
    "CausalTransmissionOutcome",
    "SQLiteCausalIntelligenceGraphStore",
    "build_causal_calibration_report",
    "build_causal_investment_graph",
]
