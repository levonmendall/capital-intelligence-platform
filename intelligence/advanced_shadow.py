"""Append-only shadow-mode inventory for advanced investment intelligence.

The coordinator is intentionally downstream of the canonical CIO and construction
cycle. It records which advanced engines had sufficient governed inputs during each
real cycle and which remained fail-closed awaiting evidence. Shadow records cannot
change candidates, specialist calculations, CIO decisions, construction, or execution.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class AdvancedEngine(str, Enum):
    CAUSAL_REASONING = "grounded_causal_reasoning"
    PRIMARY_SOURCE_DOCUMENTS = "primary_source_document_intelligence"
    INVESTMENT_GRAPH = "semantic_investment_graph"
    VALUE_OF_INFORMATION = "value_of_information_research_planner"
    ADVERSARIAL_CHALLENGE = "adversarial_cio_challenge"
    FORECAST_LEDGER = "claim_level_forecast_ledger"
    PORTFOLIO_DIGITAL_TWIN = "portfolio_digital_twin"
    STRUCTURAL_BREAKS = "structural_break_detection"
    CHAMPION_CHALLENGER = "champion_challenger_governance"
    INSTITUTIONAL_DATA = "institutional_data_activation"


class ShadowEngineState(str, Enum):
    OBSERVED = "observed"
    AWAITING_GOVERNED_INPUT = "awaiting_governed_input"
    DISABLED_PENDING_CERTIFICATION = "disabled_pending_certification"


@dataclass(frozen=True, slots=True)
class ShadowEngineRecord:
    engine: AdvancedEngine
    state: ShadowEngineState
    detail: str
    evidence_identifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AdvancedShadowSnapshot:
    cycle_identifier: str
    as_of: datetime
    code_version: str
    records: tuple[ShadowEngineRecord, ...]
    excluded_from_cio_calculations: bool = True
    authorizes_portfolio_change: bool = False
    schema_version: str = "advanced-intelligence-shadow.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_identifier": self.cycle_identifier,
            "as_of": self.as_of.isoformat(),
            "code_version": self.code_version,
            "records": [
                {
                    "engine": item.engine.value,
                    "state": item.state.value,
                    "detail": item.detail,
                    "evidence_identifiers": list(item.evidence_identifiers),
                }
                for item in self.records
            ],
            "excluded_from_cio_calculations": self.excluded_from_cio_calculations,
            "authorizes_portfolio_change": self.authorizes_portfolio_change,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }


class AdvancedIntelligenceShadowCoordinator:
    version = "advanced-intelligence-shadow.v1"

    def observe_cycle(
        self,
        *,
        cycle_identifier: str,
        as_of: datetime,
        code_version: str,
        candidate_count: int,
        specialist_context_count: int,
        decision_count: int,
        alternative_count: int,
        posture_identifier: str,
        institutional_provider_count: int = 0,
    ) -> AdvancedShadowSnapshot:
        if not cycle_identifier.strip() or not code_version.strip() or not posture_identifier.strip():
            raise ValueError("cycle, code, and posture identifiers are required")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        for name, value in (
            ("candidate_count", candidate_count),
            ("specialist_context_count", specialist_context_count),
            ("decision_count", decision_count),
            ("alternative_count", alternative_count),
            ("institutional_provider_count", institutional_provider_count),
        ):
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be non-negative")

        candidate_state = (
            ShadowEngineState.OBSERVED
            if candidate_count
            else ShadowEngineState.AWAITING_GOVERNED_INPUT
        )
        context_state = (
            ShadowEngineState.OBSERVED
            if specialist_context_count
            else ShadowEngineState.AWAITING_GOVERNED_INPUT
        )
        decision_state = (
            ShadowEngineState.OBSERVED
            if decision_count
            else ShadowEngineState.AWAITING_GOVERNED_INPUT
        )
        records = (
            ShadowEngineRecord(
                AdvancedEngine.CAUSAL_REASONING,
                context_state,
                "Observed the governed posture and specialist evidence boundary; event assessments are processed only when supplied by the public-information pipeline.",
                (posture_identifier,),
            ),
            ShadowEngineRecord(
                AdvancedEngine.PRIMARY_SOURCE_DOCUMENTS,
                ShadowEngineState.AWAITING_GOVERNED_INPUT,
                "No document may be inferred from candidate data; the engine waits for licensed, timestamped primary-source documents.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.INVESTMENT_GRAPH,
                candidate_state,
                "Observed the governed candidate set without expanding ownership eligibility.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.VALUE_OF_INFORMATION,
                decision_state,
                "Observed unresolved decision assumptions when CIO decisions were available; research remains provider governed.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.ADVERSARIAL_CHALLENGE,
                decision_state,
                "Observed material CIO conclusions as a non-voting review service.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.FORECAST_LEDGER,
                context_state,
                "Observed forecast-capable specialist evidence; only explicit claims with fixed resolution rules enter the ledger.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.PORTFOLIO_DIGITAL_TWIN,
                ShadowEngineState.OBSERVED if alternative_count else ShadowEngineState.AWAITING_GOVERNED_INPUT,
                "Observed governed portfolio alternatives; simulation cannot add instruments or increase CIO-approved sizing.",
            ),
            ShadowEngineRecord(
                AdvancedEngine.STRUCTURAL_BREAKS,
                context_state,
                "Observed the posture evidence boundary; provider degradation remains separate from market novelty.",
                (posture_identifier,),
            ),
            ShadowEngineRecord(
                AdvancedEngine.CHAMPION_CHALLENGER,
                ShadowEngineState.OBSERVED,
                "Recorded the production model as champion; challengers remain shadow-only until explicit promotion approval.",
                (code_version,),
            ),
            ShadowEngineRecord(
                AdvancedEngine.INSTITUTIONAL_DATA,
                (
                    ShadowEngineState.OBSERVED
                    if institutional_provider_count
                    else ShadowEngineState.DISABLED_PENDING_CERTIFICATION
                ),
                "Commercial institutional datasets remain disabled unless every onboarding and certification gate passes.",
            ),
        )
        return AdvancedShadowSnapshot(
            cycle_identifier=cycle_identifier,
            as_of=as_of,
            code_version=code_version,
            records=records,
        )


class SQLiteAdvancedShadowStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS advanced_intelligence_shadow(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    cycle_identifier TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS advanced_shadow_no_update
                BEFORE UPDATE ON advanced_intelligence_shadow
                BEGIN SELECT RAISE(ABORT, 'advanced shadow history is append only'); END;
                CREATE TRIGGER IF NOT EXISTS advanced_shadow_no_delete
                BEFORE DELETE ON advanced_intelligence_shadow
                BEGIN SELECT RAISE(ABORT, 'advanced shadow history is append only'); END;
                """
            )

    @staticmethod
    def _hash(previous_hash: str | None, payload_json: str) -> str:
        return hashlib.sha256(((previous_hash or "") + "\n" + payload_json).encode()).hexdigest()

    def append(self, snapshot: AdvancedShadowSnapshot) -> str:
        payload_json = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(
                "SELECT payload_json,content_hash FROM advanced_intelligence_shadow WHERE cycle_identifier=?",
                (snapshot.cycle_identifier,),
            ).fetchone()
            if existing:
                if str(existing[0]) == payload_json:
                    return str(existing[1])
                raise ValueError("conflicting advanced-shadow cycle identifier")
            prior = connection.execute(
                "SELECT content_hash FROM advanced_intelligence_shadow ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(prior[0]) if prior else None
            content_hash = self._hash(previous_hash, payload_json)
            connection.execute(
                "INSERT INTO advanced_intelligence_shadow(cycle_identifier,payload_json,previous_hash,content_hash) VALUES(?,?,?,?)",
                (snapshot.cycle_identifier, payload_json, previous_hash, content_hash),
            )
        return content_hash

    def verify(self) -> None:
        previous_hash: str | None = None
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload_json,previous_hash,content_hash FROM advanced_intelligence_shadow ORDER BY sequence"
            ).fetchall()
        for payload_json, stored_previous, stored_hash in rows:
            if stored_previous != previous_hash:
                raise ValueError("advanced-shadow previous hash mismatch")
            expected = self._hash(previous_hash, str(payload_json))
            if stored_hash != expected:
                raise ValueError("advanced-shadow content hash mismatch")
            previous_hash = str(stored_hash)


__all__ = [
    "AdvancedEngine",
    "AdvancedIntelligenceShadowCoordinator",
    "AdvancedShadowSnapshot",
    "SQLiteAdvancedShadowStore",
    "ShadowEngineRecord",
    "ShadowEngineState",
]
