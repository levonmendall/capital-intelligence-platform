"""Append-only global rotation context and cash-accountability persistence.

The store is separate from canonical CIO decision authority. It records why excess cash
remained after each completed paper cycle, including cycles with no candidate-level CIO
decision, so persistent abstention cannot disappear from the audit trail.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any

from cio.models import CIOAction
from portfolio.global_rotation_models import (
    CashCompetitionState,
    GlobalRotationContext,
)


class ResidualCashClassification(str, Enum):
    REQUIRED_RESERVE = "required_reserve"
    ECONOMIC_WIN_ESTIMATE = "economic_win_estimate"
    DEPLOYED_WITH_RESIDUAL = "deployed_with_residual"
    HARD_CONSTRAINT_FORCED = "hard_constraint_forced"
    UNEXPLAINED_RESIDUAL = "unexplained_residual"


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return round(result, 8)


@dataclass(frozen=True, slots=True)
class GlobalCashAccountability:
    cycle_identifier: str
    starting_cash_weight: float
    required_cash_weight: float
    final_cash_weight: float
    residual_excess_cash_weight: float
    positive_cio_action_count: int
    construction_block_count: int
    ranked_opportunity_count: int
    pre_cio_cash_state: CashCompetitionState
    classification: ResidualCashClassification
    strongest_candidate_identifier: str | None
    strongest_domain: str | None
    strongest_score: float | None
    strongest_expected_return_edge: float | None
    explanation: str
    policy_version: str = "global-cash-accountability.v1"
    investment_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_identifier, str) or not self.cycle_identifier.strip():
            raise ValueError("cycle_identifier cannot be empty")
        for name in (
            "starting_cash_weight",
            "required_cash_weight",
            "final_cash_weight",
            "residual_excess_cash_weight",
        ):
            value = _finite(getattr(self, name), field_name=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)
        for name in (
            "positive_cio_action_count",
            "construction_block_count",
            "ranked_opportunity_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.pre_cio_cash_state, CashCompetitionState):
            raise TypeError("pre_cio_cash_state must be CashCompetitionState")
        if not isinstance(self.classification, ResidualCashClassification):
            raise TypeError("classification must be ResidualCashClassification")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("explanation cannot be empty")
        if self.investment_authority:
            raise ValueError("cash accountability cannot authorize investment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_identifier": self.cycle_identifier,
            "starting_cash_weight": self.starting_cash_weight,
            "required_cash_weight": self.required_cash_weight,
            "final_cash_weight": self.final_cash_weight,
            "residual_excess_cash_weight": self.residual_excess_cash_weight,
            "positive_cio_action_count": self.positive_cio_action_count,
            "construction_block_count": self.construction_block_count,
            "ranked_opportunity_count": self.ranked_opportunity_count,
            "pre_cio_cash_state": self.pre_cio_cash_state.value,
            "classification": self.classification.value,
            "strongest_candidate_identifier": self.strongest_candidate_identifier,
            "strongest_domain": self.strongest_domain,
            "strongest_score": self.strongest_score,
            "strongest_expected_return_edge": self.strongest_expected_return_edge,
            "explanation": self.explanation,
            "policy_version": self.policy_version,
            "investment_authority": False,
            "construction_authority": False,
        }


def build_global_cash_accountability(
    *,
    cycle_identifier: str,
    context: GlobalRotationContext,
    result: object,
) -> GlobalCashAccountability:
    construction = getattr(result, "construction", None)
    final_cash = (
        context.current_cash_weight
        if construction is None
        else float(getattr(construction, "target_cash_weight", context.current_cash_weight))
    )
    final_cash = max(0.0, min(1.0, final_cash))
    residual = max(0.0, final_cash - context.minimum_cash_weight)
    decisions = tuple(getattr(result, "decisions", ()) or ())
    positive_count = sum(
        getattr(item, "action", None) in {CIOAction.BUY, CIOAction.INCREASE}
        for item in decisions
    )
    blocks = tuple(getattr(construction, "blocks", ()) or ()) if construction is not None else ()
    strongest = context.strongest

    if residual <= 1e-8:
        classification = ResidualCashClassification.REQUIRED_RESERVE
        explanation = "No cash remains beyond the governed minimum reserve after final construction."
    elif context.cash_competition_state is CashCompetitionState.CASH_LEADING_ESTIMATE:
        classification = ResidualCashClassification.ECONOMIC_WIN_ESTIMATE
        explanation = (
            "No pre-CIO globally ranked candidate cleared the positive-edge and minimum global-opportunity score required to challenge marginal cash."
        )
    elif blocks:
        classification = ResidualCashClassification.HARD_CONSTRAINT_FORCED
        explanation = (
            "Final construction retained excess cash because one or more explicit portfolio construction constraints blocked additional deployment."
        )
    elif positive_count > 0:
        classification = ResidualCashClassification.DEPLOYED_WITH_RESIDUAL
        explanation = (
            "The CIO deployed capital into positive opportunities, but approved conviction/risk sizing left residual cash above the minimum reserve; that residual remains subject to future global competition."
        )
    else:
        classification = ResidualCashClassification.UNEXPLAINED_RESIDUAL
        explanation = (
            "A pre-CIO deployment opportunity existed, no final construction block explains the residual, and no positive CIO action deployed capital. This is an explicit abstention diagnostic requiring review rather than a valid default-cash conclusion."
        )

    return GlobalCashAccountability(
        cycle_identifier=cycle_identifier,
        starting_cash_weight=context.current_cash_weight,
        required_cash_weight=context.minimum_cash_weight,
        final_cash_weight=final_cash,
        residual_excess_cash_weight=residual,
        positive_cio_action_count=positive_count,
        construction_block_count=len(blocks),
        ranked_opportunity_count=len(context.signals),
        pre_cio_cash_state=context.cash_competition_state,
        classification=classification,
        strongest_candidate_identifier=(
            None if strongest is None else strongest.candidate_identifier
        ),
        strongest_domain=None if strongest is None else strongest.domain.value,
        strongest_score=None if strongest is None else strongest.score,
        strongest_expected_return_edge=(
            None if strongest is None else strongest.expected_return_edge
        ),
        explanation=explanation,
    )


class SQLiteGlobalRotationStore:
    """Independent append-only hash chain for completed global rotation cycles."""

    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS global_rotation_events (
                    sequence INTEGER PRIMARY KEY,
                    event_identifier TEXT NOT NULL UNIQUE,
                    cycle_identifier TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS global_rotation_prevent_update
                BEFORE UPDATE ON global_rotation_events
                BEGIN
                    SELECT RAISE(ABORT, 'global rotation store is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS global_rotation_prevent_delete
                BEFORE DELETE ON global_rotation_events
                BEGIN
                    SELECT RAISE(ABORT, 'global rotation store is append-only');
                END;
                """
            )

    def append(
        self,
        *,
        cycle_identifier: str,
        context: GlobalRotationContext,
        accountability: GlobalCashAccountability,
        code_version: str,
    ) -> str:
        payload = {
            "schema_version": "global-rotation-event.v1",
            "cycle_identifier": str(cycle_identifier),
            "code_version": str(code_version or "unknown"),
            "global_rotation_context": context.to_dict(),
            "cash_accountability": accountability.to_dict(),
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload_json = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        event_identifier = f"global-rotation:{cycle_identifier}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json, content_hash FROM global_rotation_events WHERE event_identifier = ?",
                (event_identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "global rotation event already exists with different content"
                    )
                connection.rollback()
                return str(existing["content_hash"])
            previous = connection.execute(
                "SELECT sequence, content_hash FROM global_rotation_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous is not None else 1
            previous_hash = (
                str(previous["content_hash"]) if previous is not None else self._GENESIS
            )
            content_hash = hashlib.sha256(
                json.dumps(
                    {
                        "sequence": sequence,
                        "event_identifier": event_identifier,
                        "cycle_identifier": str(cycle_identifier),
                        "occurred_at": context.as_of.isoformat(),
                        "payload_json": payload_json,
                        "previous_hash": previous_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            connection.execute(
                """
                INSERT INTO global_rotation_events (
                    sequence, event_identifier, cycle_identifier, occurred_at,
                    payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    event_identifier,
                    str(cycle_identifier),
                    context.as_of.isoformat(),
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            connection.commit()
            return content_hash

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        expected_sequence = 1
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT * FROM global_rotation_events ORDER BY sequence"
            )
            for row in cursor:
                if int(row["sequence"]) != expected_sequence:
                    return False
                if str(row["previous_hash"]) != previous:
                    return False
                expected = hashlib.sha256(
                    json.dumps(
                        {
                            "sequence": int(row["sequence"]),
                            "event_identifier": str(row["event_identifier"]),
                            "cycle_identifier": str(row["cycle_identifier"]),
                            "occurred_at": str(row["occurred_at"]),
                            "payload_json": str(row["payload_json"]),
                            "previous_hash": str(row["previous_hash"]),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if expected != str(row["content_hash"]):
                    return False
                previous = expected
                expected_sequence += 1
        return True


__all__ = [
    "GlobalCashAccountability",
    "ResidualCashClassification",
    "SQLiteGlobalRotationStore",
    "build_global_cash_accountability",
]
