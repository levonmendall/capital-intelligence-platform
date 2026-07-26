"""Append-only persistence for multi-engine normalization bundles."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.normalization import (
    MultiEngineNormalizationBundle,
    NormalizedEngineAssessment,
)


class SQLiteNormalizationStore:
    """Persist normalization bundles beside raw analytical-engine results."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("normalization store path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS multi_engine_normalization_bundles (
                    identifier TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL UNIQUE,
                    generated_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS multi_engine_normalization_latest
                ON multi_engine_normalization_bundles (as_of DESC);

                CREATE TRIGGER IF NOT EXISTS normalization_prevent_update
                BEFORE UPDATE ON multi_engine_normalization_bundles
                BEGIN
                    SELECT RAISE(ABORT, 'normalization history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS normalization_prevent_delete
                BEFORE DELETE ON multi_engine_normalization_bundles
                BEGIN
                    SELECT RAISE(ABORT, 'normalization history is append-only');
                END;
                """
            )

    def append(
        self,
        bundle: MultiEngineNormalizationBundle,
    ) -> MultiEngineNormalizationBundle:
        if self.read_only:
            raise PermissionError("normalization store is read-only")
        if not isinstance(bundle, MultiEngineNormalizationBundle):
            raise TypeError("bundle must be a MultiEngineNormalizationBundle")
        payload = json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM multi_engine_normalization_bundles
                WHERE identifier = ? OR as_of = ?
                """,
                (bundle.identifier, bundle.as_of.isoformat()),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "normalization bundle already exists with different content"
                    )
                return bundle
            connection.execute(
                """
                INSERT INTO multi_engine_normalization_bundles (
                    identifier, as_of, generated_at, policy_version, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    bundle.identifier,
                    bundle.as_of.isoformat(),
                    bundle.generated_at.isoformat(),
                    bundle.policy_version,
                    payload,
                ),
            )
        return bundle

    def latest(
        self,
        *,
        at_or_before: datetime | None = None,
    ) -> MultiEngineNormalizationBundle | None:
        where = ""
        parameters: tuple[object, ...] = ()
        if at_or_before is not None:
            if at_or_before.tzinfo is None or at_or_before.utcoffset() is None:
                raise ValueError("at_or_before must be timezone-aware")
            where = "WHERE as_of <= ?"
            parameters = (at_or_before.isoformat(),)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    f"""
                    SELECT payload_json
                    FROM multi_engine_normalization_bundles
                    {where}
                    ORDER BY as_of DESC
                    LIMIT 1
                    """,
                    parameters,
                ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return None
            raise
        return None if row is None else normalization_bundle_from_dict(
            json.loads(row["payload_json"])
        )

    def history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[MultiEngineNormalizationBundle, ...]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_normalization_bundles
                    ORDER BY as_of DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return ()
            raise
        return tuple(
            normalization_bundle_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                table = connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'multi_engine_normalization_bundles'
                    """
                ).fetchone()
                if table is None:
                    return (
                        True,
                        "normalization history has not been created; raw analytical "
                        "engine results remain available",
                    )
                connection.execute(
                    "SELECT COUNT(*) FROM multi_engine_normalization_bundles"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"normalization store is unavailable: {error}"
        return True, "append-only multi-engine normalization history is available"

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


def normalization_bundle_from_dict(
    payload: dict,
) -> MultiEngineNormalizationBundle:
    assessments = tuple(
        NormalizedEngineAssessment(
            identifier=item["identifier"],
            engine=item["engine"],
            role=item["role"],
            normalization_policy_version=item["normalization_policy_version"],
            source_result_identifier=item.get("source_result_identifier"),
            source_policy_version=item.get("source_policy_version"),
            as_of=datetime.fromisoformat(item["as_of"]),
            generated_at=datetime.fromisoformat(item["generated_at"]),
            source_direction=EngineDirection(item["source_direction"]),
            source_score=(
                None if item.get("source_score") is None else int(item["source_score"])
            ),
            source_confidence=int(item["source_confidence"]),
            opportunity_score=(
                None
                if item.get("opportunity_score") is None
                else int(item["opportunity_score"])
            ),
            risk_score=(
                None if item.get("risk_score") is None else int(item["risk_score"])
            ),
            confidence_score=int(item["confidence_score"]),
            data_quality_score=int(item["data_quality_score"]),
            coverage=float(item["coverage"]),
            freshness_days=(
                None
                if item.get("freshness_days") is None
                else int(item["freshness_days"])
            ),
            materiality_score=int(item["materiality_score"]),
            data_status=EngineDataStatus(item["data_status"]),
            supporting_evidence_identifiers=tuple(
                item.get("supporting_evidence_identifiers", ())
            ),
            contradictory_evidence_identifiers=tuple(
                item.get("contradictory_evidence_identifiers", ())
            ),
            explanation=item["explanation"],
        )
        for item in payload.get("assessments", ())
    )
    return MultiEngineNormalizationBundle(
        identifier=payload["identifier"],
        policy_version=payload["policy_version"],
        as_of=datetime.fromisoformat(payload["as_of"]),
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        expected_engines=tuple(payload["expected_engines"]),
        assessments=assessments,
    )


__all__ = [
    "SQLiteNormalizationStore",
    "normalization_bundle_from_dict",
]
