"""Deterministic event quality, clustering, and portfolio-impact evidence.

This module prioritizes educational information and may request a canonical CIO
review.  It cannot create a CIO decision, construction, order, or fill.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


_STOP_WORDS = frozenset(
    {"a", "an", "and", "as", "at", "for", "from", "in", "of", "on", "the", "to", "with"}
)


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _tokens(value: object) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[a-z0-9]+", _text(value).lower())
        if token not in _STOP_WORDS and len(token) > 1
    )


def _items(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(dict.fromkeys(_text(item) for item in value if _text(item)))


def _ratio(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(number, 0.0), 1.0)


def _provenance(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("provenance")
    return value if isinstance(value, Mapping) else {}


def _record_identifier(record: Mapping[str, Any]) -> str:
    identifier = _text(record.get("identifier"))
    if not identifier:
        raise ValueError("event records require an identifier")
    return identifier


def semantic_event_key(record: Mapping[str, Any]) -> str:
    canonical = _text(record.get("canonical_event_identifier")).lower()
    if canonical:
        return canonical
    material = " ".join(sorted(_tokens(record.get("topic"))))
    if not material:
        raise ValueError("event records require a topic or canonical identifier")
    return "semantic:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _similar(left: Mapping[str, Any], right: Mapping[str, Any], threshold: float) -> bool:
    if semantic_event_key(left) == semantic_event_key(right):
        return True
    left_tokens = _tokens(left.get("topic")) | _tokens(left.get("summary"))
    right_tokens = _tokens(right.get("topic")) | _tokens(right.get("summary"))
    if not left_tokens or not right_tokens:
        return False
    similarity = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    left_entities, right_entities = set(_items(left.get("entities"))), set(_items(right.get("entities")))
    entity_compatible = not left_entities or not right_entities or bool(left_entities & right_entities)
    return entity_compatible and similarity >= threshold


@dataclass(frozen=True, slots=True)
class EventQualityPolicy:
    version: str = "event-quality.v1"
    semantic_similarity_threshold: float = 0.45
    minimum_independent_sources: int = 2
    minimum_materiality: float = 0.50
    minimum_novelty: float = 0.50
    minimum_market_confirmation: float = 0.10


@dataclass(frozen=True, slots=True)
class EventClusterAssessment:
    identifier: str
    semantic_key: str
    representative_identifier: str
    record_identifiers: tuple[str, ...]
    source_identifiers: tuple[str, ...]
    independent_source_count: int
    entities: tuple[str, ...]
    instruments: tuple[str, ...]
    impact_channels: tuple[str, ...]
    portfolio_exposures: tuple[str, ...]
    novelty: float
    materiality: float
    corroboration: float
    market_confirmation: float
    quality_score: float
    eligible_for_cio_context: bool
    explanation: str
    policy_version: str
    schema_version: str = "event-cluster-assessment.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "semantic_key": self.semantic_key,
            "representative_identifier": self.representative_identifier,
            "record_identifiers": list(self.record_identifiers),
            "source_identifiers": list(self.source_identifiers),
            "independent_source_count": self.independent_source_count,
            "entities": list(self.entities),
            "instruments": list(self.instruments),
            "impact_channels": list(self.impact_channels),
            "portfolio_exposures": list(self.portfolio_exposures),
            "novelty": self.novelty,
            "materiality": self.materiality,
            "corroboration": self.corroboration,
            "market_confirmation": self.market_confirmation,
            "quality_score": self.quality_score,
            "eligible_for_cio_context": self.eligible_for_cio_context,
            "explanation": self.explanation,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
            "authorizes_portfolio_change": False,
            "real_money_authorized": False,
        }


def assess_event_clusters(
    records: Iterable[Mapping[str, Any]],
    *,
    prior_semantic_keys: Iterable[str] = (),
    owned_instruments: Iterable[str] = (),
    exposure_map: Mapping[str, Sequence[str]] | None = None,
    market_confirmation: Mapping[str, float] | None = None,
    policy: EventQualityPolicy | None = None,
) -> tuple[tuple[EventClusterAssessment, Mapping[str, Any]], ...]:
    effective = policy or EventQualityPolicy()
    pending = sorted((dict(item) for item in records), key=_record_identifier)
    groups: list[list[Mapping[str, Any]]] = []
    for record in pending:
        for group in groups:
            if _similar(record, group[0], effective.semantic_similarity_threshold):
                group.append(record)
                break
        else:
            groups.append([record])

    prior = set(prior_semantic_keys)
    owned = set(owned_instruments)
    mapping = exposure_map or {}
    confirmations = market_confirmation or {}
    results = []
    for group in groups:
        representative = max(
            group,
            key=lambda item: (
                _ratio(item.get("reliability")) * _ratio(item.get("materiality")),
                _record_identifier(item),
            ),
        )
        semantic_key = semantic_event_key(representative)
        providers = tuple(
            sorted(
                {
                    _text(_provenance(item).get("independence_group"))
                    or _text(_provenance(item).get("provider"))
                    or _text(_provenance(item).get("source_identifier"))
                    or "unknown"
                    for item in group
                }
            )
        )
        source_ids = tuple(
            sorted(
                {
                    _text(_provenance(item).get("source_identifier"))
                    or _text(_provenance(item).get("provider"))
                    or _record_identifier(item)
                    for item in group
                }
            )
        )
        entities = tuple(sorted({value for item in group for value in _items(item.get("entities"))}))
        instruments = tuple(sorted({value for item in group for value in _items(item.get("instruments"))}))
        channels = tuple(sorted({value for item in group for value in _items(item.get("impact_channels"))}))
        exposures = set(instruments) & owned
        for key in (*entities, *instruments, *channels):
            exposures.update(str(value) for value in mapping.get(key, ()) if str(value) in owned)
        novelty = 0.0 if semantic_key in prior else 1.0
        materiality = max(_ratio(item.get("materiality")) for item in group)
        corroboration = min(len(providers) / effective.minimum_independent_sources, 1.0)
        confirmation = max(
            (confirmations.get(key, 0.0) for key in (semantic_key, *instruments, *channels)),
            default=0.0,
        )
        confirmation = _ratio(confirmation)
        reliability = max(_ratio(item.get("reliability")) for item in group)
        relevance = max(_ratio(item.get("relevance")) for item in group)
        score = round(
            0.25 * reliability
            + 0.20 * relevance
            + 0.20 * materiality
            + 0.15 * corroboration
            + 0.10 * novelty
            + 0.10 * confirmation,
            6,
        )
        disputed = any(
            _text(_provenance(item).get("quality_state")).lower() in {"disputed", "unverified", "missing"}
            for item in group
        )
        eligible = (
            not disputed
            and len(providers) >= effective.minimum_independent_sources
            and materiality >= effective.minimum_materiality
            and novelty >= effective.minimum_novelty
            and confirmation >= effective.minimum_market_confirmation
        )
        explanation = (
            "Worth CIO review: independent sources corroborate a new material event, markets confirm it, and portfolio exposures are mapped."
            if eligible
            else "Monitor only: novelty, corroboration, materiality, market confirmation, or evidence quality is not yet sufficient for CIO review."
        )
        material = "|".join(sorted(_record_identifier(item) for item in group))
        identifier = "event-cluster:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
        assessment = EventClusterAssessment(
            identifier=identifier,
            semantic_key=semantic_key,
            representative_identifier=_record_identifier(representative),
            record_identifiers=tuple(sorted(_record_identifier(item) for item in group)),
            source_identifiers=source_ids,
            independent_source_count=len(providers),
            entities=entities,
            instruments=instruments,
            impact_channels=channels,
            portfolio_exposures=tuple(sorted(exposures)),
            novelty=novelty,
            materiality=materiality,
            corroboration=corroboration,
            market_confirmation=confirmation,
            quality_score=score,
            eligible_for_cio_context=eligible,
            explanation=explanation,
            policy_version=effective.version,
        )
        results.append((assessment, representative))
    return tuple(sorted(results, key=lambda item: (item[0].quality_score, item[0].identifier), reverse=True))


class SQLiteEventClusterStore:
    """Idempotent append-only lineage for versioned cluster assessments."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS event_cluster_assessments (
                    identifier TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS event_clusters_no_update BEFORE UPDATE ON event_cluster_assessments
                BEGIN SELECT RAISE(ABORT, 'event cluster lineage is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS event_clusters_no_delete BEFORE DELETE ON event_cluster_assessments
                BEGIN SELECT RAISE(ABORT, 'event cluster lineage is append-only'); END;
                """
            )

    def append(self, assessment: EventClusterAssessment, *, recorded_at: datetime) -> None:
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        payload = json.dumps(assessment.to_dict(), sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT payload_hash FROM event_cluster_assessments WHERE identifier = ?", (assessment.identifier,)
            ).fetchone()
            if existing is not None:
                if existing[0] != digest:
                    raise ValueError("cluster identifier already exists with different content")
                return
            connection.execute(
                "INSERT INTO event_cluster_assessments VALUES (?, ?, ?, ?)",
                (assessment.identifier, recorded_at.astimezone(timezone.utc).isoformat(), payload, digest),
            )


def evaluate_benchmark(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "event-quality-benchmark.v1":
        raise ValueError("unsupported event quality benchmark")
    annotations = payload.get("annotations")
    if not isinstance(annotations, list) or not annotations:
        raise ValueError("benchmark requires annotations")
    tp = fp = fn = tn = 0
    for case in annotations:
        results = assess_event_clusters(
            case["records"],
            prior_semantic_keys=case.get("prior_semantic_keys", ()),
            owned_instruments=case.get("owned_instruments", ()),
            exposure_map=case.get("exposure_map", {}),
            market_confirmation=case.get("market_confirmation", {}),
        )
        predicted = any(item.eligible_for_cio_context for item, _ in results)
        expected = bool(case["expected_cio_context"])
        if predicted and expected:
            tp += 1
        elif predicted:
            fp += 1
        elif expected:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    thresholds = payload["acceptance_thresholds"]
    review_state = payload.get("human_review", {}).get("state", "missing")
    passed = precision >= thresholds["minimum_precision"] and recall >= thresholds["minimum_recall"]
    return {
        "schema_version": "event-quality-benchmark-report.v1",
        "benchmark_version": payload["version"],
        "review_state": review_state,
        "certified": passed and review_state == "approved",
        "metrics_passed": passed,
        "precision": precision,
        "recall": recall,
        "confusion": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn},
        "authorizes_portfolio_change": False,
        "real_money_authorized": False,
    }


__all__ = [
    "EventClusterAssessment",
    "EventQualityPolicy",
    "SQLiteEventClusterStore",
    "assess_event_clusters",
    "evaluate_benchmark",
    "semantic_event_key",
]
