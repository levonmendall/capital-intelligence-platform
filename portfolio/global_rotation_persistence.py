"""Append-only global rotation context and cash-accountability persistence.

The store is separate from canonical CIO decision authority. It records why excess cash
remained after each completed paper cycle and provides the prior immutable rotation
snapshot needed to measure leadership migration. It never mutates canonical CIO
persistence or authorizes investment.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from cio.models import CIOAction
from portfolio.global_rotation_models import CashCompetitionState, GlobalRotationContext

_GLOBAL_CONTEXT_PREFIX = "global-rotation-context.v1:"


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


def _decision_rotation_payload(decision: object) -> dict[str, Any]:
    for marker in tuple(getattr(decision, "monitoring_indicators", ()) or ()):
        if not isinstance(marker, str) or not marker.startswith(_GLOBAL_CONTEXT_PREFIX):
            continue
        try:
            payload = json.loads(marker[len(_GLOBAL_CONTEXT_PREFIX):])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _to_dict_or_none(value: object | None) -> dict[str, Any] | None:
    if value is None:
        return None
    method = getattr(value, "to_dict", None)
    if not callable(method):
        raise TypeError("persisted global rotation extension must expose to_dict()")
    payload = method()
    if not isinstance(payload, dict):
        raise TypeError("global rotation extension to_dict() must return a dict")
    return payload


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
    hard_blocked_candidate_count: int
    hard_blocker_count: int
    soft_constraint_count: int
    conviction_stage_counts: tuple[tuple[str, int], ...]
    indicated_conviction_weight: float
    positive_deployed_weight: float
    optimized_deployable_weight: float
    unfilled_optimized_weight: float
    construction_expected_return_improvement: float | None
    pre_cio_cash_state: CashCompetitionState
    classification: ResidualCashClassification
    strongest_candidate_identifier: str | None
    strongest_domain: str | None
    strongest_score: float | None
    strongest_expected_return_edge: float | None
    cycle_disposition_classification: str | None
    explanation: str
    policy_version: str = "global-cash-accountability.v4"
    investment_authority: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_identifier, str) or not self.cycle_identifier.strip():
            raise ValueError("cycle_identifier cannot be empty")
        for name in (
            "starting_cash_weight",
            "required_cash_weight",
            "final_cash_weight",
            "residual_excess_cash_weight",
            "indicated_conviction_weight",
            "positive_deployed_weight",
            "optimized_deployable_weight",
            "unfilled_optimized_weight",
        ):
            value = _finite(getattr(self, name), field_name=name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)
        if self.construction_expected_return_improvement is not None:
            object.__setattr__(
                self,
                "construction_expected_return_improvement",
                _finite(
                    self.construction_expected_return_improvement,
                    field_name="construction_expected_return_improvement",
                ),
            )
        for name in (
            "positive_cio_action_count",
            "construction_block_count",
            "ranked_opportunity_count",
            "hard_blocked_candidate_count",
            "hard_blocker_count",
            "soft_constraint_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if not isinstance(self.conviction_stage_counts, tuple) or not all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and item[0].strip()
            and isinstance(item[1], int)
            and not isinstance(item[1], bool)
            and item[1] >= 0
            for item in self.conviction_stage_counts
        ):
            raise ValueError("conviction_stage_counts must contain (stage, count) pairs")
        if len(tuple(item[0] for item in self.conviction_stage_counts)) != len(
            set(item[0] for item in self.conviction_stage_counts)
        ):
            raise ValueError("conviction stages must be unique")
        if not isinstance(self.pre_cio_cash_state, CashCompetitionState):
            raise TypeError("pre_cio_cash_state must be CashCompetitionState")
        if not isinstance(self.classification, ResidualCashClassification):
            raise TypeError("classification must be ResidualCashClassification")
        if self.cycle_disposition_classification is not None and (
            not isinstance(self.cycle_disposition_classification, str)
            or not self.cycle_disposition_classification.strip()
        ):
            raise ValueError("cycle_disposition_classification must be text or None")
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
            "hard_blocked_candidate_count": self.hard_blocked_candidate_count,
            "hard_blocker_count": self.hard_blocker_count,
            "soft_constraint_count": self.soft_constraint_count,
            "conviction_stage_counts": [list(item) for item in self.conviction_stage_counts],
            "indicated_conviction_weight": self.indicated_conviction_weight,
            "positive_deployed_weight": self.positive_deployed_weight,
            "optimized_deployable_weight": self.optimized_deployable_weight,
            "unfilled_optimized_weight": self.unfilled_optimized_weight,
            "construction_expected_return_improvement": self.construction_expected_return_improvement,
            "pre_cio_cash_state": self.pre_cio_cash_state.value,
            "classification": self.classification.value,
            "strongest_candidate_identifier": self.strongest_candidate_identifier,
            "strongest_domain": self.strongest_domain,
            "strongest_score": self.strongest_score,
            "strongest_expected_return_edge": self.strongest_expected_return_edge,
            "cycle_disposition_classification": self.cycle_disposition_classification,
            "explanation": self.explanation,
            "policy_version": self.policy_version,
            "investment_authority": False,
            "construction_authority": False,
        }


def _positive_deployed_weight(construction: object | None) -> float:
    if construction is None:
        return 0.0
    total = 0.0
    for trade in tuple(getattr(construction, "trades", ()) or ()):
        before = getattr(trade, "from_weight", None)
        after = getattr(trade, "to_weight", None)
        if isinstance(before, (int, float)) and not isinstance(before, bool) and isinstance(after, (int, float)) and not isinstance(after, bool):
            total += max(0.0, float(after) - float(before))
    return min(1.0, total)


def build_global_cash_accountability(
    *,
    cycle_identifier: str,
    context: GlobalRotationContext,
    result: object,
    optimizer_proposal: object | None = None,
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
    disposition = getattr(result, "cycle_disposition", None)
    disposition_classification = getattr(disposition, "classification", None)
    if disposition_classification is not None:
        disposition_classification = str(disposition_classification).strip() or None

    rotation_payloads = tuple(
        payload for payload in (_decision_rotation_payload(item) for item in decisions) if payload
    )
    stage_counts: dict[str, int] = {}
    hard_blocked_candidate_count = 0
    hard_blocker_count = 0
    soft_constraint_count = 0
    indicated_conviction_weight = 0.0
    for payload in rotation_payloads:
        stage = str(payload.get("conviction_stage", "unavailable"))
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        hard = tuple(payload.get("hard_blockers", ()) or ())
        soft = tuple(payload.get("soft_constraints", ()) or ())
        hard_blocker_count += len(hard)
        soft_constraint_count += len(soft)
        if hard:
            hard_blocked_candidate_count += 1
        target = payload.get("conviction_target_weight")
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            indicated_conviction_weight += max(0.0, float(target))
    indicated_conviction_weight = min(1.0, indicated_conviction_weight)
    construction_improvement = (
        None if construction is None else getattr(construction, "expected_return_improvement", None)
    )
    deployed_weight = _positive_deployed_weight(construction)
    optimized_weight = 0.0
    if optimizer_proposal is not None:
        value = getattr(optimizer_proposal, "deployable_cash_used", 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            optimized_weight = max(0.0, min(1.0, float(value)))
    unfilled = max(0.0, optimized_weight - deployed_weight)

    all_reviewed_hard_blocked = bool(context.signals) and (
        hard_blocked_candidate_count >= len(context.signals)
    )
    unexplained_partial = (
        residual > 1e-8
        and optimized_weight > 0.0
        and unfilled >= 0.0025 - 1e-8
        and not blocks
        and not all_reviewed_hard_blocked
    )
    if residual <= 1e-8:
        classification = ResidualCashClassification.REQUIRED_RESERVE
        explanation = "No cash remains beyond the governed minimum reserve after final construction."
    elif disposition_classification == "evidence_or_authority_block":
        classification = ResidualCashClassification.HARD_CONSTRAINT_FORCED
        explanation = (
            "Excess cash remained because the governed empty-queue disposition found an evidence, capability-authority, operational, or unmapped qualification block. Cash did not win an economic comparison; deployment was unavailable."
        )
    elif blocks:
        classification = ResidualCashClassification.HARD_CONSTRAINT_FORCED
        explanation = (
            "Final construction retained excess cash because one or more explicit portfolio construction constraints blocked additional deployment."
        )
    elif all_reviewed_hard_blocked:
        classification = ResidualCashClassification.HARD_CONSTRAINT_FORCED
        explanation = (
            "Every candidate that reached global CIO review was subsequently blocked by one or more hard evidence, implementation, funding, or downside controls."
        )
    elif unexplained_partial:
        classification = ResidualCashClassification.UNEXPLAINED_RESIDUAL
        explanation = (
            f"The specialist-bounded optimizer identified {optimized_weight:.2%} of deployable marginal capital, but final positive deployment used only {deployed_weight:.2%}; {unfilled:.2%} remained unfilled while excess cash persisted without a construction or complete hard-control explanation."
        )
    elif positive_count > 0:
        classification = ResidualCashClassification.DEPLOYED_WITH_RESIDUAL
        explanation = (
            "The CIO deployed capital into positive opportunities and no material specialist-bounded optimizer allocation remained unexplained; residual cash reflects approved conviction/risk sizing."
        )
    elif context.cash_competition_state is CashCompetitionState.CASH_LEADING_ESTIMATE:
        classification = ResidualCashClassification.ECONOMIC_WIN_ESTIMATE
        explanation = (
            "Among candidates that survived governed qualification, none cleared the positive-edge and minimum global-opportunity score required to challenge marginal cash."
        )
    else:
        classification = ResidualCashClassification.UNEXPLAINED_RESIDUAL
        explanation = (
            "A pre-CIO deployment opportunity existed, no final construction block or complete set of hard CIO blockers explains the residual, and no positive CIO action deployed capital."
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
        hard_blocked_candidate_count=hard_blocked_candidate_count,
        hard_blocker_count=hard_blocker_count,
        soft_constraint_count=soft_constraint_count,
        conviction_stage_counts=tuple(sorted(stage_counts.items())),
        indicated_conviction_weight=round(indicated_conviction_weight, 8),
        positive_deployed_weight=round(deployed_weight, 8),
        optimized_deployable_weight=round(optimized_weight, 8),
        unfilled_optimized_weight=round(unfilled, 8),
        construction_expected_return_improvement=(
            None if construction_improvement is None else float(construction_improvement)
        ),
        pre_cio_cash_state=context.cash_competition_state,
        classification=classification,
        strongest_candidate_identifier=None if strongest is None else strongest.candidate_identifier,
        strongest_domain=None if strongest is None else strongest.domain.value,
        strongest_score=None if strongest is None else strongest.score,
        strongest_expected_return_edge=None if strongest is None else strongest.expected_return_edge,
        cycle_disposition_classification=disposition_classification,
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

    def latest_payload(self) -> dict[str, Any] | None:
        """Return the last immutable side-store payload without changing authority."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM global_rotation_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        return payload if isinstance(payload, dict) else None

    def latest_signal_snapshots(self) -> dict[str, Mapping[str, Any]]:
        """Return prior candidate snapshots used only for longitudinal comparison."""

        payload = self.latest_payload()
        if payload is None:
            return {}
        context = payload.get("global_rotation_context")
        if not isinstance(context, dict):
            return {}
        values = context.get("signals", ())
        if not isinstance(values, list):
            return {}
        result: dict[str, Mapping[str, Any]] = {}
        for item in values:
            if not isinstance(item, dict):
                continue
            identifier = str(item.get("candidate_identifier", "")).strip()
            if identifier:
                result[identifier] = item
        return result

    def append(
        self,
        *,
        cycle_identifier: str,
        context: GlobalRotationContext,
        accountability: GlobalCashAccountability,
        code_version: str,
        optimizer_proposal: object | None = None,
        coverage_report: object | None = None,
    ) -> str:
        payload = {
            "schema_version": "global-rotation-event.v2",
            "cycle_identifier": str(cycle_identifier),
            "code_version": str(code_version or "unknown"),
            "global_rotation_context": context.to_dict(),
            "cash_accountability": accountability.to_dict(),
            "compound_optimizer": _to_dict_or_none(optimizer_proposal),
            "market_coverage": _to_dict_or_none(coverage_report),
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        event_identifier = f"global-rotation:{cycle_identifier}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_json, content_hash FROM global_rotation_events WHERE event_identifier = ?",
                (event_identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError("global rotation event already exists with different content")
                connection.rollback()
                return str(existing["content_hash"])
            previous = connection.execute(
                "SELECT sequence, content_hash FROM global_rotation_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous["sequence"]) + 1 if previous is not None else 1
            previous_hash = str(previous["content_hash"]) if previous is not None else self._GENESIS
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
            cursor = connection.execute("SELECT * FROM global_rotation_events ORDER BY sequence")
            for row in cursor:
                if int(row["sequence"]) != expected_sequence or str(row["previous_hash"]) != previous:
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
