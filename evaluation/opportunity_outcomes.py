"""Append-only live opportunity-cost measurement for screened candidates.

This ledger complements the full point-in-time CIO evaluator by measuring whether
pre-committee qualification rejected a company that subsequently outperformed
cash.  It never feeds current returns back into the same decision and grants no
candidate, sizing, construction, execution, or policy authority.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import exp, log1p
from pathlib import Path
from typing import Any, Mapping, Sequence

from cio import CandidateDecisionRecord
from opportunity import OpportunityQueue


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value.strip()


@dataclass(frozen=True, slots=True)
class OpportunityOutcomeSummary:
    recorded_decisions: int
    resolved_outcomes: int
    missed_opportunities: int
    avoided_losses: int


class SQLiteOpportunityOutcomeStore:
    """Hash-chained decisions and later outcome observations."""

    _TABLE = "opportunity_outcome_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS opportunity_outcome_symbol_sequence
                ON {self._TABLE} (symbol, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'opportunity outcome events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'opportunity outcome events are append-only'); END;
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        event_type: str,
        symbol: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        material = "|".join(
            (
                str(sequence),
                event_identifier,
                event_type,
                symbol,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _append(
        self,
        *,
        event_identifier: str,
        event_type: str,
        symbol: str,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> None:
        identifier = _text(event_identifier, field_name="event_identifier")
        kind = _text(event_type, field_name="event_type")
        normalized_symbol = _text(symbol, field_name="symbol").upper()
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE event_identifier = ?",
                (identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError("opportunity outcome event identifier conflict")
                return
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=identifier,
                event_type=kind,
                symbol=normalized_symbol,
                occurred_at=timestamp,
                payload_json=payload_json,
                previous_hash=previous,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, event_type, symbol, occurred_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    identifier,
                    kind,
                    normalized_symbol,
                    timestamp,
                    payload_json,
                    previous,
                    content_hash,
                ),
            )

    def append_screening_decisions(
        self,
        *,
        queue: OpportunityQueue,
        candidates: Sequence[CandidateDecisionRecord],
        cash_annual_return: float,
    ) -> int:
        candidate_by_identifier = {item.identifier: item for item in candidates}
        ranked = {item.candidate.identifier: item for item in queue.ranked}
        rejected = {item.candidate_identifier: item for item in queue.rejected}
        count = 0
        for candidate in candidates:
            ranking = ranked.get(candidate.identifier)
            rejection = rejected.get(candidate.identifier)
            disposition = "qualified" if ranking is not None else "rejected"
            reasons = () if rejection is None else rejection.reasons
            event_identifier = f"screening-decision:{candidate.identifier}"
            self._append(
                event_identifier=event_identifier,
                event_type="screening_decision",
                symbol=candidate.instrument.symbol,
                occurred_at=candidate.as_of,
                payload={
                    "candidate_identifier": candidate.identifier,
                    "symbol": candidate.instrument.symbol,
                    "decision_as_of": candidate.as_of.isoformat(),
                    "decision_horizon_days": candidate.decision_horizon_days,
                    "starting_price": candidate.current_price,
                    "cash_annual_return": float(cash_annual_return),
                    "disposition": disposition,
                    "rank": None if ranking is None else ranking.rank,
                    "score": None if ranking is None else ranking.score,
                    "reasons": list(reasons),
                    "resolved_policy_profile": (
                        None if rejection is None else rejection.resolved_policy_profile
                    ),
                    "paper_only": True,
                    "real_money_authorized": False,
                },
            )
            count += 1
        return count

    def unresolved_symbols(self, *, as_of: datetime, minimum_age_days: int = 21) -> tuple[str, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        decisions = self._decision_rows()
        outcomes = self._outcome_decision_ids()
        symbols = {
            str(payload["symbol"]).upper()
            for payload in decisions
            if str(payload["candidate_identifier"]) not in outcomes
            and timestamp - datetime.fromisoformat(str(payload["decision_as_of"]))
            >= timedelta(days=minimum_age_days)
        }
        return tuple(sorted(symbols))

    def resolve_due(
        self,
        *,
        observed_at: datetime,
        observed_prices: Mapping[str, tuple[float, str]],
        minimum_age_days: int = 21,
        material_edge: float = 0.01,
    ) -> int:
        timestamp = _aware(observed_at, field_name="observed_at")
        outcomes = self._outcome_decision_ids()
        count = 0
        for decision in self._decision_rows():
            candidate_identifier = str(decision["candidate_identifier"])
            if candidate_identifier in outcomes:
                continue
            decision_time = datetime.fromisoformat(str(decision["decision_as_of"]))
            elapsed = timestamp - decision_time
            if elapsed < timedelta(days=minimum_age_days):
                continue
            symbol = str(decision["symbol"]).upper()
            observation = observed_prices.get(symbol)
            if observation is None:
                continue
            current_price, source_identifier = observation
            starting_price = float(decision["starting_price"])
            if starting_price <= 0.0 or current_price <= 0.0:
                continue
            candidate_return = current_price / starting_price - 1.0
            years = elapsed.total_seconds() / (365.25 * 24 * 3600)
            cash_annual = float(decision["cash_annual_return"])
            cash_return = (
                exp(log1p(cash_annual) * years) - 1.0
                if cash_annual > -1.0
                else -1.0
            )
            excess = candidate_return - cash_return
            disposition = str(decision["disposition"])
            if disposition == "rejected" and excess > material_edge:
                outcome = "missed_opportunity"
            elif disposition == "rejected" and excess < -material_edge:
                outcome = "avoided_loss"
            elif disposition == "qualified" and excess > material_edge:
                outcome = "supported_gain"
            elif disposition == "qualified" and excess < -material_edge:
                outcome = "supported_loss"
            else:
                outcome = "neutral"
            self._append(
                event_identifier=f"screening-outcome:{candidate_identifier}:{timestamp.date().isoformat()}",
                event_type="screening_outcome",
                symbol=symbol,
                occurred_at=timestamp,
                payload={
                    "candidate_identifier": candidate_identifier,
                    "symbol": symbol,
                    "decision_as_of": decision["decision_as_of"],
                    "observed_at": timestamp.isoformat(),
                    "elapsed_days": elapsed.total_seconds() / 86400.0,
                    "starting_price": starting_price,
                    "observed_price": current_price,
                    "candidate_return": candidate_return,
                    "cash_return": cash_return,
                    "excess_return_vs_cash": excess,
                    "disposition": disposition,
                    "outcome": outcome,
                    "source_identifier": source_identifier,
                    "research_only": True,
                    "execution_authority": False,
                },
            )
            outcomes.add(candidate_identifier)
            count += 1
        return count

    def summary(self) -> OpportunityOutcomeSummary:
        decisions = self._decision_rows()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE event_type = 'screening_outcome'"
            ).fetchall()
        payloads = [json.loads(str(row["payload_json"])) for row in rows]
        return OpportunityOutcomeSummary(
            recorded_decisions=len(decisions),
            resolved_outcomes=len(payloads),
            missed_opportunities=sum(item.get("outcome") == "missed_opportunity" for item in payloads),
            avoided_losses=sum(item.get("outcome") == "avoided_loss" for item in payloads),
        )

    def _decision_rows(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE event_type = 'screening_decision' ORDER BY sequence"
            ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    def _outcome_decision_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} WHERE event_type = 'screening_outcome'"
            ).fetchall()
        return {
            str(json.loads(str(row["payload_json"]))["candidate_identifier"])
            for row in rows
        }

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous = self._GENESIS
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected or str(row["previous_hash"]) != previous:
                raise ValueError("opportunity outcome ledger chain is invalid")
            expected_hash = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                event_type=str(row["event_type"]),
                symbol=str(row["symbol"]),
                occurred_at=str(row["occurred_at"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous,
            )
            if str(row["content_hash"]) != expected_hash:
                raise ValueError("opportunity outcome ledger content hash is invalid")
            previous = expected_hash
        return True


__all__ = ["OpportunityOutcomeSummary", "SQLiteOpportunityOutcomeStore"]
