"""Explicit, reversible champion-versus-challenger promotion authority."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from evaluation.model_comparison import ModelComparisonReport
from governance.model_experiments import ModelExperiment


@dataclass(frozen=True, slots=True)
class ModelPromotionDecision:
    identifier: str
    experiment_identifier: str
    previous_champion_version: str
    promoted_model_version: str
    approved_by: str
    approved_at: datetime
    rollback_model_version: str
    comparison_report_identifier: str
    rationale: str
    schema_version: str = "model-promotion-decision.v1"

    def __post_init__(self) -> None:
        for name in (
            "identifier",
            "experiment_identifier",
            "previous_champion_version",
            "promoted_model_version",
            "approved_by",
            "rollback_model_version",
            "comparison_report_identifier",
            "rationale",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.previous_champion_version == self.promoted_model_version:
            raise ValueError("promotion must change the model version")
        if self.rollback_model_version != self.previous_champion_version:
            raise ValueError("rollback must preserve the previous champion")
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "experiment_identifier": self.experiment_identifier,
            "previous_champion_version": self.previous_champion_version,
            "promoted_model_version": self.promoted_model_version,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat(),
            "rollback_model_version": self.rollback_model_version,
            "comparison_report_identifier": self.comparison_report_identifier,
            "rationale": self.rationale,
            "automatic_policy_change": False,
        }


class PromotionError(RuntimeError):
    pass


class ChampionChallengerAuthority:
    def approve(
        self,
        experiment: ModelExperiment,
        report: ModelComparisonReport,
        *,
        identifier: str,
        approved_by: str,
        approved_at: datetime,
        rationale: str,
    ) -> ModelPromotionDecision:
        if report.experiment_identifier != experiment.identifier:
            raise PromotionError("comparison report does not match experiment")
        if not report.promotion_recommended:
            raise PromotionError(
                "challenger does not satisfy promotion requirements"
            )
        return ModelPromotionDecision(
            identifier=identifier,
            experiment_identifier=experiment.identifier,
            previous_champion_version=experiment.champion_model_version,
            promoted_model_version=experiment.challenger_model_version,
            approved_by=approved_by,
            approved_at=approved_at,
            rollback_model_version=experiment.champion_model_version,
            comparison_report_identifier=(
                f"model-comparison:{experiment.identifier}:{report.as_of.isoformat()}"
            ),
            rationale=rationale,
        )


class SQLiteModelGovernanceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_governance_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS model_governance_no_update
                BEFORE UPDATE ON model_governance_events
                BEGIN SELECT RAISE(ABORT, 'model governance is append only'); END;
                CREATE TRIGGER IF NOT EXISTS model_governance_no_delete
                BEFORE DELETE ON model_governance_events
                BEGIN SELECT RAISE(ABORT, 'model governance is append only'); END;
                """
            )

    @staticmethod
    def _hash(previous_hash: str | None, payload_json: str) -> str:
        return hashlib.sha256(
            ((previous_hash or "") + "\n" + payload_json).encode()
        ).hexdigest()

    def append(
        self,
        identifier: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        payload_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with sqlite3.connect(self.path) as connection:
            prior = connection.execute(
                "SELECT content_hash FROM model_governance_events ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(prior[0]) if prior else None
            content_hash = self._hash(previous_hash, payload_json)
            existing = connection.execute(
                "SELECT payload_json,content_hash FROM model_governance_events WHERE identifier=?",
                (identifier,),
            ).fetchone()
            if existing:
                if str(existing[0]) == payload_json:
                    return str(existing[1])
                raise PromotionError(
                    "conflicting model-governance identifier"
                )
            connection.execute(
                "INSERT INTO model_governance_events(identifier,event_type,payload_json,previous_hash,content_hash) VALUES(?,?,?,?,?)",
                (
                    identifier,
                    event_type,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return content_hash


__all__ = [
    "ChampionChallengerAuthority",
    "ModelPromotionDecision",
    "PromotionError",
    "SQLiteModelGovernanceStore",
]
