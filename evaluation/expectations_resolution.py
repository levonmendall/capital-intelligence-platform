"""Point-in-time expectations/surprise forecast registry and resolution.

The production CIO already consumes governed market expectations, internal
expectations, expected surprise, and priced-in evidence. This module records exactly
that decision-time view and later resolves it against actual surprise and market
reaction. It is append-only, advisory, and cannot authorize capital or mutate policy.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(value: object, *, field_name: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if low is not None and number < low:
        raise ValueError(f"{field_name} must be at least {low}")
    if high is not None and number > high:
        raise ValueError(f"{field_name} must be at most {high}")
    return number


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExpectationsForecastRecord:
    identifier: str
    packet_identifier: str
    candidate_identifier: str
    symbol: str
    as_of: datetime
    market_expectation: str
    internal_expectation: str
    expected_surprise: float
    priced_in_score: float | None
    evidence_identifiers: tuple[str, ...]
    investment_authority: bool = False
    schema_version: str = "expectations-forecast-record.v1"

    def __post_init__(self) -> None:
        for name in ("identifier", "packet_identifier", "candidate_identifier", "symbol"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        _aware(self.as_of, field_name="as_of")
        object.__setattr__(
            self,
            "expected_surprise",
            _finite(self.expected_surprise, field_name="expected_surprise", low=-1.0, high=1.0),
        )
        if self.priced_in_score is not None:
            object.__setattr__(
                self,
                "priced_in_score",
                _finite(self.priced_in_score, field_name="priced_in_score", low=0.0, high=1.0),
            )
        if not self.evidence_identifiers:
            raise ValueError("expectations forecast requires evidence lineage")
        if self.investment_authority:
            raise ValueError("expectations forecast cannot authorize capital")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "packet_identifier": self.packet_identifier,
            "candidate_identifier": self.candidate_identifier,
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "market_expectation": self.market_expectation,
            "internal_expectation": self.internal_expectation,
            "expected_surprise": self.expected_surprise,
            "priced_in_score": self.priced_in_score,
            "evidence_identifiers": list(self.evidence_identifiers),
            "investment_authority": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_packet(cls, packet: object) -> "ExpectationsForecastRecord | None":
        explanation = getattr(packet, "explanation", None)
        if explanation is None:
            return None
        surprise = getattr(explanation, "expected_surprise", None)
        if surprise is None:
            return None
        evidence = tuple(getattr(explanation, "evidence_identifiers", ()) or ())
        if not evidence:
            evidence = tuple(getattr(packet, "source_lineage", ()) or ())
        return cls(
            identifier=f"expectations:{packet.identifier}",
            packet_identifier=packet.identifier,
            candidate_identifier=packet.candidate_identifier,
            symbol=packet.symbol,
            as_of=packet.as_of,
            market_expectation=str(getattr(explanation, "market_expectation", "unavailable")),
            internal_expectation=str(getattr(explanation, "internal_expectation", "unavailable")),
            expected_surprise=float(surprise),
            priced_in_score=getattr(explanation, "priced_in_score", None),
            evidence_identifiers=evidence,
        )


@dataclass(frozen=True, slots=True)
class ExpectationsOutcomeObservation:
    forecast_identifier: str
    observed_at: datetime
    realized_surprise: float
    market_reaction: float
    abnormal_market_reaction: float | None
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "expectations-outcome-observation.v1"

    def __post_init__(self) -> None:
        if not self.forecast_identifier.strip():
            raise ValueError("forecast_identifier cannot be empty")
        _aware(self.observed_at, field_name="observed_at")
        object.__setattr__(
            self,
            "realized_surprise",
            _finite(self.realized_surprise, field_name="realized_surprise", low=-5.0, high=5.0),
        )
        object.__setattr__(
            self,
            "market_reaction",
            _finite(self.market_reaction, field_name="market_reaction", low=-1.0, high=1.0),
        )
        if self.abnormal_market_reaction is not None:
            object.__setattr__(
                self,
                "abnormal_market_reaction",
                _finite(self.abnormal_market_reaction, field_name="abnormal_market_reaction", low=-1.0, high=1.0),
            )
        if not self.evidence_identifiers:
            raise ValueError("expectations outcome requires evidence lineage")

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_identifier": self.forecast_identifier,
            "observed_at": self.observed_at.isoformat(),
            "realized_surprise": self.realized_surprise,
            "market_reaction": self.market_reaction,
            "abnormal_market_reaction": self.abnormal_market_reaction,
            "evidence_identifiers": list(self.evidence_identifiers),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ExpectationsCalibrationReport:
    as_of: datetime
    resolved_count: int
    surprise_direction_accuracy: float
    surprise_mean_absolute_error: float
    mean_market_reaction_when_direction_correct: float
    priced_in_reaction_correlation: float | None
    suggested_confidence_ceiling: float
    policy_change_authorized: bool = False
    performance_claim_authorized: bool = False
    schema_version: str = "expectations-calibration.v1"

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if self.resolved_count < 1:
            raise ValueError("resolved_count must be positive")
        if self.policy_change_authorized or self.performance_claim_authorized:
            raise ValueError("expectations calibration is advisory only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "resolved_count": self.resolved_count,
            "surprise_direction_accuracy": round(self.surprise_direction_accuracy, 8),
            "surprise_mean_absolute_error": round(self.surprise_mean_absolute_error, 8),
            "mean_market_reaction_when_direction_correct": round(self.mean_market_reaction_when_direction_correct, 8),
            "priced_in_reaction_correlation": None if self.priced_in_reaction_correlation is None else round(self.priced_in_reaction_correlation, 8),
            "suggested_confidence_ceiling": round(self.suggested_confidence_ceiling, 8),
            "policy_change_authorized": False,
            "performance_claim_authorized": False,
            "schema_version": self.schema_version,
        }


class SQLiteExpectationsResolutionStore:
    def __init__(self, path: str | Path = "database/expectations-resolution.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS expectations_forecasts (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    packet_identifier TEXT NOT NULL,
                    candidate_identifier TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS expectations_outcomes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    forecast_identifier TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(forecast_identifier, observed_at)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def append_forecast(self, forecast: ExpectationsForecastRecord) -> str:
        payload_json = _canonical(forecast.to_dict())
        content_hash = _hash(payload_json)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM expectations_forecasts WHERE identifier = ?",
                (forecast.identifier,),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != content_hash:
                    raise ValueError("expectations forecast identifier already exists with different content")
                return content_hash
            connection.execute(
                "INSERT INTO expectations_forecasts(identifier, packet_identifier, candidate_identifier, symbol, as_of, payload_json, content_hash, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    forecast.identifier,
                    forecast.packet_identifier,
                    forecast.candidate_identifier,
                    forecast.symbol.upper(),
                    forecast.as_of.isoformat(),
                    payload_json,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return content_hash

    def append_outcome(self, outcome: ExpectationsOutcomeObservation) -> str:
        with self._connect() as connection:
            forecast = connection.execute(
                "SELECT as_of FROM expectations_forecasts WHERE identifier = ?",
                (outcome.forecast_identifier,),
            ).fetchone()
            if forecast is None:
                raise ValueError("expectations outcome references unknown forecast")
            if outcome.observed_at <= datetime.fromisoformat(str(forecast["as_of"])):
                raise ValueError("expectations outcome must be observed after the forecast as_of")
        payload_json = _canonical(outcome.to_dict())
        content_hash = _hash(payload_json)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content_hash FROM expectations_outcomes WHERE forecast_identifier = ? AND observed_at = ?",
                (outcome.forecast_identifier, outcome.observed_at.isoformat()),
            ).fetchone()
            if row is not None:
                if str(row["content_hash"]) != content_hash:
                    raise ValueError("expectations outcome exists with different content")
                return content_hash
            connection.execute(
                "INSERT INTO expectations_outcomes(forecast_identifier, observed_at, payload_json, content_hash, recorded_at) VALUES (?, ?, ?, ?, ?)",
                (
                    outcome.forecast_identifier,
                    outcome.observed_at.isoformat(),
                    payload_json,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return content_hash

    def resolved_pairs(self) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT f.payload_json AS forecast_json, o.payload_json AS outcome_json
                FROM expectations_outcomes o
                JOIN expectations_forecasts f ON f.identifier = o.forecast_identifier
                ORDER BY o.sequence ASC
                """
            ).fetchall()
        return tuple(
            (json.loads(str(row["forecast_json"])), json.loads(str(row["outcome_json"])))
            for row in rows
        )


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator_left = sum((a - mean_left) ** 2 for a in left) ** 0.5
    denominator_right = sum((b - mean_right) ** 2 for b in right) ** 0.5
    denominator = denominator_left * denominator_right
    if denominator <= 1e-12:
        return None
    return numerator / denominator


def build_expectations_calibration_report(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    as_of: datetime,
) -> ExpectationsCalibrationReport:
    _aware(as_of, field_name="as_of")
    values = tuple(pairs)
    if not values:
        raise ValueError("expectations calibration requires resolved forecasts")
    direction_hits: list[bool] = []
    errors: list[float] = []
    correct_reactions: list[float] = []
    priced_in: list[float] = []
    reaction_magnitudes: list[float] = []
    for forecast, outcome in values:
        expected = float(forecast["expected_surprise"])
        realized = float(outcome["realized_surprise"])
        hit = (expected == 0.0 and realized == 0.0) or (expected * realized > 0.0)
        direction_hits.append(hit)
        errors.append(abs(expected - realized))
        if hit:
            correct_reactions.append(abs(float(outcome["market_reaction"])))
        raw_priced = forecast.get("priced_in_score")
        if raw_priced is not None:
            priced_in.append(float(raw_priced))
            reaction_magnitudes.append(abs(float(outcome["market_reaction"])))
    count = len(values)
    directional_accuracy = sum(direction_hits) / count
    mae = sum(errors) / count
    reaction = 0.0 if not correct_reactions else sum(correct_reactions) / len(correct_reactions)
    correlation = _correlation(priced_in, reaction_magnitudes)
    # Conservative evidence-only ceiling: never rewards larger errors, and never
    # exceeds observed directional reliability.
    error_reliability = max(0.0, min(1.0, 1.0 - mae))
    ceiling = min(directional_accuracy, error_reliability)
    return ExpectationsCalibrationReport(
        as_of=as_of,
        resolved_count=count,
        surprise_direction_accuracy=directional_accuracy,
        surprise_mean_absolute_error=mae,
        mean_market_reaction_when_direction_correct=reaction,
        priced_in_reaction_correlation=correlation,
        suggested_confidence_ceiling=ceiling,
    )


__all__ = [
    "ExpectationsCalibrationReport",
    "ExpectationsForecastRecord",
    "ExpectationsOutcomeObservation",
    "SQLiteExpectationsResolutionStore",
    "build_expectations_calibration_report",
]
