"""Append-only persistence for versioned analytical-engine results."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from intelligence.analytical_engine import (
    AnalyticalEngineResult,
    EngineDataStatus,
    EngineDirection,
    EngineEvidence,
)


class SQLiteAnalyticalEngineStore:
    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("analytical engine path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analytical_engine_results (
                    identifier TEXT PRIMARY KEY,
                    engine TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (engine, as_of)
                );
                CREATE INDEX IF NOT EXISTS analytical_engine_latest
                ON analytical_engine_results (engine, as_of DESC);

                CREATE TRIGGER IF NOT EXISTS analytical_engine_prevent_update
                BEFORE UPDATE ON analytical_engine_results
                BEGIN
                    SELECT RAISE(ABORT, 'analytical engine history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS analytical_engine_prevent_delete
                BEFORE DELETE ON analytical_engine_results
                BEGIN
                    SELECT RAISE(ABORT, 'analytical engine history is append-only');
                END;
                """
            )

    def append(self, result: AnalyticalEngineResult) -> AnalyticalEngineResult:
        if self.read_only:
            raise PermissionError("analytical engine store is read-only")
        if not isinstance(result, AnalyticalEngineResult):
            raise TypeError("result must be an AnalyticalEngineResult")
        payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM analytical_engine_results
                WHERE identifier = ? OR (engine = ? AND as_of = ?)
                """,
                (result.identifier, result.engine, result.as_of.isoformat()),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "analytical engine result already exists with different content"
                    )
                return result
            connection.execute(
                """
                INSERT INTO analytical_engine_results (
                    identifier, engine, as_of, generated_at,
                    policy_version, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.identifier,
                    result.engine,
                    result.as_of.isoformat(),
                    result.generated_at.isoformat(),
                    result.policy_version,
                    payload,
                ),
            )
        return result

    def latest(
        self,
        engine: str,
        *,
        at_or_before: datetime | None = None,
    ) -> AnalyticalEngineResult | None:
        normalized = engine.strip()
        if not normalized:
            raise ValueError("engine cannot be empty")
        where = "engine = ?"
        parameters: list[object] = [normalized]
        if at_or_before is not None:
            if at_or_before.tzinfo is None or at_or_before.utcoffset() is None:
                raise ValueError("at_or_before must be timezone-aware")
            where += " AND as_of <= ?"
            parameters.append(at_or_before.isoformat())
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT payload_json FROM analytical_engine_results
                WHERE {where}
                ORDER BY as_of DESC
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
        return None if row is None else analytical_engine_result_from_dict(
            json.loads(row["payload_json"])
        )

    def history(
        self,
        engine: str,
        *,
        limit: int = 30,
    ) -> tuple[AnalyticalEngineResult, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        normalized = engine.strip()
        if not normalized:
            raise ValueError("engine cannot be empty")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM analytical_engine_results
                WHERE engine = ?
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
        return tuple(
            analytical_engine_result_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                connection.execute(
                    "SELECT COUNT(*) FROM analytical_engine_results"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"analytical engine store is unavailable: {error}"
        return True, "append-only analytical engine history is available"

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            encoded = quote(str(self.path.resolve()), safe="/")
            connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def analytical_engine_result_from_dict(payload: dict) -> AnalyticalEngineResult:
    evidence = tuple(
        EngineEvidence(
            identifier=item["identifier"],
            component=item["component"],
            indicator=item["indicator"],
            provider=item["provider"],
            series_identifier=item["series_identifier"],
            observation_date=date.fromisoformat(item["observation_date"]),
            released_at=datetime.fromisoformat(item["released_at"]),
            retrieved_at=datetime.fromisoformat(item["retrieved_at"]),
            vintage_date=(
                None
                if item.get("vintage_date") is None
                else date.fromisoformat(item["vintage_date"])
            ),
            quality_state=item["quality_state"],
            signal_score=float(item["signal_score"]),
            weighted_contribution=float(item["weighted_contribution"]),
            explanation=item["explanation"],
        )
        for item in payload.get("evidence", ())
    )
    return AnalyticalEngineResult(
        identifier=payload["identifier"],
        engine=payload["engine"],
        scope=payload["scope"],
        policy_version=payload["policy_version"],
        as_of=datetime.fromisoformat(payload["as_of"]),
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        direction=EngineDirection(payload["direction"]),
        score=int(payload["score"]),
        confidence=int(payload["confidence"]),
        coverage=float(payload["coverage"]),
        data_status=EngineDataStatus(payload["data_status"]),
        summary=payload["summary"],
        explanation=payload["explanation"],
        risks=tuple(payload.get("risks", ())),
        transmission_channels=tuple(payload.get("transmission_channels", ())),
        review_conditions=tuple(payload.get("review_conditions", ())),
        evidence=evidence,
    )


__all__ = [
    "SQLiteAnalyticalEngineStore",
    "analytical_engine_result_from_dict",
]
