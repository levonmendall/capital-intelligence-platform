"""Append-only policy and result persistence for multi-engine governance."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from intelligence.analytical_engine import EngineDirection
from intelligence.governance import (
    ActiveGovernanceVeto,
    GovernanceIssue,
    GovernanceStatus,
    IssueSeverity,
    MultiEngineGovernancePolicy,
    MultiEngineGovernanceResult,
    PositiveConclusionCeiling,
    VetoType,
)
from intelligence.synthesis_weights import SynthesisStatus


class SQLiteGovernanceStore:
    """Persist immutable governance policies and evidence dispositions."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        if self.path.exists() and self.path.is_dir():
            raise ValueError("governance store path must be a file")
        if not read_only:
            self.initialize()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS multi_engine_governance_policies (
                    version TEXT PRIMARY KEY,
                    published_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS governance_policy_latest
                ON multi_engine_governance_policies (published_at DESC);

                CREATE TABLE IF NOT EXISTS multi_engine_governance_results (
                    identifier TEXT PRIMARY KEY,
                    as_of TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    synthesis_result_identifier TEXT NOT NULL,
                    normalization_bundle_identifier TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (policy_version, as_of),
                    FOREIGN KEY (policy_version)
                        REFERENCES multi_engine_governance_policies(version)
                );
                CREATE INDEX IF NOT EXISTS governance_result_latest
                ON multi_engine_governance_results (as_of DESC);

                CREATE TRIGGER IF NOT EXISTS governance_policy_prevent_update
                BEFORE UPDATE ON multi_engine_governance_policies
                BEGIN
                    SELECT RAISE(ABORT, 'governance policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_policy_prevent_delete
                BEFORE DELETE ON multi_engine_governance_policies
                BEGIN
                    SELECT RAISE(ABORT, 'governance policy history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_result_prevent_update
                BEFORE UPDATE ON multi_engine_governance_results
                BEGIN
                    SELECT RAISE(ABORT, 'governance result history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS governance_result_prevent_delete
                BEFORE DELETE ON multi_engine_governance_results
                BEGIN
                    SELECT RAISE(ABORT, 'governance result history is append-only');
                END;
                """
            )

    def append_policy(
        self,
        policy: MultiEngineGovernancePolicy,
    ) -> MultiEngineGovernancePolicy:
        if self.read_only:
            raise PermissionError("governance store is read-only")
        if not isinstance(policy, MultiEngineGovernancePolicy):
            raise TypeError("policy must be a MultiEngineGovernancePolicy")
        payload = json.dumps(policy.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM multi_engine_governance_policies
                WHERE version = ?
                """,
                (policy.version,),
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload:
                    raise ValueError(
                        "governance policy version already exists with different content"
                    )
                return policy
            connection.execute(
                """
                INSERT INTO multi_engine_governance_policies (
                    version, published_at, payload_json
                ) VALUES (?, ?, ?)
                """,
                (policy.version, policy.published_at.isoformat(), payload),
            )
        return policy

    def append(
        self,
        result: MultiEngineGovernanceResult,
    ) -> MultiEngineGovernanceResult:
        if self.read_only:
            raise PermissionError("governance store is read-only")
        if not isinstance(result, MultiEngineGovernanceResult):
            raise TypeError("result must be a MultiEngineGovernanceResult")
        payload = json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            policy = connection.execute(
                """
                SELECT version
                FROM multi_engine_governance_policies
                WHERE version = ?
                """,
                (result.policy_version,),
            ).fetchone()
            if policy is None:
                raise ValueError("governance policy must be appended before its result")
            row = connection.execute(
                """
                SELECT payload_json
                FROM multi_engine_governance_results
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
                        "governance result already exists with different content"
                    )
                return result
            connection.execute(
                """
                INSERT INTO multi_engine_governance_results (
                    identifier, as_of, generated_at, policy_version,
                    synthesis_result_identifier, normalization_bundle_identifier,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.identifier,
                    result.as_of.isoformat(),
                    result.generated_at.isoformat(),
                    result.policy_version,
                    result.synthesis_result_identifier,
                    result.normalization_bundle_identifier,
                    payload,
                ),
            )
        return result

    def latest(
        self,
        *,
        at_or_before: datetime | None = None,
    ) -> MultiEngineGovernanceResult | None:
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
                    FROM multi_engine_governance_results
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
        return None if row is None else governance_result_from_dict(
            json.loads(row["payload_json"])
        )

    def history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[MultiEngineGovernanceResult, ...]:
        self._require_limit(limit)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_governance_results
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
            governance_result_from_dict(json.loads(row["payload_json"]))
            for row in rows
        )

    def latest_policy(self) -> MultiEngineGovernancePolicy | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_governance_policies
                    ORDER BY published_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return None
            raise
        return None if row is None else governance_policy_from_dict(
            json.loads(row["payload_json"])
        )

    def policy_history(
        self,
        *,
        limit: int = 30,
    ) -> tuple[MultiEngineGovernancePolicy, ...]:
        self._require_limit(limit)
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM multi_engine_governance_policies
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
            governance_policy_from_dict(json.loads(row["payload_json"]))
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
                              'multi_engine_governance_policies',
                              'multi_engine_governance_results'
                          )
                        """
                    ).fetchall()
                }
                if len(tables) < 2:
                    return (
                        True,
                        "governance history has not been created; weighted synthesis "
                        "remains available",
                    )
                connection.execute(
                    "SELECT COUNT(*) FROM multi_engine_governance_policies"
                ).fetchone()
                connection.execute(
                    "SELECT COUNT(*) FROM multi_engine_governance_results"
                ).fetchone()
        except (OSError, sqlite3.Error) as error:
            return False, f"governance store is unavailable: {error}"
        return True, "append-only governance policy and result history is available"

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


def governance_policy_from_dict(payload: dict) -> MultiEngineGovernancePolicy:
    return MultiEngineGovernancePolicy(
        version=payload["version"],
        published_at=datetime.fromisoformat(payload["published_at"]),
        minimum_confidence_score=int(payload["minimum_confidence_score"]),
        minimum_data_quality_score=int(payload["minimum_data_quality_score"]),
        hard_minimum_confidence_score=int(payload["hard_minimum_confidence_score"]),
        hard_minimum_data_quality_score=int(
            payload["hard_minimum_data_quality_score"]
        ),
        conflict_opportunity_threshold=int(
            payload["conflict_opportunity_threshold"]
        ),
        conflict_risk_threshold=int(payload["conflict_risk_threshold"]),
        engine_support_threshold=int(payload["engine_support_threshold"]),
        engine_risk_threshold=int(payload["engine_risk_threshold"]),
        minimum_conflict_engines_per_side=int(
            payload["minimum_conflict_engines_per_side"]
        ),
        credit_veto_risk_threshold=int(payload["credit_veto_risk_threshold"]),
        risk_veto_risk_threshold=int(payload["risk_veto_risk_threshold"]),
        veto_minimum_confidence_score=int(
            payload["veto_minimum_confidence_score"]
        ),
        veto_minimum_data_quality_score=int(
            payload["veto_minimum_data_quality_score"]
        ),
        incomplete_confidence_ceiling=int(
            payload["incomplete_confidence_ceiling"]
        ),
        stale_confidence_ceiling=int(payload["stale_confidence_ceiling"]),
        critical_stale_confidence_ceiling=int(
            payload["critical_stale_confidence_ceiling"]
        ),
        conflict_confidence_ceiling=int(payload["conflict_confidence_ceiling"]),
        veto_confidence_ceiling=int(payload["veto_confidence_ceiling"]),
        critical_engines=tuple(payload["critical_engines"]),
        change_rationale=payload["change_rationale"],
    )


def governance_result_from_dict(payload: dict) -> MultiEngineGovernanceResult:
    issues = tuple(
        GovernanceIssue(
            code=item["code"],
            severity=IssueSeverity(item["severity"]),
            message=item["message"],
            confidence_ceiling=int(item["confidence_ceiling"]),
            engine=item.get("engine"),
        )
        for item in payload.get("issues", ())
    )
    vetoes = tuple(
        ActiveGovernanceVeto(
            veto_type=VetoType(item["veto_type"]),
            engine=item["engine"],
            normalized_assessment_identifier=(
                item["normalized_assessment_identifier"]
            ),
            source_direction=EngineDirection(item["source_direction"]),
            risk_score=int(item["risk_score"]),
            confidence_score=int(item["confidence_score"]),
            data_quality_score=int(item["data_quality_score"]),
            reason=item["reason"],
        )
        for item in payload.get("active_vetoes", ())
    )
    return MultiEngineGovernanceResult(
        identifier=payload["identifier"],
        policy_version=payload["policy_version"],
        policy_published_at=datetime.fromisoformat(payload["policy_published_at"]),
        synthesis_result_identifier=payload["synthesis_result_identifier"],
        synthesis_policy_version=payload["synthesis_policy_version"],
        normalization_bundle_identifier=payload["normalization_bundle_identifier"],
        normalization_policy_version=payload["normalization_policy_version"],
        as_of=datetime.fromisoformat(payload["as_of"]),
        generated_at=datetime.fromisoformat(payload["generated_at"]),
        status=GovernanceStatus(payload["status"]),
        source_synthesis_status=SynthesisStatus(payload["source_synthesis_status"]),
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
        governed_confidence_score=(
            None
            if payload.get("governed_confidence_score") is None
            else int(payload["governed_confidence_score"])
        ),
        confidence_ceiling=int(payload["confidence_ceiling"]),
        decision_available=bool(payload["decision_available"]),
        committee_submission_eligible=bool(
            payload["committee_submission_eligible"]
        ),
        requires_human_review=bool(payload["requires_human_review"]),
        positive_conclusion_ceiling=PositiveConclusionCeiling(
            payload["positive_conclusion_ceiling"]
        ),
        issues=issues,
        active_vetoes=vetoes,
        supportive_engines=tuple(payload.get("supportive_engines", ())),
        adverse_engines=tuple(payload.get("adverse_engines", ())),
        incomplete_engines=tuple(payload.get("incomplete_engines", ())),
        stale_engines=tuple(payload.get("stale_engines", ())),
    )


__all__ = [
    "SQLiteGovernanceStore",
    "governance_policy_from_dict",
    "governance_result_from_dict",
]
