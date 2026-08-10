"""Append-only Decision Intelligence v3 ledger and wealth-oriented validation.

The ledger records post-CIO explanation packets and later realized outcomes without
mutating policy. Validation focuses on the portfolio's economic objective: sustainable
compounding of dollar value after costs. Metrics remain diagnostic and cannot tune
thresholds, promote models, or authorize capital automatically.
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

from intelligence.decision_intelligence_v3 import CandidateDecisionIntelligencePacket


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DecisionOutcomeObservation:
    packet_identifier: str
    observed_at: datetime
    realized_candidate_return: float
    realized_portfolio_return: float
    realized_cash_return: float
    realized_best_alternative_return: float
    realized_benchmark_return: float | None = None
    realized_max_drawdown: float | None = None
    evidence_identifiers: tuple[str, ...] = ()
    schema_version: str = "decision-outcome-observation.v1"

    def __post_init__(self) -> None:
        if not self.packet_identifier.strip():
            raise ValueError("packet_identifier cannot be empty")
        _aware(self.observed_at, field_name="observed_at")
        for name in (
            "realized_candidate_return",
            "realized_portfolio_return",
            "realized_cash_return",
            "realized_best_alternative_return",
        ):
            object.__setattr__(self, name, _finite(getattr(self, name), field_name=name))
        for name in ("realized_benchmark_return", "realized_max_drawdown"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, field_name=name))
        if self.realized_max_drawdown is not None and self.realized_max_drawdown > 0.0:
            raise ValueError("realized_max_drawdown must be non-positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_identifier": self.packet_identifier,
            "observed_at": self.observed_at.isoformat(),
            "realized_candidate_return": self.realized_candidate_return,
            "realized_portfolio_return": self.realized_portfolio_return,
            "realized_cash_return": self.realized_cash_return,
            "realized_best_alternative_return": self.realized_best_alternative_return,
            "realized_benchmark_return": self.realized_benchmark_return,
            "realized_max_drawdown": self.realized_max_drawdown,
            "evidence_identifiers": list(self.evidence_identifiers),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CIOWealthValidationReport:
    as_of: datetime
    observation_count: int
    mean_portfolio_excess_return_vs_cash: float
    mean_portfolio_excess_return_vs_best_alternative: float
    mean_candidate_excess_return_vs_best_alternative: float
    beat_cash_rate: float
    beat_best_alternative_rate: float
    expected_return_mean_absolute_error: float
    expected_improvement_mean_absolute_error: float
    cumulative_diagnostic_dollar_value_added_vs_cash: float
    cumulative_diagnostic_dollar_value_added_vs_best_alternative: float
    positive_dollar_value_added_rate: float
    performance_claim_authorized: bool = False
    policy_change_authorized: bool = False
    schema_version: str = "cio-wealth-validation.v1"

    def __post_init__(self) -> None:
        _aware(self.as_of, field_name="as_of")
        if self.observation_count < 1:
            raise ValueError("observation_count must be positive")
        if self.performance_claim_authorized or self.policy_change_authorized:
            raise ValueError("validation report is advisory only")

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "observation_count": self.observation_count,
            "mean_portfolio_excess_return_vs_cash": round(self.mean_portfolio_excess_return_vs_cash, 8),
            "mean_portfolio_excess_return_vs_best_alternative": round(self.mean_portfolio_excess_return_vs_best_alternative, 8),
            "mean_candidate_excess_return_vs_best_alternative": round(self.mean_candidate_excess_return_vs_best_alternative, 8),
            "beat_cash_rate": round(self.beat_cash_rate, 8),
            "beat_best_alternative_rate": round(self.beat_best_alternative_rate, 8),
            "expected_return_mean_absolute_error": round(self.expected_return_mean_absolute_error, 8),
            "expected_improvement_mean_absolute_error": round(self.expected_improvement_mean_absolute_error, 8),
            "cumulative_diagnostic_dollar_value_added_vs_cash": round(self.cumulative_diagnostic_dollar_value_added_vs_cash, 2),
            "cumulative_diagnostic_dollar_value_added_vs_best_alternative": round(self.cumulative_diagnostic_dollar_value_added_vs_best_alternative, 2),
            "positive_dollar_value_added_rate": round(self.positive_dollar_value_added_rate, 8),
            "performance_claim_authorized": False,
            "policy_change_authorized": False,
            "schema_version": self.schema_version,
        }


class SQLiteDecisionIntelligenceV3Store:
    """Append-only packet/outcome store with content-addressed idempotency."""

    def __init__(self, path: str | Path = "database/decision-intelligence-v3.db") -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_intelligence_packets (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    packet_identifier TEXT NOT NULL UNIQUE,
                    cycle_identifier TEXT NOT NULL,
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
                CREATE TABLE IF NOT EXISTS decision_outcomes (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    packet_identifier TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    UNIQUE(packet_identifier, observed_at)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_packets_cycle ON decision_intelligence_packets(cycle_identifier, sequence)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_packets_symbol ON decision_intelligence_packets(symbol, sequence)"
            )

    def append_packet(self, packet: CandidateDecisionIntelligencePacket) -> str:
        if not isinstance(packet, CandidateDecisionIntelligencePacket):
            raise TypeError("packet must be CandidateDecisionIntelligencePacket")
        payload = packet.to_dict()
        payload_json = _canonical(payload)
        content_hash = _hash(payload_json)
        recorded_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT content_hash FROM decision_intelligence_packets WHERE packet_identifier = ?",
                (packet.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) != content_hash:
                    raise ValueError("packet identifier already exists with different content")
                return content_hash
            connection.execute(
                """
                INSERT INTO decision_intelligence_packets(
                    packet_identifier, cycle_identifier, candidate_identifier, symbol,
                    as_of, payload_json, content_hash, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    packet.identifier,
                    packet.cycle_identifier,
                    packet.candidate_identifier,
                    packet.symbol.upper(),
                    packet.as_of.isoformat(),
                    payload_json,
                    content_hash,
                    recorded_at,
                ),
            )
        return content_hash

    def append_outcome(self, outcome: DecisionOutcomeObservation) -> str:
        if not isinstance(outcome, DecisionOutcomeObservation):
            raise TypeError("outcome must be DecisionOutcomeObservation")
        if self.packet(outcome.packet_identifier) is None:
            raise ValueError("outcome references an unknown decision-intelligence packet")
        payload_json = _canonical(outcome.to_dict())
        content_hash = _hash(payload_json)
        recorded_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT content_hash FROM decision_outcomes WHERE packet_identifier = ? AND observed_at = ?",
                (outcome.packet_identifier, outcome.observed_at.isoformat()),
            ).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) != content_hash:
                    raise ValueError("outcome timestamp already exists with different content")
                return content_hash
            connection.execute(
                """
                INSERT INTO decision_outcomes(
                    packet_identifier, observed_at, payload_json, content_hash, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    outcome.packet_identifier,
                    outcome.observed_at.isoformat(),
                    payload_json,
                    content_hash,
                    recorded_at,
                ),
            )
        return content_hash

    def packet(self, identifier: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_intelligence_packets WHERE packet_identifier = ?",
                (str(identifier),),
            ).fetchone()
        return None if row is None else json.loads(str(row["payload_json"]))

    def latest_packets(self, *, limit: int = 100) -> tuple[dict[str, Any], ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM decision_intelligence_packets ORDER BY sequence DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return tuple(json.loads(str(row["payload_json"])) for row in rows)

    def latest_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_intelligence_packets WHERE symbol = ? ORDER BY sequence DESC LIMIT 1",
                (str(symbol).strip().upper(),),
            ).fetchone()
        return None if row is None else json.loads(str(row["payload_json"]))

    def latest_cycle_packets(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            cycle = connection.execute(
                "SELECT cycle_identifier FROM decision_intelligence_packets ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            if cycle is None:
                return ()
            rows = connection.execute(
                "SELECT payload_json FROM decision_intelligence_packets WHERE cycle_identifier = ? ORDER BY sequence ASC",
                (str(cycle["cycle_identifier"]),),
            ).fetchall()
        return tuple(json.loads(str(row["payload_json"])) for row in rows)

    def validation_pairs(self) -> tuple[tuple[dict[str, Any], dict[str, Any]], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT p.payload_json AS packet_json, o.payload_json AS outcome_json
                FROM decision_outcomes o
                JOIN decision_intelligence_packets p
                  ON p.packet_identifier = o.packet_identifier
                ORDER BY o.sequence ASC
                """
            ).fetchall()
        return tuple(
            (json.loads(str(row["packet_json"])), json.loads(str(row["outcome_json"])))
            for row in rows
        )


def build_cio_wealth_validation_report(
    pairs: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    as_of: datetime,
) -> CIOWealthValidationReport:
    """Measure realized dollar-value creation without making a performance claim."""

    _aware(as_of, field_name="as_of")
    values = tuple(pairs)
    if not values:
        raise ValueError("wealth validation requires at least one resolved decision")

    portfolio_vs_cash: list[float] = []
    portfolio_vs_alt: list[float] = []
    candidate_vs_alt: list[float] = []
    expected_return_errors: list[float] = []
    expected_improvement_errors: list[float] = []
    dollar_vs_cash: list[float] = []
    dollar_vs_alt: list[float] = []

    for packet, outcome in values:
        objective = dict(packet["objective"])
        opportunity = dict(packet["opportunity"])
        portfolio_value = float(objective["portfolio_value"])
        realized_portfolio = float(outcome["realized_portfolio_return"])
        realized_cash = float(outcome["realized_cash_return"])
        realized_alt = float(outcome["realized_best_alternative_return"])
        realized_candidate = float(outcome["realized_candidate_return"])
        portfolio_vs_cash.append(realized_portfolio - realized_cash)
        portfolio_vs_alt.append(realized_portfolio - realized_alt)
        candidate_vs_alt.append(realized_candidate - realized_alt)
        expected_return_errors.append(
            abs(realized_candidate - float(opportunity["candidate_expected_return"]))
        )
        # Match the expected candidate attribution used at decision time: allocation
        # change multiplied by the candidate's realized edge over the same alternative.
        # This handles both additions and avoided losses from reductions without
        # confusing candidate attribution with whole-portfolio realized return.
        weight_change = float(opportunity["proposed_target_weight"]) - float(
            opportunity["current_weight"]
        )
        realized_candidate_improvement = weight_change * (
            realized_candidate - realized_alt
        )
        expected_improvement_errors.append(
            abs(
                realized_candidate_improvement
                - float(opportunity["marginal_portfolio_improvement"])
            )
        )
        dollar_vs_cash.append(portfolio_value * (realized_portfolio - realized_cash))
        dollar_vs_alt.append(portfolio_value * (realized_portfolio - realized_alt))

    count = len(values)
    mean = lambda xs: sum(xs) / len(xs)
    return CIOWealthValidationReport(
        as_of=as_of,
        observation_count=count,
        mean_portfolio_excess_return_vs_cash=mean(portfolio_vs_cash),
        mean_portfolio_excess_return_vs_best_alternative=mean(portfolio_vs_alt),
        mean_candidate_excess_return_vs_best_alternative=mean(candidate_vs_alt),
        beat_cash_rate=sum(value > 0.0 for value in portfolio_vs_cash) / count,
        beat_best_alternative_rate=sum(value > 0.0 for value in portfolio_vs_alt) / count,
        expected_return_mean_absolute_error=mean(expected_return_errors),
        expected_improvement_mean_absolute_error=mean(expected_improvement_errors),
        cumulative_diagnostic_dollar_value_added_vs_cash=sum(dollar_vs_cash),
        cumulative_diagnostic_dollar_value_added_vs_best_alternative=sum(dollar_vs_alt),
        positive_dollar_value_added_rate=sum(value > 0.0 for value in dollar_vs_alt) / count,
    )


__all__ = [
    "CIOWealthValidationReport",
    "DecisionOutcomeObservation",
    "SQLiteDecisionIntelligenceV3Store",
    "build_cio_wealth_validation_report",
]
