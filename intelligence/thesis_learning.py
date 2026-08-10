"""Append-only thesis, attribution, counterfactual, and source-value learning records.

Learning remains subordinate to current evidence.  Nothing in this module can create
an investment candidate, increase a target weight, promote policy, or authorize
execution.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


class ThesisHealth(str, Enum):
    STRENGTHENED = "strengthened"
    UNCHANGED = "unchanged"
    WEAKENED = "weakened"
    INVALIDATED = "invalidated"


class DecisionQuality(str, Enum):
    GOOD_DECISION_GOOD_OUTCOME = "good_decision_good_outcome"
    GOOD_DECISION_BAD_OUTCOME = "good_decision_bad_outcome"
    BAD_DECISION_LUCKY_OUTCOME = "bad_decision_lucky_outcome"
    BAD_DECISION_BAD_OUTCOME = "bad_decision_bad_outcome"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class InvestmentThesisRecord:
    identifier: str
    candidate_identifier: str
    as_of: datetime
    rationale: str
    assumptions: tuple[str, ...]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    expected_horizon_days: int
    health: ThesisHealth
    evidence_identifiers: tuple[str, ...]
    investment_authority: bool = False

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("thesis as_of must be timezone-aware")
        if self.expected_horizon_days < 1:
            raise ValueError("expected_horizon_days must be positive")
        if not self.evidence_identifiers:
            raise ValueError("thesis requires evidence identifiers")


@dataclass(frozen=True, slots=True)
class DecisionOutcomeAttribution:
    identifier: str
    decision_identifier: str
    observed_at: datetime
    expected_return: float
    realized_return: float
    benchmark_return: float
    best_rejected_return: float | None
    quality: DecisionQuality
    correct_assumptions: tuple[str, ...]
    failed_assumptions: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    policy_promotion_authorized: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for name in ("expected_return", "realized_return", "benchmark_return"):
            if not isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} must be finite")
        if self.best_rejected_return is not None and not isfinite(
            float(self.best_rejected_return)
        ):
            raise ValueError("best_rejected_return must be finite")
        if not self.evidence_identifiers:
            raise ValueError("outcome attribution requires evidence identifiers")


@dataclass(frozen=True, slots=True)
class CounterfactualAlternativeOutcome:
    identifier: str
    decision_identifier: str
    alternative_identifier: str
    observed_at: datetime
    chosen_return: float
    alternative_return: float
    cash_return: float
    benchmark_return: float
    evidence_identifiers: tuple[str, ...]
    investment_authority: bool = False

    @property
    def opportunity_cost(self) -> float:
        return round(float(self.alternative_return) - float(self.chosen_return), 8)


@dataclass(frozen=True, slots=True)
class SourceInformationValue:
    identifier: str
    source_identifier: str
    evaluated_at: datetime
    observation_count: int
    decision_usage_count: int
    lead_time_score: float
    incremental_value_score: float
    independence_score: float
    reliability_score: float
    false_positive_rate: float
    cost_score: float
    evidence_identifiers: tuple[str, ...]
    investment_authority: bool = False

    @property
    def net_information_value(self) -> float:
        positive = (
            0.20 * self.lead_time_score
            + 0.30 * self.incremental_value_score
            + 0.20 * self.independence_score
            + 0.20 * self.reliability_score
            + 0.10 * min(1.0, self.decision_usage_count / max(self.observation_count, 1))
        )
        penalty = 0.60 * self.false_positive_rate + 0.40 * self.cost_score
        return round(max(-1.0, min(1.0, positive - 0.35 * penalty)), 8)


class SQLiteDecisionLearningStore:
    """Generic append-only chain for research learning records."""

    _TABLE = "decision_learning_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    event_kind TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'decision learning is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'decision learning is append-only');
                END;
                """
            )

    @staticmethod
    def _json_default(value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        raise TypeError(f"cannot serialize {type(value).__name__}")

    def append(self, event_kind: str, record: object) -> int:
        payload = asdict(record) if hasattr(record, "__dataclass_fields__") else record
        if not isinstance(payload, Mapping):
            raise TypeError("learning record must be a dataclass or mapping")
        identifier = str(payload.get("identifier", "")).strip()
        timestamp = payload.get("observed_at") or payload.get("evaluated_at") or payload.get("as_of")
        if not identifier or not isinstance(timestamp, datetime):
            raise ValueError("learning record requires identifier and timezone-aware timestamp")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("learning record timestamp must be timezone-aware")
        payload_json = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=self._json_default,
        )
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != payload_json:
                    raise ValueError("learning identifier already exists with different content")
                return int(existing[0])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous = self._GENESIS if tail is None else str(tail[1])
            material = "|".join(
                (str(sequence), identifier, event_kind, timestamp.isoformat(), payload_json, previous)
            )
            content_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
            connection.execute(
                f"INSERT INTO {self._TABLE} "
                "(sequence,event_identifier,event_kind,occurred_at,payload_json,previous_hash,content_hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    sequence,
                    identifier,
                    event_kind,
                    timestamp.isoformat(),
                    payload_json,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def verify_integrity(self) -> bool:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT sequence,event_identifier,event_kind,occurred_at,payload_json,previous_hash,content_hash "
                f"FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row[0]) != expected or str(row[5]) != previous:
                raise RuntimeError("decision-learning chain is invalid")
            material = "|".join(
                (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), previous)
            )
            content_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if str(row[6]) != content_hash:
                raise RuntimeError("decision-learning content hash is invalid")
            previous = content_hash
        return True


__all__ = [
    "CounterfactualAlternativeOutcome",
    "DecisionOutcomeAttribution",
    "DecisionQuality",
    "InvestmentThesisRecord",
    "SQLiteDecisionLearningStore",
    "SourceInformationValue",
    "ThesisHealth",
]
