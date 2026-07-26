"""Append-only policy and weighted synthesis persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from intelligence.synthesis_weights import (
    EngineSynthesisWeight,
    MissingWeightPolicy,
    MultiEngineSynthesisResult,
    SynthesisStatus,
    SynthesisWeightPolicy,
    WeightedEngineContribution,
)


class SQLiteSynthesisStore:
    """Persist versioned weight policies and synthesis results."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("synthesis store path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS multi_engine_synthesis_policies (
                    version TEXT PRIMARY KEY,
                    published_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS synthesis_policy_latest
                ON multi_engine_synthesis_policies (published_at DESC);

                CREATE TABLE IF NOT EXISTS multi_engine_synthesis_results (
                    identifier TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    normalization_bundle_identifier TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (policy_version, as_of),
                    FOREIGN KEY (policy_version)
                        REFERENCES multi_engine_synthesis_policies(version)
                );
                CREATE INDEX IF NOT EXISTS synthesis_result_latest
                ON multi_engine_synthesis_results (as_of DESC);

                CREATE TRIGGER IF NOT EXISTS synthesis_policy_prevent_update
                BEFORE UPDATE ON multi_engine_synthesis_policies
                BEGIN
                    SELECT RAISE(ABORT, 'synthesis policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS synthesis_policy_prevent_delete
                BEFORE DELETE ON multi_engine_synthesis_policies
                BEGIN
                    SELECT RAISE(ABORT, 'synthesis policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS synthesis_result_prevent_update
                BEFORE UPDATE ON multi_engine_synthesis_results
                BEGIN
                    SELECT RAISE(ABORT, 'synthesis result history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS synthesis_result_prevent_delete
                BEFORE DELETE ON multi_engine_synthesis_results
                BEGIN
                    SELECT RAISE(ABORT, 'synthesis result history is append-only');
                END;
                """
            )

    def append_policy(self, policy: SynthesisWeightPolicy) -> SynthesisWeightPolicy:
        if self.read_only:
            raise PermissionError("synthesis store is read-only")
        if not isinstance(policy, SynthesisWeightPolicy):
            raise TypeError("policy must be a SynthesisWeightPolicy")
        payload = json.dumps(policy.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM multi_engine_synthesis_policies
                WHERE version = ?
                """,
                (policy.version,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "synthesis policy version already exists with different content"
                    )
                return policy
            connection.execute(
                """
                INSERT INTO multi_engine_synthesis_policies (
                    version, published_at, payload_json
                ) VALUES (?, ?, ?)
                """,
                (policy.version, policy.published_at.isoformat(), payload),
            )
        return policy

    def append(
        self,
        result: MultiEngineSynthesisResult,
    ) -> MultiEngineSynthesisResult:
        if self.read_only:
            raise PermissionError("synthesis store is read-only")
        if not isinstance(result, MultiEngineSynthesisResult):
            raise TypeError("result must be a MultiEngineSynthesisResult")
        payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            policy = connection.execute(
                """
                SELECT version
                FROM multi_engine_synthesis_policies
                WHERE version = ?
                """,
                (result.policy_version,),
            ).fetchone()
            if policy is None:
                raise ValueError("synthesis policy must be appended before its result")
            row = connection.execute(
                """
                SELECT payload_json
                FROM multi_engine_synthesis_results
                WHERE identifier = ? OR (policy_version = ? AND as_of = ?)
                """,
                (
                    result.identifier,
                    result.policy_version,
                    result.as_of.isoformat(),
                ),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "synthesis result already exists with different content"
                    )
                return result
            connection.execute(
                """
                INSERT INTO multi_engine_synthesis_results (
                    identifier, as_of, generated_at, policy_version,
                    normalization_bundle_identifier, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.identifier,
                    result.as_of.isoformat(),
                    result.generated_at.isoformat(),
                    result.policy_version,
                    result.normalization_bundle_identifier,
                    payload,
                ),
            )
        return result

    def latest(
        self,
        *,
        at_or_before: datetime | None = None,
    ) -> MultiEngineSynthesisResult | None:
        where = ""
        parameters: tuple[object, ...] = ()
        if at_or_before is not None:
            self._require_aware(at_or_before)
            where = "WHERE as_of <= ?"
            parameters = (at_or_before.isoformat(),)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    f"""
                    SELECT payload_json
                    FROM multi_engine_synthesis_results
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
        return None if row is None else synthesis_result_from_dict(
            json.loads(row["payload_json"])
        )

    def history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[MultiEngineSynthesisResult, ...]:
        self._require_limit(limit)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_synthesis_results
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
            synthesis_result_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def latest_policy(self) -> SynthesisWeightPolicy | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_synthesis_policies
                    ORDER BY published_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return None
            raise
        return None if row is None else synthesis_policy_from_dict(
            json.loads(row["payload_json"])
        )

    def policy_history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[SynthesisWeightPolicy, ...]:
        self._require_limit(limit)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_synthesis_policies
                    ORDER BY published_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return ()
            raise
        return tuple(
            synthesis_policy_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def readiness(self) -> tuple[bool, str]:
        try:
            with self._connect() as connection:
                tables = {
                    row["name"]
                    for row in connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                          AND name IN (
                              'multi_engine_synthesis_policies',
                              'multi_engine_synthesis_results'
                          )
                        """
                    ).fetchall()
                }
                if len(tables) < 2:
                    return (
                        True,
                        "weighted synthesis history has not been created; "
                        "normalization remains available",
                    )
                connection.execute(
                    "SELECT COUNT(*) FROM multi_engine_synthesis_policies"
                ).fetchone()
                connection.execute(
                    "SELECT COUNT(*) FROM multi_engine_synthesis_results"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"synthesis store is unavailable: {error}"
        return True, "append-only synthesis policy and result history is available"

    def _connect(self) -> sqlite3.Connection:
        if self.read_only:
            if not self.path.exists():
                raise FileNotFoundError(self.path)
            encoded = quote(str(self.path.resolve()), safe="/")
            connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True)
            connection.execute("PRAGMA query_only = ON")
        else:
            connection = sqlite3.connect(self.path)
            connection.execute("PRAGMA foreign_keys = ON")
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("at_or_before must be timezone-aware")

    @staticmethod
    def _require_limit(limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")


def synthesis_policy_from_dict(payload: dict) -> SynthesisWeightPolicy:
    return SynthesisWeightPolicy(
        version=payload["version"],
        published_at=datetime.fromisoformat(payload["published_at"]),
        weights=tuple(
            EngineSynthesisWeight(
                engine=item["engine"],
                opportunity_weight_bps=int(item["opportunity_weight_bps"]),
                risk_weight_bps=int(item["risk_weight_bps"]),
                evidence_weight_bps=int(item["evidence_weight_bps"]),
                rationale=item["rationale"],
            )
            for item in payload["weights"]
        ),
        minimum_opportunity_coverage_bps=int(
            payload["minimum_opportunity_coverage_bps"]
        ),
        minimum_risk_coverage_bps=int(payload["minimum_risk_coverage_bps"]),
        minimum_evidence_coverage_bps=int(
            payload["minimum_evidence_coverage_bps"]
        ),
        minimum_available_engines=int(payload["minimum_available_engines"]),
        missing_weight_policy=MissingWeightPolicy(
            payload["missing_weight_policy"]
        ),
        regime_sensitive=bool(payload["regime_sensitive"]),
        change_rationale=payload["change_rationale"],
    )


def synthesis_result_from_dict(payload: dict) -> MultiEngineSynthesisResult:
    contributions = tuple(
        WeightedEngineContribution(
            engine=item["engine"],
            normalized_assessment_identifier=(
                item["normalized_assessment_identifier"]
            ),
            available=bool(item["available"]),
            opportunity_weight_bps=int(item["opportunity_weight_bps"]),
            risk_weight_bps=int(item["risk_weight_bps"]),
            evidence_weight_bps=int(item["evidence_weight_bps"]),
            opportunity_score=(
                None
                if item.get("opportunity_score") is None
                else int(item["opportunity_score"])
            ),
            risk_score=(
                None
                if item.get("risk_score") is None
                else int(item["risk_score"])
            ),
            confidence_score=int(item["confidence_score"]),
            data_quality_score=int(item["data_quality_score"]),
            opportunity_weighted_points=item.get(
                "opportunity_weighted_points"
            ),
            risk_weighted_points=item.get("risk_weighted_points"),
            confidence_weighted_points=item.get(
                "confidence_weighted_points"
            ),
            data_quality_weighted_points=item.get(
                "data_quality_weighted_points"
            ),
        )
        for item in payload["contributions"]
    )
    return MultiEngineSynthesisResult(
        identifier=payload["identifier"],
        policy_version=payload["policy_version"],
        policy_published_at=datetime.fromisoformat(
            payload["policy_published_at"]
        ),
        normalization_bundle_identifier=(
            payload["normalization_bundle_identifier"]
        ),
        normalization_policy_version=payload["normalization_policy_version"],
        as_of=datetime.fromisoformat(payload["as_of"]),
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        status=SynthesisStatus(payload["status"]),
        aggregate_opportunity_score=(
            None
            if payload.get("aggregate_opportunity_score") is None
            else int(payload["aggregate_opportunity_score"])
        ),
        aggregate_risk_score=(
            None
            if payload.get("aggregate_risk_score") is None
            else int(payload["aggregate_risk_score"])
        ),
        aggregate_confidence_score=(
            None
            if payload.get("aggregate_confidence_score") is None
            else int(payload["aggregate_confidence_score"])
        ),
        aggregate_data_quality_score=(
            None
            if payload.get("aggregate_data_quality_score") is None
            else int(payload["aggregate_data_quality_score"])
        ),
        opportunity_weight_coverage_bps=int(
            payload["opportunity_weight_coverage_bps"]
        ),
        risk_weight_coverage_bps=int(payload["risk_weight_coverage_bps"]),
        evidence_weight_coverage_bps=int(
            payload["evidence_weight_coverage_bps"]
        ),
        minimum_available_engines=int(payload["minimum_available_engines"]),
        available_engine_count=int(payload["available_engine_count"]),
        missing_engines=tuple(payload.get("missing_engines", ())),
        insufficiency_reasons=tuple(
            payload.get("insufficiency_reasons", ())
        ),
        contributions=contributions,
    )


__all__ = [
    "SQLiteSynthesisStore",
    "synthesis_policy_from_dict",
    "synthesis_result_from_dict",
]
