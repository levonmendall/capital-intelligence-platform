"""Append-only post-activation decision review journal."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DecisionReview:
    decision_identifier: str
    reviewed_at: datetime
    score_changed: bool
    committee_stable: bool
    veto_active: bool
    alert_warranted: bool
    explanation_clear: bool
    process_classification: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.decision_identifier.strip():
            raise ValueError("decision_identifier is required")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if self.process_classification not in {"disciplined", "flawed", "unresolved"}:
            raise ValueError("invalid process classification")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reviewed_at"] = self.reviewed_at.isoformat()
        return payload


class SQLiteDecisionReviewJournal:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS decision_reviews (
                    decision_identifier TEXT PRIMARY KEY,
                    reviewed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS decision_reviews_no_update
                BEFORE UPDATE ON decision_reviews
                BEGIN SELECT RAISE(ABORT, 'decision reviews are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS decision_reviews_no_delete
                BEFORE DELETE ON decision_reviews
                BEGIN SELECT RAISE(ABORT, 'decision reviews are append-only'); END;
                """
            )

    def append(self, review: DecisionReview) -> DecisionReview:
        payload = json.dumps(review.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_reviews WHERE decision_identifier = ?",
                (review.decision_identifier,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError("decision review already exists with different content")
                return review
            connection.execute(
                "INSERT INTO decision_reviews VALUES (?, ?, ?)",
                (review.decision_identifier, review.reviewed_at.isoformat(), payload),
            )
        return review

    def history(self) -> tuple[DecisionReview, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM decision_reviews ORDER BY reviewed_at"
            ).fetchall()
        return tuple(_from_dict(json.loads(row["payload_json"])) for row in rows)

    def metrics(self) -> dict[str, Any]:
        values = self.history()
        count = len(values)
        return {
            "schema_version": "decision-review-metrics.v1",
            "review_count": count,
            "disciplined_rate": round(
                sum(item.process_classification == "disciplined" for item in values) / count,
                4,
            ) if count else None,
            "committee_stability_rate": round(
                sum(item.committee_stable for item in values) / count,
                4,
            ) if count else None,
            "explanation_clarity_rate": round(
                sum(item.explanation_clear for item in values) / count,
                4,
            ) if count else None,
            "alert_precision_review_rate": round(
                sum(item.alert_warranted for item in values) / count,
                4,
            ) if count else None,
        }


def _from_dict(payload: dict[str, Any]) -> DecisionReview:
    return DecisionReview(
        decision_identifier=payload["decision_identifier"],
        reviewed_at=datetime.fromisoformat(payload["reviewed_at"]),
        score_changed=bool(payload["score_changed"]),
        committee_stable=bool(payload["committee_stable"]),
        veto_active=bool(payload["veto_active"]),
        alert_warranted=bool(payload["alert_warranted"]),
        explanation_clear=bool(payload["explanation_clear"]),
        process_classification=payload["process_classification"],
        notes=payload.get("notes", ""),
    )
