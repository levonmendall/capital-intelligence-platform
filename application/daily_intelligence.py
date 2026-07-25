"""Canonical application service for the daily Capital Intelligence experience."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from committee import RegimeCommitteeDecision, RegimeGovernanceWorkflow
from intelligence.regime_pipeline import InstitutionalRegimePipeline, InstitutionalRegimeRun
from monitoring import MarketChangeAssessment, RegimeMaterialChangeEngine
from portfolio import PortfolioFitDecision
from reporting import (
    CIODecisionCard,
    CapitalIntelligenceScore,
    MarketEnvironmentBrief,
    build_capital_intelligence_score,
    build_cio_decision_card,
    build_market_environment_brief,
    capital_intelligence_score_to_dict,
    decision_card_to_dict,
    market_environment_brief_to_dict,
)


class DailyIntelligenceStatus(str, Enum):
    """Honest operating state for one completed daily intelligence cycle."""

    CURRENT = "current"
    INCOMPLETE = "incomplete"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DailySnapshotRecord:
    """Compact immutable history row used by the application surface."""

    identifier: str
    as_of: datetime
    generated_at: datetime
    score: int
    score_delta: int | None
    status: DailyIntelligenceStatus
    environment: str
    risk: str
    committee: str
    portfolio_impact: str
    changed_materially: bool
    should_alert: bool
    replay_identifiers: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "environment",
            "risk",
            "committee",
            "portfolio_impact",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("as_of", "generated_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise TypeError("score must be an int")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if self.score_delta is not None and (
            isinstance(self.score_delta, bool)
            or not isinstance(self.score_delta, int)
        ):
            raise TypeError("score_delta must be an int or None")
        if not isinstance(self.status, DailyIntelligenceStatus):
            raise TypeError("status must be a DailyIntelligenceStatus")
        if not isinstance(self.changed_materially, bool):
            raise TypeError("changed_materially must be a bool")
        if not isinstance(self.should_alert, bool):
            raise TypeError("should_alert must be a bool")
        if not isinstance(self.replay_identifiers, tuple) or not all(
            isinstance(value, str) and value.strip()
            for value in self.replay_identifiers
        ):
            raise TypeError(
                "replay_identifiers must contain non-empty strings"
            )


@dataclass(frozen=True, slots=True)
class DailyCapitalIntelligenceSnapshot:
    """One internally consistent morning product surface."""

    identifier: str
    as_of: datetime
    generated_at: datetime
    status: DailyIntelligenceStatus
    score: CapitalIntelligenceScore
    score_delta: int | None
    environment: MarketEnvironmentBrief
    decision_card: CIODecisionCard
    change_assessment: MarketChangeAssessment | None
    change_summary: str
    replay_identifiers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("identifier must be a non-empty string")
        for field_name in ("as_of", "generated_at"):
            value = getattr(self, field_name)
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if not isinstance(self.status, DailyIntelligenceStatus):
            raise TypeError("status must be a DailyIntelligenceStatus")
        if not isinstance(self.score, CapitalIntelligenceScore):
            raise TypeError("score must be a CapitalIntelligenceScore")
        if not isinstance(self.environment, MarketEnvironmentBrief):
            raise TypeError("environment must be a MarketEnvironmentBrief")
        if not isinstance(self.decision_card, CIODecisionCard):
            raise TypeError("decision_card must be a CIODecisionCard")
        if self.change_assessment is not None and not isinstance(
            self.change_assessment,
            MarketChangeAssessment,
        ):
            raise TypeError(
                "change_assessment must be a MarketChangeAssessment or None"
            )
        if self.score_delta is not None and (
            isinstance(self.score_delta, bool)
            or not isinstance(self.score_delta, int)
        ):
            raise TypeError("score_delta must be an int or None")
        if (
            not isinstance(self.change_summary, str)
            or not self.change_summary.strip()
        ):
            raise ValueError("change_summary must be a non-empty string")
        if not isinstance(self.replay_identifiers, tuple) or not all(
            isinstance(value, str) and value.strip()
            for value in self.replay_identifiers
        ):
            raise TypeError(
                "replay_identifiers must contain non-empty strings"
            )
        if not (
            self.as_of
            == self.score.as_of
            == self.environment.as_of
            == self.decision_card.as_of
        ):
            raise ValueError(
                "all daily surfaces must use the same as_of timestamp"
            )
        if (
            self.change_assessment is not None
            and self.change_assessment.current_as_of != self.as_of
        ):
            raise ValueError(
                "change_assessment must end at the snapshot as_of"
            )

    @property
    def changed_materially(self) -> bool:
        return self.environment.changed_materially

    @property
    def should_alert(self) -> bool:
        return self.environment.should_alert

    def to_record(self) -> DailySnapshotRecord:
        return DailySnapshotRecord(
            identifier=self.identifier,
            as_of=self.as_of,
            generated_at=self.generated_at,
            score=self.score.score,
            score_delta=self.score_delta,
            status=self.status,
            environment=self.score.environment,
            risk=self.score.risk,
            committee=self.score.committee,
            portfolio_impact=self.score.portfolio_impact,
            changed_materially=self.changed_materially,
            should_alert=self.should_alert,
            replay_identifiers=self.replay_identifiers,
        )


@dataclass(frozen=True, slots=True)
class DailyIntelligenceCycle:
    """Canonical outputs and the single application snapshot they produced."""

    run: InstitutionalRegimeRun
    decision: RegimeCommitteeDecision
    snapshot: DailyCapitalIntelligenceSnapshot
    change_assessment: MarketChangeAssessment | None = None


class SQLiteDailySnapshotStore:
    """Append-only local history for daily presentation snapshots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.exists() and self.path.is_dir():
            raise ValueError("snapshot path must be a file")
        self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_intelligence_snapshots (
                    identifier TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL UNIQUE,
                    generated_at TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    score_delta INTEGER,
                    status TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    committee TEXT NOT NULL,
                    portfolio_impact TEXT NOT NULL,
                    changed_materially INTEGER NOT NULL,
                    should_alert INTEGER NOT NULL,
                    replay_identifiers_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS daily_intelligence_as_of_desc
                ON daily_intelligence_snapshots (as_of DESC);

                CREATE TRIGGER IF NOT EXISTS daily_intelligence_prevent_update
                BEFORE UPDATE ON daily_intelligence_snapshots
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'daily intelligence history is append-only'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS daily_intelligence_prevent_delete
                BEFORE DELETE ON daily_intelligence_snapshots
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'daily intelligence history is append-only'
                    );
                END;
                """
            )

    def append(
        self,
        snapshot: DailyCapitalIntelligenceSnapshot,
    ) -> DailySnapshotRecord:
        if not isinstance(snapshot, DailyCapitalIntelligenceSnapshot):
            raise TypeError(
                "snapshot must be a DailyCapitalIntelligenceSnapshot"
            )
        record = snapshot.to_record()
        payload = json.dumps(
            daily_snapshot_to_dict(snapshot),
            sort_keys=True,
            separators=(",", ":"),
        )
        values = (
            record.identifier,
            record.as_of.isoformat(),
            record.generated_at.isoformat(),
            record.score,
            record.score_delta,
            record.status.value,
            record.environment,
            record.risk,
            record.committee,
            record.portfolio_impact,
            int(record.changed_materially),
            int(record.should_alert),
            json.dumps(record.replay_identifiers),
            payload,
        )
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT payload_json
                FROM daily_intelligence_snapshots
                WHERE identifier = ?
                """,
                (record.identifier,),
            ).fetchone()
            if existing is not None:
                if existing["payload_json"] != payload:
                    raise ValueError(
                        "snapshot identifier already exists with different content"
                    )
                return record
            connection.execute(
                """
                INSERT INTO daily_intelligence_snapshots (
                    identifier,
                    as_of,
                    generated_at,
                    score,
                    score_delta,
                    status,
                    environment,
                    risk,
                    committee,
                    portfolio_impact,
                    changed_materially,
                    should_alert,
                    replay_identifiers_json,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return record

    def latest(
        self,
        *,
        before: datetime | None = None,
    ) -> DailySnapshotRecord | None:
        parameters: tuple[object, ...] = ()
        where = ""
        if before is not None:
            if before.tzinfo is None or before.utcoffset() is None:
                raise ValueError("before must be timezone-aware")
            where = "WHERE as_of < ?"
            parameters = (before.isoformat(),)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM daily_intelligence_snapshots
                {where}
                ORDER BY as_of DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        return None if row is None else self._record_from_row(row)

    def history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[DailySnapshotRecord, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an int")
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM daily_intelligence_snapshots
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM daily_intelligence_snapshots
                """
            ).fetchone()
        return int(row["count"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> DailySnapshotRecord:
        return DailySnapshotRecord(
            identifier=row["identifier"],
            as_of=datetime.fromisoformat(row["as_of"]),
            generated_at=datetime.fromisoformat(row["generated_at"]),
            score=int(row["score"]),
            score_delta=(
                None
                if row["score_delta"] is None
                else int(row["score_delta"])
            ),
            status=DailyIntelligenceStatus(row["status"]),
            environment=row["environment"],
            risk=row["risk"],
            committee=row["committee"],
            portfolio_impact=row["portfolio_impact"],
            changed_materially=bool(row["changed_materially"]),
            should_alert=bool(row["should_alert"]),
            replay_identifiers=tuple(
                json.loads(row["replay_identifiers_json"])
            ),
        )


class DailyCapitalIntelligenceService:
    """Run the canonical chain and publish one consistent snapshot."""

    def __init__(
        self,
        pipeline: InstitutionalRegimePipeline,
        *,
        governance: RegimeGovernanceWorkflow | None = None,
        change_engine: RegimeMaterialChangeEngine | None = None,
        store: SQLiteDailySnapshotStore | None = None,
        clock: Callable[[], datetime] | None = None,
        maximum_age: timedelta = timedelta(hours=36),
    ) -> None:
        if not isinstance(pipeline, InstitutionalRegimePipeline):
            raise TypeError(
                "pipeline must be an InstitutionalRegimePipeline"
            )
        if maximum_age <= timedelta(0):
            raise ValueError("maximum_age must be positive")
        self.pipeline = pipeline
        self.governance = governance or RegimeGovernanceWorkflow()
        self.change_engine = change_engine or RegimeMaterialChangeEngine()
        self.store = store
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.maximum_age = maximum_age

    def run(
        self,
        *,
        as_of: datetime,
        previous_run: InstitutionalRegimeRun | None = None,
        previous_decision: RegimeCommitteeDecision | None = None,
        portfolio_fit: PortfolioFitDecision | None = None,
        replay_identifiers: tuple[str, ...] = (),
    ) -> DailyIntelligenceCycle:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if (previous_run is None) != (previous_decision is None):
            raise ValueError(
                "previous_run and previous_decision must be supplied together"
            )
        run = self.pipeline.run(as_of=as_of)
        decision = self.governance.evaluate(run)
        change = None
        if previous_run is not None and previous_decision is not None:
            change = self.change_engine.compare(
                previous_run,
                run,
                previous_decision,
                decision,
            )
        previous_record = (
            self.store.latest(before=as_of)
            if self.store is not None
            else None
        )
        snapshot = build_daily_capital_intelligence_snapshot(
            run,
            decision,
            generated_at=self._clock(),
            previous_record=previous_record,
            change=change,
            portfolio_fit=portfolio_fit,
            replay_identifiers=replay_identifiers,
            maximum_age=self.maximum_age,
        )
        if self.store is not None:
            self.store.append(snapshot)
        return DailyIntelligenceCycle(
            run=run,
            decision=decision,
            snapshot=snapshot,
            change_assessment=change,
        )


def build_daily_capital_intelligence_snapshot(
    run: InstitutionalRegimeRun,
    decision: RegimeCommitteeDecision,
    *,
    generated_at: datetime,
    previous_record: DailySnapshotRecord | None = None,
    change: MarketChangeAssessment | None = None,
    portfolio_fit: PortfolioFitDecision | None = None,
    replay_identifiers: tuple[str, ...] = (),
    maximum_age: timedelta = timedelta(hours=36),
) -> DailyCapitalIntelligenceSnapshot:
    """Assemble every opening-screen field from the same canonical run."""

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    if maximum_age <= timedelta(0):
        raise ValueError("maximum_age must be positive")
    card = build_cio_decision_card(
        run,
        decision,
        change=change,
        portfolio_fit=portfolio_fit,
    )
    score = build_capital_intelligence_score(
        run,
        decision,
        change=change,
        portfolio_fit=portfolio_fit,
    )
    environment = build_market_environment_brief(
        run,
        decision,
        change=change,
    )
    timestamp = run.as_of.isoformat()
    if timestamp not in decision.recommendation.identifier:
        raise ValueError("decision must reference run")
    if score.decision_identifier != decision.decision_identifier:
        raise ValueError("score must reference decision")
    score_delta = (
        None
        if previous_record is None
        else score.score - previous_record.score
    )
    status = _status_for(
        run,
        card,
        generated_at=generated_at,
        maximum_age=maximum_age,
    )
    change_summary = _change_summary(
        change,
        score_delta=score_delta,
    )
    return DailyCapitalIntelligenceSnapshot(
        identifier=f"daily-capital-intelligence:{timestamp}",
        as_of=run.as_of,
        generated_at=generated_at,
        status=status,
        score=score,
        score_delta=score_delta,
        environment=environment,
        decision_card=card,
        change_assessment=change,
        change_summary=change_summary,
        replay_identifiers=replay_identifiers,
    )


def daily_snapshot_to_dict(
    snapshot: DailyCapitalIntelligenceSnapshot,
) -> dict[str, Any]:
    if not isinstance(snapshot, DailyCapitalIntelligenceSnapshot):
        raise TypeError(
            "snapshot must be a DailyCapitalIntelligenceSnapshot"
        )
    return {
        "schema_version": "daily-capital-intelligence.v1",
        "identifier": snapshot.identifier,
        "as_of": snapshot.as_of.isoformat(),
        "generated_at": snapshot.generated_at.isoformat(),
        "status": snapshot.status.value,
        "score": capital_intelligence_score_to_dict(snapshot.score),
        "score_delta": snapshot.score_delta,
        "environment": market_environment_brief_to_dict(
            snapshot.environment
        ),
        "decision_card": decision_card_to_dict(
            snapshot.decision_card
        ),
        "change": (
            None
            if snapshot.change_assessment is None
            else {
                "identifier": snapshot.change_assessment.identifier,
                "state": snapshot.change_assessment.state.value,
                "alert_level": (
                    snapshot.change_assessment.alert_level.value
                ),
                "headline": snapshot.change_assessment.headline,
                "explanation": snapshot.change_assessment.explanation,
            }
        ),
        "change_summary": snapshot.change_summary,
        "changed_materially": snapshot.changed_materially,
        "should_alert": snapshot.should_alert,
        "decision_replays": list(snapshot.replay_identifiers),
        "sources": {
            "regime_run": snapshot.score.regime_run_identifier,
            "decision": snapshot.score.decision_identifier,
        },
    }


def _status_for(
    run: InstitutionalRegimeRun,
    card: CIODecisionCard,
    *,
    generated_at: datetime,
    maximum_age: timedelta,
) -> DailyIntelligenceStatus:
    if run.loaded_count == 0:
        return DailyIntelligenceStatus.UNAVAILABLE
    if generated_at - run.as_of > maximum_age:
        return DailyIntelligenceStatus.STALE
    if card.data_status != "Complete":
        return DailyIntelligenceStatus.INCOMPLETE
    return DailyIntelligenceStatus.CURRENT


def _change_summary(
    change: MarketChangeAssessment | None,
    *,
    score_delta: int | None,
) -> str:
    if change is not None:
        return change.explanation
    if score_delta is None:
        return (
            "This is the first canonical daily snapshot; "
            "no prior comparison is available."
        )
    if score_delta == 0:
        return (
            "The Capital Intelligence Score is unchanged "
            "from the prior snapshot."
        )
    direction = "increased" if score_delta > 0 else "decreased"
    return (
        f"The Capital Intelligence Score {direction} "
        f"by {abs(score_delta)} points."
    )


__all__ = [
    "DailyCapitalIntelligenceService",
    "DailyCapitalIntelligenceSnapshot",
    "DailyIntelligenceCycle",
    "DailyIntelligenceStatus",
    "DailySnapshotRecord",
    "SQLiteDailySnapshotStore",
    "build_daily_capital_intelligence_snapshot",
    "daily_snapshot_to_dict",
]
