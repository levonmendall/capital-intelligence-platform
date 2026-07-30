"""Governed production assembly for the canonical CIO cycle.

This module turns persisted screening, portfolio, and point-in-time evidence
records into ``ProductionCanonicalCIOContext``.  It never discovers candidates,
substitutes candidate evidence, or falls back to legacy state.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from application.cio_cycle import (
    CandidateCycleContext,
    CandidateExposureProfile,
    CyclePortfolioState,
)
from application.production_cio import (
    ProductionCanonicalCIOContext,
    ProductionContextManifest,
)
from cio import CandidateAssetClass, EvidenceQuality
from committee.specialists import (
    AssetValuationSpecialistContext,
    CrossAssetForecastSpecialistContext,
    ForecastScenarioAssessment,
    MacroSpecialistContext,
    MarketSpecialistContext,
)
from company import (
    CompanyAnalysis,
    CompanyFactor,
    CompanyFactorAssessment,
    CompanyMarketSnapshot,
    CompanyRegimeContext,
    FinancialHistory,
    NormalizedAnnualFinancials,
)
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunitySetContext,
)
from portfolio.construction_api import PortfolioAsset
from portfolio.state import SQLiteCanonicalPortfolioStore
from screening import (
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
    candidate_from_payload,
)


class ProductionContextError(RuntimeError):
    """Raised when governed production context cannot be assembled."""


class EvidenceCertificationState(str, Enum):
    """Certification state accepted by the production context boundary."""

    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    EXPIRED = "expired"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _number(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    if maximum is not None and normalized > maximum:
        raise ValueError(f"{field_name} must be at most {maximum}")
    return round(normalized, 8)


def _texts(
    value: object,
    *,
    field_name: str,
    minimum: int = 0,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _pairs(
    value: object,
    *,
    field_name: str,
    bounded: bool = False,
) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized: list[tuple[str, float]] = []
    for raw_name, raw_value in value:
        name = _text(raw_name, field_name=f"{field_name} name")
        number = _number(
            raw_value,
            field_name=f"{field_name} value",
            minimum=-1.0 if bounded else None,
            maximum=1.0 if bounded else None,
        )
        normalized.append((name, number))
    if len(normalized) != len({name for name, _ in normalized}):
        raise ValueError(f"{field_name} names must be unique")
    return tuple(normalized)


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("production context payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class GovernedEvidenceLineage:
    """Certification, freshness, source, and model lineage for one evidence set."""

    certification_identifier: str
    certification_state: EvidenceCertificationState
    certification_expires_at: datetime
    fresh_until: datetime
    evidence_identifiers: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    model_versions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "certification_identifier",
            _text(
                self.certification_identifier,
                field_name="certification_identifier",
            ),
        )
        if not isinstance(self.certification_state, EvidenceCertificationState):
            raise TypeError(
                "certification_state must be an EvidenceCertificationState"
            )
        _aware(
            self.certification_expires_at,
            field_name="certification_expires_at",
        )
        _aware(self.fresh_until, field_name="fresh_until")
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(
                self.evidence_identifiers,
                field_name="evidence_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "source_versions",
            tuple(
                (
                    _text(name, field_name="source version name"),
                    _text(version, field_name="source version"),
                )
                for name, version in self.source_versions
            ),
        )
        object.__setattr__(
            self,
            "model_versions",
            tuple(
                (
                    _text(name, field_name="model version name"),
                    _text(version, field_name="model version"),
                )
                for name, version in self.model_versions
            ),
        )
        for field_name in ("source_versions", "model_versions"):
            values = getattr(self, field_name)
            names = tuple(name for name, _ in values)
            if len(names) != len(set(names)):
                raise ValueError(f"{field_name} names must be unique")

    def require_usable(self, *, knowledge_cutoff: datetime) -> None:
        cutoff = _aware(knowledge_cutoff, field_name="knowledge_cutoff")
        if self.certification_state is not EvidenceCertificationState.APPROVED:
            raise ProductionContextError(
                f"evidence certification {self.certification_identifier} "
                f"is {self.certification_state.value}, not approved"
            )
        if self.certification_expires_at < cutoff:
            raise ProductionContextError(
                f"evidence certification {self.certification_identifier} is expired"
            )
        if self.fresh_until < cutoff:
            raise ProductionContextError(
                f"evidence governed by {self.certification_identifier} is stale"
            )


@dataclass(frozen=True, slots=True)
class ProductionCandidateEvidence:
    """Governed specialist and exposure evidence for one screened candidate."""

    identifier: str
    candidate_identifier: str
    symbol: str
    as_of: datetime
    knowledge_cutoff: datetime
    analysis_completed_at: datetime
    macro: MacroSpecialistContext
    market: MarketSpecialistContext
    company: CompanyAnalysis | None
    exposure_profile: CandidateExposureProfile
    fundamental_evidence_identifiers: tuple[str, ...]
    fundamental_model_version: str
    lineage: GovernedEvidenceLineage
    forecast: CrossAssetForecastSpecialistContext | None = None
    asset_valuation: AssetValuationSpecialistContext | None = None

    def __post_init__(self) -> None:
        for field_name in ("identifier", "candidate_identifier"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        for field_name in ("as_of", "knowledge_cutoff", "analysis_completed_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        if not self.as_of <= self.analysis_completed_at <= self.knowledge_cutoff:
            raise ValueError(
                "analysis_completed_at must be inside the point-in-time boundary"
            )
        if not isinstance(self.macro, MacroSpecialistContext):
            raise TypeError("macro must be MacroSpecialistContext")
        if not isinstance(self.market, MarketSpecialistContext):
            raise TypeError("market must be MarketSpecialistContext")
        if self.macro.as_of != self.as_of or self.market.as_of != self.as_of:
            raise ValueError("macro and market evidence must share candidate as_of")
        if self.company is not None:
            if not isinstance(self.company, CompanyAnalysis):
                raise TypeError("company must be CompanyAnalysis or None")
            if self.company.as_of != self.as_of:
                raise ValueError("company evidence must share candidate as_of")
            if self.company.symbol != self.symbol:
                raise ValueError("company evidence symbol does not match candidate")
        if not isinstance(self.exposure_profile, CandidateExposureProfile):
            raise TypeError(
                "exposure_profile must be CandidateExposureProfile"
            )
        if (
            self.exposure_profile.candidate_identifier
            != self.candidate_identifier
        ):
            raise ValueError("exposure profile does not match candidate")
        object.__setattr__(
            self,
            "fundamental_evidence_identifiers",
            _texts(
                self.fundamental_evidence_identifiers,
                field_name="fundamental_evidence_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "fundamental_model_version",
            _text(
                self.fundamental_model_version,
                field_name="fundamental_model_version",
            ),
        )
        if not isinstance(self.lineage, GovernedEvidenceLineage):
            raise TypeError("lineage must be GovernedEvidenceLineage")
        self.lineage.require_usable(knowledge_cutoff=self.knowledge_cutoff)
        if self.forecast is not None:
            if not isinstance(self.forecast, CrossAssetForecastSpecialistContext):
                raise TypeError(
                    "forecast must be CrossAssetForecastSpecialistContext or None"
                )
            if self.forecast.as_of != self.as_of:
                raise ValueError("forecast evidence must share candidate as_of")
        if self.asset_valuation is not None:
            if not isinstance(self.asset_valuation, AssetValuationSpecialistContext):
                raise TypeError(
                    "asset_valuation must be AssetValuationSpecialistContext or None"
                )
            if self.asset_valuation.as_of != self.as_of:
                raise ValueError("asset valuation evidence must share candidate as_of")


@dataclass(frozen=True, slots=True)
class ProductionHoldingEvidence:
    """Governed expected-return, cost, and exposure evidence for a current holding."""

    identifier: str
    symbol: str
    as_of: datetime
    knowledge_cutoff: datetime
    expected_return: float
    evidence_quality: float
    liquidity_score: float
    sector: str
    factor_loadings: tuple[tuple[str, float], ...]
    correlation_bucket: str
    average_daily_dollar_volume: float
    transaction_cost_bps: float
    slippage_bps: float
    minimum_weight: float
    funding_eligible: bool
    lineage: GovernedEvidenceLineage

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _text(self.identifier, field_name="identifier"),
        )
        object.__setattr__(
            self,
            "symbol",
            _text(self.symbol, field_name="symbol").upper(),
        )
        for field_name in ("as_of", "knowledge_cutoff"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        object.__setattr__(
            self,
            "expected_return",
            _number(self.expected_return, field_name="expected_return"),
        )
        for field_name in ("evidence_quality", "liquidity_score", "minimum_weight"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        object.__setattr__(
            self,
            "sector",
            _text(self.sector, field_name="sector"),
        )
        object.__setattr__(
            self,
            "factor_loadings",
            _pairs(
                self.factor_loadings,
                field_name="factor_loadings",
                bounded=True,
            ),
        )
        object.__setattr__(
            self,
            "correlation_bucket",
            _text(
                self.correlation_bucket,
                field_name="correlation_bucket",
            ),
        )
        object.__setattr__(
            self,
            "average_daily_dollar_volume",
            _number(
                self.average_daily_dollar_volume,
                field_name="average_daily_dollar_volume",
                minimum=0.0,
            ),
        )
        for field_name in ("transaction_cost_bps", "slippage_bps"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                ),
            )
        if not isinstance(self.funding_eligible, bool):
            raise TypeError("funding_eligible must be a bool")
        if not isinstance(self.lineage, GovernedEvidenceLineage):
            raise TypeError("lineage must be GovernedEvidenceLineage")
        self.lineage.require_usable(knowledge_cutoff=self.knowledge_cutoff)

    @property
    def implementation_cost_return(self) -> float:
        return round(
            (self.transaction_cost_bps + self.slippage_bps) / 10_000,
            8,
        )


@dataclass(frozen=True, slots=True)
class ProductionContextEvidenceSnapshot:
    """Complete persisted evidence inputs for one production decision timestamp."""

    identifier: str
    screening_cycle_identifier: str
    portfolio_code: str
    as_of: datetime
    knowledge_cutoff: datetime
    cash_expected_return: float
    cash_evidence_quality: float
    cash_liquidity_score: float
    cash_lineage: GovernedEvidenceLineage
    candidate_evidence: tuple[ProductionCandidateEvidence, ...]
    holding_evidence: tuple[ProductionHoldingEvidence, ...]
    schema_version: str = "production-context-evidence.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "screening_cycle_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "portfolio_code",
            _text(self.portfolio_code, field_name="portfolio_code").upper(),
        )
        for field_name in ("as_of", "knowledge_cutoff"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        object.__setattr__(
            self,
            "cash_expected_return",
            _number(
                self.cash_expected_return,
                field_name="cash_expected_return",
            ),
        )
        for field_name in ("cash_evidence_quality", "cash_liquidity_score"):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        if not isinstance(self.cash_lineage, GovernedEvidenceLineage):
            raise TypeError("cash_lineage must be GovernedEvidenceLineage")
        self.cash_lineage.require_usable(
            knowledge_cutoff=self.knowledge_cutoff
        )
        if not isinstance(self.candidate_evidence, tuple) or not all(
            isinstance(item, ProductionCandidateEvidence)
            for item in self.candidate_evidence
        ):
            raise TypeError(
                "candidate_evidence must contain ProductionCandidateEvidence"
            )
        if not isinstance(self.holding_evidence, tuple) or not all(
            isinstance(item, ProductionHoldingEvidence)
            for item in self.holding_evidence
        ):
            raise TypeError(
                "holding_evidence must contain ProductionHoldingEvidence"
            )
        for item in (*self.candidate_evidence, *self.holding_evidence):
            if item.as_of != self.as_of:
                raise ValueError("all production evidence must share as_of")
            if item.knowledge_cutoff != self.knowledge_cutoff:
                raise ValueError(
                    "all production evidence must share knowledge_cutoff"
                )
        candidate_ids = tuple(
            item.candidate_identifier for item in self.candidate_evidence
        )
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate evidence identifiers must be unique")
        candidate_symbols = tuple(item.symbol for item in self.candidate_evidence)
        if len(candidate_symbols) != len(set(candidate_symbols)):
            raise ValueError("candidate evidence symbols must be unique")
        holding_symbols = tuple(item.symbol for item in self.holding_evidence)
        if len(holding_symbols) != len(set(holding_symbols)):
            raise ValueError("holding evidence symbols must be unique")


class SQLiteProductionContextStore:
    """Append-only authority for certified point-in-time production context."""

    _TABLE = "production_context_evidence_events"
    _GENESIS_HASH = "0" * 64

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
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    screening_cycle_identifier TEXT NOT NULL,
                    portfolio_code TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    knowledge_cutoff TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS production_context_as_of
                ON {self._TABLE} (portfolio_code, as_of, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'production context history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'production context history is append-only');
                END;
                """
            )

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        screening_cycle_identifier: str,
        portfolio_code: str,
        as_of: str,
        knowledge_cutoff: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                screening_cycle_identifier,
                portfolio_code,
                as_of,
                knowledge_cutoff,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, snapshot: ProductionContextEvidenceSnapshot) -> int:
        if not isinstance(snapshot, ProductionContextEvidenceSnapshot):
            raise TypeError(
                "snapshot must be ProductionContextEvidenceSnapshot"
            )
        self.verify_integrity()
        payload_json = _canonical_json(_snapshot_to_dict(snapshot))
        as_of = snapshot.as_of.isoformat()
        knowledge_cutoff = snapshot.knowledge_cutoff.isoformat()
        with self._connect() as connection:
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (snapshot.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ValueError(
                        "production context identifier already exists "
                        "with different content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous_hash = (
                self._GENESIS_HASH
                if tail is None
                else str(tail["content_hash"])
            )
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=snapshot.identifier,
                screening_cycle_identifier=snapshot.screening_cycle_identifier,
                portfolio_code=snapshot.portfolio_code,
                as_of=as_of,
                knowledge_cutoff=knowledge_cutoff,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, screening_cycle_identifier,
                    portfolio_code, as_of, knowledge_cutoff, payload_json,
                    previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    snapshot.identifier,
                    snapshot.screening_cycle_identifier,
                    snapshot.portfolio_code,
                    as_of,
                    knowledge_cutoff,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def snapshot_for_as_of(
        self,
        *,
        portfolio_code: str,
        as_of: datetime,
    ) -> ProductionContextEvidenceSnapshot | None:
        normalized_code = _text(
            portfolio_code,
            field_name="portfolio_code",
        ).upper()
        timestamp = _aware(as_of, field_name="as_of").isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE portfolio_code = ? AND as_of = ? ORDER BY sequence",
                (normalized_code, timestamp),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ProductionContextError(
                "multiple production context snapshots exist for one portfolio "
                "and decision timestamp"
            )
        return _snapshot_from_dict(json.loads(str(rows[0]["payload_json"])))

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected_sequence, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected_sequence:
                raise ProductionContextError(
                    "production context event sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise ProductionContextError(
                    "production context previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected_sequence,
                event_identifier=str(row["event_identifier"]),
                screening_cycle_identifier=str(
                    row["screening_cycle_identifier"]
                ),
                portfolio_code=str(row["portfolio_code"]),
                as_of=str(row["as_of"]),
                knowledge_cutoff=str(row["knowledge_cutoff"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise ProductionContextError(
                    "production context content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class RepositoryProductionCanonicalCIOContextProvider:
    """Assemble one canonical context exclusively from persisted authorities."""

    name = "REPOSITORY_PRODUCTION_CONTEXT"

    def __init__(
        self,
        *,
        screening_store: SQLiteFullUniverseScreeningStore,
        portfolio_store: SQLiteCanonicalPortfolioStore,
        context_store: SQLiteProductionContextStore,
        portfolio_code: str = "COMPOUNDING",
        code_version: str | None = None,
    ) -> None:
        if not isinstance(
            screening_store,
            SQLiteFullUniverseScreeningStore,
        ):
            raise TypeError(
                "screening_store must be SQLiteFullUniverseScreeningStore"
            )
        if not isinstance(portfolio_store, SQLiteCanonicalPortfolioStore):
            raise TypeError(
                "portfolio_store must be SQLiteCanonicalPortfolioStore"
            )
        if not isinstance(context_store, SQLiteProductionContextStore):
            raise TypeError(
                "context_store must be SQLiteProductionContextStore"
            )
        self.screening_store = screening_store
        self.portfolio_store = portfolio_store
        self.context_store = context_store
        self.portfolio_code = _text(
            portfolio_code,
            field_name="portfolio_code",
        ).upper()
        self.code_version = _text(
            code_version
            or os.getenv("CAPITAL_INTELLIGENCE_CODE_VERSION")
            or os.getenv("GITHUB_SHA")
            or "unknown",
            field_name="code_version",
        )

    def load_context(
        self,
        *,
        as_of: datetime,
    ) -> ProductionCanonicalCIOContext:
        decision_time = _aware(as_of, field_name="as_of")
        self.screening_store.verify_integrity()
        self.portfolio_store.verify_integrity()
        self.context_store.verify_integrity()

        evidence = self.context_store.snapshot_for_as_of(
            portfolio_code=self.portfolio_code,
            as_of=decision_time,
        )
        if evidence is None:
            raise ProductionContextError(
                "certified production context evidence is unavailable "
                "for the decision timestamp"
            )
        publication = self.screening_store.publication(
            evidence.screening_cycle_identifier
        )
        if publication is None:
            raise ProductionContextError(
                "production context requires a persisted screening publication"
            )
        cycle_events = self.screening_store.events(
            evidence.screening_cycle_identifier,
            event_type=ScreeningEventType.CYCLE_STARTED,
        )
        if len(cycle_events) != 1:
            raise ProductionContextError(
                "screening cycle must contain exactly one start boundary"
            )
        cycle_boundary = cycle_events[0].payload
        screening_as_of = datetime.fromisoformat(str(cycle_boundary["as_of"]))
        screening_cutoff = datetime.fromisoformat(
            str(cycle_boundary["knowledge_cutoff"])
        )
        if screening_as_of != decision_time or evidence.as_of != decision_time:
            raise ProductionContextError(
                "screening, evidence, and decision timestamps do not match"
            )
        if screening_cutoff != evidence.knowledge_cutoff:
            raise ProductionContextError(
                "screening and production evidence knowledge cutoffs do not match"
            )
        if publication.published_at > evidence.knowledge_cutoff:
            raise ProductionContextError(
                "screening publication was not available by the knowledge cutoff"
            )
        if publication.screened_instrument_count != publication.eligible_instrument_count:
            raise ProductionContextError(
                "production context cannot consume incomplete screening coverage"
            )

        candidates = tuple(
            candidate_from_payload(payload)
            for payload in publication.candidate_payloads
        )
        candidate_map = {item.identifier: item for item in candidates}
        if len(candidate_map) != len(candidates):
            raise ProductionContextError(
                "screening publication contains duplicate candidate identifiers"
            )
        if any(item.as_of != decision_time for item in candidates):
            raise ProductionContextError(
                "screened candidates do not share the decision timestamp"
            )
        ranked_payloads = tuple(
            dict(item)
            for item in publication.opportunity_queue_payload.get("ranked", ())
        )
        qualified_ids = tuple(
            _text(
                item.get("candidate_identifier"),
                field_name="qualified candidate identifier",
            )
            for item in ranked_payloads
        )
        if len(qualified_ids) != len(set(qualified_ids)):
            raise ProductionContextError(
                "screening publication contains duplicate qualified candidates"
            )
        if not set(qualified_ids).issubset(candidate_map):
            raise ProductionContextError(
                "screening opportunity queue references unknown candidates"
            )

        candidate_evidence = {
            item.candidate_identifier: item for item in evidence.candidate_evidence
        }
        if set(candidate_evidence) != set(qualified_ids):
            missing = sorted(set(qualified_ids) - set(candidate_evidence))
            extra = sorted(set(candidate_evidence) - set(qualified_ids))
            raise ProductionContextError(
                "candidate context coverage must exactly match qualified "
                f"screening candidates: missing={missing} extra={extra}"
            )
        for candidate_identifier in qualified_ids:
            candidate = candidate_map[candidate_identifier]
            governed = candidate_evidence[candidate_identifier]
            if governed.symbol != candidate.instrument.symbol:
                raise ProductionContextError(
                    f"candidate context symbol does not match {candidate_identifier}"
                )
            if (
                candidate.instrument.asset_class is CandidateAssetClass.US_EQUITY
                and governed.company is None
            ):
                raise ProductionContextError(
                    f"equity candidate {candidate_identifier} is missing governed "
                    "fundamental and valuation analysis"
                )
            if governed.company is None and governed.asset_valuation is None:
                raise ProductionContextError(
                    f"candidate {candidate_identifier} is missing independent valuation evidence"
                )
            if governed.forecast is None:
                raise ProductionContextError(
                    f"candidate {candidate_identifier} is missing governed forecast translation"
                )

        portfolio_snapshot = self._portfolio_snapshot(decision_time)
        holding_context = {
            item.symbol: item for item in evidence.holding_evidence
        }
        portfolio_symbols = {
            item.symbol for item in portfolio_snapshot.positions
        }
        if set(holding_context) != portfolio_symbols:
            missing = sorted(portfolio_symbols - set(holding_context))
            extra = sorted(set(holding_context) - portfolio_symbols)
            raise ProductionContextError(
                "holding context coverage must exactly match canonical holdings: "
                f"missing={missing} extra={extra}"
            )
        if portfolio_snapshot.nav <= 0.0:
            raise ProductionContextError(
                "canonical portfolio NAV must be positive"
            )
        cash_weight = round(
            portfolio_snapshot.cash_amount / portfolio_snapshot.nav,
            8,
        )
        if cash_weight <= 0.0:
            raise ProductionContextError(
                "canonical portfolio must retain a positive cash alternative"
            )

        positions = tuple(
            self._portfolio_asset(
                position=position,
                portfolio_value=portfolio_snapshot.nav,
                evidence=holding_context[position.symbol],
            )
            for position in portfolio_snapshot.positions
        )
        specialist_contexts = tuple(
            CandidateCycleContext(
                candidate_identifier=candidate_identifier,
                analysis_completed_at=(
                    candidate_evidence[candidate_identifier].analysis_completed_at
                ),
                macro=candidate_evidence[candidate_identifier].macro,
                market=candidate_evidence[candidate_identifier].market,
                forecast=candidate_evidence[candidate_identifier].forecast,
                company=candidate_evidence[candidate_identifier].company,
                asset_valuation=(
                    candidate_evidence[candidate_identifier].asset_valuation
                ),
            )
            for candidate_identifier in qualified_ids
        )
        exposure_profiles = tuple(
            candidate_evidence[candidate_identifier].exposure_profile
            for candidate_identifier in qualified_ids
        )
        portfolio = CyclePortfolioState(
            identifier=f"cycle-portfolio:{portfolio_snapshot.identifier}",
            as_of=decision_time,
            portfolio_value=portfolio_snapshot.nav,
            cash_weight=cash_weight,
            cash_expected_return=evidence.cash_expected_return,
            positions=positions,
            exposure_profiles=exposure_profiles,
        )
        alternatives: list[AlternativeUse] = [
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=evidence.cash_expected_return,
                implementation_cost_return=0.0,
                evidence_quality=evidence.cash_evidence_quality,
                liquidity_score=evidence.cash_liquidity_score,
                current_weight=cash_weight,
            )
        ]
        alternatives.extend(
            AlternativeUse(
                identifier=f"holding:{position.symbol}",
                kind=AlternativeKind.CURRENT_HOLDING,
                expected_return=holding_context[position.symbol].expected_return,
                implementation_cost_return=(
                    holding_context[position.symbol].implementation_cost_return
                ),
                evidence_quality=holding_context[
                    position.symbol
                ].evidence_quality,
                liquidity_score=holding_context[position.symbol].liquidity_score,
                current_weight=round(
                    position.market_value / portfolio_snapshot.nav,
                    8,
                ),
            )
            for position in portfolio_snapshot.positions
        )
        alternatives.extend(
            AlternativeUse(
                identifier=candidate_identifier,
                kind=AlternativeKind.QUALIFIED_CANDIDATE,
                expected_return=(
                    candidate_map[
                        candidate_identifier
                    ].probability_weighted_expected_return
                ),
                implementation_cost_return=(
                    candidate_map[candidate_identifier].implementation_cost_return
                ),
                evidence_quality=(
                    candidate_map[candidate_identifier].evidence_quality.score
                ),
                liquidity_score=(
                    candidate_map[candidate_identifier].liquidity_score
                ),
                current_weight=0.0,
            )
            for candidate_identifier in qualified_ids
        )
        opportunity_context = OpportunitySetContext(
            identifier=publication.opportunity_context_identifier,
            as_of=decision_time,
            alternatives=tuple(alternatives),
        )
        manifest = self._manifest(
            evidence=evidence,
            publication_identifier=publication.identifier,
            portfolio_snapshot_identifier=portfolio_snapshot.identifier,
            qualified_ids=qualified_ids,
        )
        return ProductionCanonicalCIOContext(
            identifier=f"canonical-cycle:{evidence.screening_cycle_identifier}",
            screening_cycle_identifier=evidence.screening_cycle_identifier,
            opportunity_context=opportunity_context,
            specialist_contexts=specialist_contexts,
            portfolio=portfolio,
            code_version=self.code_version,
            manifest=manifest,
        )

    def _portfolio_snapshot(self, as_of: datetime):
        snapshots = self.portfolio_store.history(
            self.portfolio_code,
            limit=10_000,
        )
        matches = tuple(item for item in snapshots if item.as_of == as_of)
        if not matches:
            raise ProductionContextError(
                "canonical portfolio snapshot is unavailable at the exact "
                "decision timestamp"
            )
        if len(matches) != 1:
            raise ProductionContextError(
                "multiple canonical portfolio snapshots exist at the decision "
                "timestamp"
            )
        return matches[0]

    @staticmethod
    def _portfolio_asset(*, position, portfolio_value: float, evidence):
        weight = round(position.market_value / portfolio_value, 8)
        if evidence.minimum_weight > weight:
            raise ProductionContextError(
                f"holding minimum weight exceeds current weight for {position.symbol}"
            )
        return PortfolioAsset(
            symbol=position.symbol,
            instrument_identifier=position.instrument_identifier,
            current_weight=weight,
            expected_return=evidence.expected_return,
            sector=evidence.sector,
            factor_loadings=evidence.factor_loadings,
            correlation_bucket=evidence.correlation_bucket,
            average_daily_dollar_volume=evidence.average_daily_dollar_volume,
            transaction_cost_bps=evidence.transaction_cost_bps,
            slippage_bps=evidence.slippage_bps,
            minimum_weight=evidence.minimum_weight,
            funding_eligible=evidence.funding_eligible,
        )

    @staticmethod
    def _manifest(
        *,
        evidence: ProductionContextEvidenceSnapshot,
        publication_identifier: str,
        portfolio_snapshot_identifier: str,
        qualified_ids: tuple[str, ...],
    ) -> ProductionContextManifest:
        lineages = [evidence.cash_lineage]
        lineages.extend(item.lineage for item in evidence.candidate_evidence)
        lineages.extend(item.lineage for item in evidence.holding_evidence)
        evidence_identifiers = tuple(
            dict.fromkeys(
                identifier
                for lineage in lineages
                for identifier in lineage.evidence_identifiers
            )
        )
        source_versions = tuple(
            sorted(
                {
                    pair
                    for lineage in lineages
                    for pair in lineage.source_versions
                }
            )
        )
        model_versions = tuple(
            sorted(
                {
                    pair
                    for lineage in lineages
                    for pair in lineage.model_versions
                }
                | {
                    (
                        "fundamental",
                        item.fundamental_model_version,
                    )
                    for item in evidence.candidate_evidence
                }
            )
        )
        candidate_context_identifiers = tuple(
            item.identifier
            for item in evidence.candidate_evidence
            if item.candidate_identifier in set(qualified_ids)
        )
        return ProductionContextManifest(
            identifier=f"manifest:{evidence.identifier}",
            screening_publication_identifier=publication_identifier,
            portfolio_snapshot_identifier=portfolio_snapshot_identifier,
            context_evidence_identifier=evidence.identifier,
            as_of=evidence.as_of,
            knowledge_cutoff=evidence.knowledge_cutoff,
            candidate_identifiers=qualified_ids,
            candidate_context_identifiers=candidate_context_identifiers,
            evidence_identifiers=evidence_identifiers,
            source_versions=source_versions,
            model_versions=model_versions,
        )


def build_production_context_provider(
    *,
    screening_database: str | Path | None = None,
    portfolio_database: str | Path | None = None,
    context_database: str | Path | None = None,
    portfolio_code: str | None = None,
    code_version: str | None = None,
) -> RepositoryProductionCanonicalCIOContextProvider:
    """Build the repository-owned provider from explicit paths or environment."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return RepositoryProductionCanonicalCIOContextProvider(
        screening_store=SQLiteFullUniverseScreeningStore(
            screening_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_FULL_UNIVERSE_SCREENING_DATABASE"
            )
            or data_dir / "full_universe_screening.db"
        ),
        portfolio_store=SQLiteCanonicalPortfolioStore(
            portfolio_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_DATABASE"
            )
            or data_dir / "canonical_portfolio.db"
        ),
        context_store=SQLiteProductionContextStore(
            context_database
            or os.getenv(
                "CAPITAL_INTELLIGENCE_PRODUCTION_CONTEXT_DATABASE"
            )
            or data_dir / "production_context.db"
        ),
        portfolio_code=portfolio_code
        or os.getenv("CAPITAL_INTELLIGENCE_CANONICAL_PORTFOLIO_CODE")
        or "COMPOUNDING",
        code_version=code_version,
    )


def _lineage_to_dict(value: GovernedEvidenceLineage) -> dict[str, Any]:
    return {
        "certification_identifier": value.certification_identifier,
        "certification_state": value.certification_state.value,
        "certification_expires_at": value.certification_expires_at.isoformat(),
        "fresh_until": value.fresh_until.isoformat(),
        "evidence_identifiers": list(value.evidence_identifiers),
        "source_versions": [list(item) for item in value.source_versions],
        "model_versions": [list(item) for item in value.model_versions],
    }


def _lineage_from_dict(payload: Mapping[str, Any]) -> GovernedEvidenceLineage:
    return GovernedEvidenceLineage(
        certification_identifier=str(payload["certification_identifier"]),
        certification_state=EvidenceCertificationState(
            str(payload["certification_state"])
        ),
        certification_expires_at=datetime.fromisoformat(
            str(payload["certification_expires_at"])
        ),
        fresh_until=datetime.fromisoformat(str(payload["fresh_until"])),
        evidence_identifiers=tuple(
            str(item) for item in payload["evidence_identifiers"]
        ),
        source_versions=tuple(
            (str(item[0]), str(item[1]))
            for item in payload.get("source_versions", ())
        ),
        model_versions=tuple(
            (str(item[0]), str(item[1]))
            for item in payload.get("model_versions", ())
        ),
    )


def _macro_to_dict(value: MacroSpecialistContext) -> dict[str, Any]:
    return {
        "as_of": value.as_of.isoformat(),
        "regime": value.regime,
        "expected_return_impact": value.expected_return_impact,
        "confidence": value.confidence,
        "tailwinds": list(value.tailwinds),
        "headwinds": list(value.headwinds),
        "systemic_risks": list(value.systemic_risks),
        "scenarios": list(value.scenarios),
        "evidence_identifiers": list(value.evidence_identifiers),
    }


def _macro_from_dict(payload: Mapping[str, Any]) -> MacroSpecialistContext:
    return MacroSpecialistContext(
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        regime=str(payload["regime"]),
        expected_return_impact=float(payload["expected_return_impact"]),
        confidence=float(payload["confidence"]),
        tailwinds=tuple(str(item) for item in payload.get("tailwinds", ())),
        headwinds=tuple(str(item) for item in payload.get("headwinds", ())),
        systemic_risks=tuple(
            str(item) for item in payload["systemic_risks"]
        ),
        scenarios=tuple(str(item) for item in payload["scenarios"]),
        evidence_identifiers=tuple(
            str(item) for item in payload["evidence_identifiers"]
        ),
    )


def _market_to_dict(value: MarketSpecialistContext) -> dict[str, Any]:
    return {
        "as_of": value.as_of.isoformat(),
        "market_regime": value.market_regime,
        "expected_return_impact": value.expected_return_impact,
        "confidence": value.confidence,
        "trend": value.trend,
        "momentum": value.momentum,
        "breadth": value.breadth,
        "liquidity": value.liquidity,
        "positioning": value.positioning,
        "evidence": list(value.evidence),
        "risks": list(value.risks),
        "entry_conditions": list(value.entry_conditions),
    }


def _market_from_dict(payload: Mapping[str, Any]) -> MarketSpecialistContext:
    return MarketSpecialistContext(
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        market_regime=str(payload["market_regime"]),
        expected_return_impact=float(payload["expected_return_impact"]),
        confidence=float(payload["confidence"]),
        trend=float(payload["trend"]),
        momentum=float(payload["momentum"]),
        breadth=float(payload["breadth"]),
        liquidity=float(payload["liquidity"]),
        positioning=float(payload["positioning"]),
        evidence=tuple(str(item) for item in payload["evidence"]),
        risks=tuple(str(item) for item in payload["risks"]),
        entry_conditions=tuple(
            str(item) for item in payload["entry_conditions"]
        ),
    )



def _forecast_to_dict(
    value: CrossAssetForecastSpecialistContext,
) -> dict[str, Any]:
    return {
        "as_of": value.as_of.isoformat(),
        "forecast_horizon_days": value.forecast_horizon_days,
        "scenarios": [
            {
                "label": item.label,
                "probability": item.probability,
                "candidate_return_impact": item.candidate_return_impact,
                "expected_path_drawdown": item.expected_path_drawdown,
                "rationale": item.rationale,
                "evidence_identifiers": list(item.evidence_identifiers),
            }
            for item in value.scenarios
        ],
        "aggregate_confidence": value.aggregate_confidence,
        "calibration_score": value.calibration_score,
        "model_agreement": value.model_agreement,
        "forecast_stability": value.forecast_stability,
        "path_drawdown_probability": value.path_drawdown_probability,
        "cross_asset_signals": list(value.cross_asset_signals),
        "contradictory_evidence": list(value.contradictory_evidence),
        "limitations": list(value.limitations),
        "change_conditions": list(value.change_conditions),
        "model_versions": list(value.model_versions),
        "evidence_identifiers": list(value.evidence_identifiers),
        "evidence_dependencies": [
            {
                "identifier": item.identifier,
                "parent_identifiers": list(item.parent_identifiers),
            }
            for item in value.evidence_dependencies
        ],
    }


def _forecast_from_dict(
    payload: Mapping[str, Any],
) -> CrossAssetForecastSpecialistContext:
    from cio import EvidenceDependency

    return CrossAssetForecastSpecialistContext(
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        forecast_horizon_days=int(payload["forecast_horizon_days"]),
        scenarios=tuple(
            ForecastScenarioAssessment(
                label=str(item["label"]),
                probability=float(item["probability"]),
                candidate_return_impact=float(item["candidate_return_impact"]),
                expected_path_drawdown=float(item["expected_path_drawdown"]),
                rationale=str(item["rationale"]),
                evidence_identifiers=tuple(
                    str(value) for value in item["evidence_identifiers"]
                ),
            )
            for item in payload["scenarios"]
        ),
        aggregate_confidence=float(payload["aggregate_confidence"]),
        calibration_score=float(payload["calibration_score"]),
        model_agreement=float(payload["model_agreement"]),
        forecast_stability=float(payload["forecast_stability"]),
        path_drawdown_probability=float(payload["path_drawdown_probability"]),
        cross_asset_signals=tuple(
            str(item) for item in payload["cross_asset_signals"]
        ),
        contradictory_evidence=tuple(
            str(item) for item in payload.get("contradictory_evidence", ())
        ),
        limitations=tuple(str(item) for item in payload["limitations"]),
        change_conditions=tuple(
            str(item) for item in payload["change_conditions"]
        ),
        model_versions=tuple(str(item) for item in payload["model_versions"]),
        evidence_identifiers=tuple(
            str(item) for item in payload["evidence_identifiers"]
        ),
        evidence_dependencies=tuple(
            EvidenceDependency(
                identifier=str(item["identifier"]),
                parent_identifiers=tuple(
                    str(value) for value in item["parent_identifiers"]
                ),
            )
            for item in payload.get("evidence_dependencies", ())
        ),
    )


def _asset_valuation_to_dict(
    value: AssetValuationSpecialistContext,
) -> dict[str, Any]:
    return {
        "as_of": value.as_of.isoformat(),
        "asset_class": value.asset_class.value,
        "expected_return_impact": value.expected_return_impact,
        "confidence": value.confidence,
        "valuation_evidence": list(value.valuation_evidence),
        "contradictory_evidence": list(value.contradictory_evidence),
        "critical_assumptions": list(value.critical_assumptions),
        "risks": list(value.risks),
        "limitations": list(value.limitations),
        "change_conditions": list(value.change_conditions),
        "evidence_identifiers": list(value.evidence_identifiers),
    }


def _asset_valuation_from_dict(
    payload: Mapping[str, Any],
) -> AssetValuationSpecialistContext:
    return AssetValuationSpecialistContext(
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        asset_class=CandidateAssetClass(str(payload["asset_class"])),
        expected_return_impact=float(payload["expected_return_impact"]),
        confidence=float(payload["confidence"]),
        valuation_evidence=tuple(
            str(item) for item in payload["valuation_evidence"]
        ),
        contradictory_evidence=tuple(
            str(item) for item in payload.get("contradictory_evidence", ())
        ),
        critical_assumptions=tuple(
            str(item) for item in payload["critical_assumptions"]
        ),
        risks=tuple(str(item) for item in payload["risks"]),
        limitations=tuple(str(item) for item in payload["limitations"]),
        change_conditions=tuple(
            str(item) for item in payload["change_conditions"]
        ),
        evidence_identifiers=tuple(
            str(item) for item in payload["evidence_identifiers"]
        ),
    )


def _quality_to_dict(value: EvidenceQuality) -> dict[str, float]:
    return {
        "reliability": value.reliability,
        "freshness": value.freshness,
        "relevance": value.relevance,
        "independence": value.independence,
        "completeness": value.completeness,
        "point_in_time_integrity": value.point_in_time_integrity,
    }


def _quality_from_dict(payload: Mapping[str, Any]) -> EvidenceQuality:
    return EvidenceQuality(
        reliability=float(payload["reliability"]),
        freshness=float(payload["freshness"]),
        relevance=float(payload["relevance"]),
        independence=float(payload["independence"]),
        completeness=float(payload["completeness"]),
        point_in_time_integrity=float(payload["point_in_time_integrity"]),
    )


def _annual_to_dict(value: NormalizedAnnualFinancials) -> dict[str, Any]:
    return {
        field_name: (
            getattr(value, field_name).isoformat()
            if field_name in {"period_end", "available_at"}
            else list(getattr(value, field_name))
            if field_name in {"accession_numbers", "source_fact_identifiers"}
            else getattr(value, field_name)
        )
        for field_name in (
            "cik",
            "fiscal_year",
            "period_end",
            "available_at",
            "accession_numbers",
            "source_fact_identifiers",
            "revenue",
            "operating_income",
            "net_income",
            "operating_cash_flow",
            "capital_expenditures",
            "assets",
            "liabilities",
            "equity",
            "cash",
            "debt",
            "current_assets",
            "current_liabilities",
            "diluted_shares",
        )
    }


def _annual_from_dict(
    payload: Mapping[str, Any],
) -> NormalizedAnnualFinancials:
    return NormalizedAnnualFinancials(
        cik=str(payload["cik"]),
        fiscal_year=int(payload["fiscal_year"]),
        period_end=date.fromisoformat(str(payload["period_end"])),
        available_at=datetime.fromisoformat(str(payload["available_at"])),
        accession_numbers=tuple(
            str(item) for item in payload["accession_numbers"]
        ),
        source_fact_identifiers=tuple(
            str(item) for item in payload["source_fact_identifiers"]
        ),
        revenue=float(payload["revenue"]),
        operating_income=_optional_float(payload.get("operating_income")),
        net_income=_optional_float(payload.get("net_income")),
        operating_cash_flow=_optional_float(
            payload.get("operating_cash_flow")
        ),
        capital_expenditures=_optional_float(
            payload.get("capital_expenditures")
        ),
        assets=_optional_float(payload.get("assets")),
        liabilities=_optional_float(payload.get("liabilities")),
        equity=_optional_float(payload.get("equity")),
        cash=_optional_float(payload.get("cash")),
        debt=_optional_float(payload.get("debt")),
        current_assets=_optional_float(payload.get("current_assets")),
        current_liabilities=_optional_float(
            payload.get("current_liabilities")
        ),
        diluted_shares=_optional_float(payload.get("diluted_shares")),
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _company_to_dict(value: CompanyAnalysis) -> dict[str, Any]:
    return {
        "cik": value.cik,
        "symbol": value.symbol,
        "as_of": value.as_of.isoformat(),
        "history": {
            "cik": value.history.cik,
            "as_of": value.history.as_of.isoformat(),
            "periods": [_annual_to_dict(item) for item in value.history.periods],
            "normalization_version": value.history.normalization_version,
        },
        "market": {
            "as_of": value.market.as_of.isoformat(),
            "current_price": value.market.current_price,
            "market_cap": value.market.market_cap,
            "shares_outstanding": value.market.shares_outstanding,
            "dividend_per_share": value.market.dividend_per_share,
            "six_month_return": value.market.six_month_return,
            "twelve_month_return": value.market.twelve_month_return,
            "benchmark_twelve_month_return": (
                value.market.benchmark_twelve_month_return
            ),
            "annualized_volatility": value.market.annualized_volatility,
            "maximum_drawdown": value.market.maximum_drawdown,
            "moving_average_200": value.market.moving_average_200,
            "average_daily_dollar_volume": (
                value.market.average_daily_dollar_volume
            ),
            "data_age_hours": value.market.data_age_hours,
            "evidence_identifiers": list(
                value.market.evidence_identifiers
            ),
        },
        "regime": {
            "as_of": value.regime.as_of.isoformat(),
            "growth_support": value.regime.growth_support,
            "liquidity_support": value.regime.liquidity_support,
            "credit_support": value.regime.credit_support,
            "market_risk_support": value.regime.market_risk_support,
            "industry_cyclicality": value.regime.industry_cyclicality,
            "duration_sensitivity": value.regime.duration_sensitivity,
            "evidence_identifiers": list(
                value.regime.evidence_identifiers
            ),
        },
        "factors": [
            {
                "factor": item.factor.value,
                "score": item.score,
                "confidence": item.confidence,
                "evidence": list(item.evidence),
                "risks": list(item.risks),
                "metrics": [list(metric) for metric in item.metrics],
                "methodology_version": item.methodology_version,
            }
            for item in value.factors
        ],
        "evidence_quality": _quality_to_dict(value.evidence_quality),
        "analysis_version": value.analysis_version,
    }


def _company_from_dict(payload: Mapping[str, Any]) -> CompanyAnalysis:
    history_payload = dict(payload["history"])
    market_payload = dict(payload["market"])
    regime_payload = dict(payload["regime"])
    return CompanyAnalysis(
        cik=str(payload["cik"]),
        symbol=str(payload["symbol"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        history=FinancialHistory(
            cik=str(history_payload["cik"]),
            as_of=datetime.fromisoformat(str(history_payload["as_of"])),
            periods=tuple(
                _annual_from_dict(dict(item))
                for item in history_payload["periods"]
            ),
            normalization_version=str(
                history_payload["normalization_version"]
            ),
        ),
        market=CompanyMarketSnapshot(
            as_of=datetime.fromisoformat(str(market_payload["as_of"])),
            current_price=float(market_payload["current_price"]),
            market_cap=float(market_payload["market_cap"]),
            shares_outstanding=float(
                market_payload["shares_outstanding"]
            ),
            dividend_per_share=float(
                market_payload["dividend_per_share"]
            ),
            six_month_return=float(market_payload["six_month_return"]),
            twelve_month_return=float(
                market_payload["twelve_month_return"]
            ),
            benchmark_twelve_month_return=float(
                market_payload["benchmark_twelve_month_return"]
            ),
            annualized_volatility=float(
                market_payload["annualized_volatility"]
            ),
            maximum_drawdown=float(market_payload["maximum_drawdown"]),
            moving_average_200=float(
                market_payload["moving_average_200"]
            ),
            average_daily_dollar_volume=float(
                market_payload["average_daily_dollar_volume"]
            ),
            data_age_hours=float(market_payload["data_age_hours"]),
            evidence_identifiers=tuple(
                str(item)
                for item in market_payload["evidence_identifiers"]
            ),
        ),
        regime=CompanyRegimeContext(
            as_of=datetime.fromisoformat(str(regime_payload["as_of"])),
            growth_support=float(regime_payload["growth_support"]),
            liquidity_support=float(regime_payload["liquidity_support"]),
            credit_support=float(regime_payload["credit_support"]),
            market_risk_support=float(
                regime_payload["market_risk_support"]
            ),
            industry_cyclicality=float(
                regime_payload["industry_cyclicality"]
            ),
            duration_sensitivity=float(
                regime_payload["duration_sensitivity"]
            ),
            evidence_identifiers=tuple(
                str(item)
                for item in regime_payload["evidence_identifiers"]
            ),
        ),
        factors=tuple(
            CompanyFactorAssessment(
                factor=CompanyFactor(str(item["factor"])),
                score=float(item["score"]),
                confidence=float(item["confidence"]),
                evidence=tuple(str(value) for value in item["evidence"]),
                risks=tuple(str(value) for value in item["risks"]),
                metrics=tuple(
                    (str(metric[0]), float(metric[1]))
                    for metric in item["metrics"]
                ),
                methodology_version=str(item["methodology_version"]),
            )
            for item in payload["factors"]
        ),
        evidence_quality=_quality_from_dict(
            dict(payload["evidence_quality"])
        ),
        analysis_version=str(payload["analysis_version"]),
    )


def _profile_to_dict(value: CandidateExposureProfile) -> dict[str, Any]:
    return {
        "candidate_identifier": value.candidate_identifier,
        "sector": value.sector,
        "factor_loadings": [list(item) for item in value.factor_loadings],
        "correlation_bucket": value.correlation_bucket,
    }


def _profile_from_dict(
    payload: Mapping[str, Any],
) -> CandidateExposureProfile:
    return CandidateExposureProfile(
        candidate_identifier=str(payload["candidate_identifier"]),
        sector=str(payload["sector"]),
        factor_loadings=tuple(
            (str(item[0]), float(item[1]))
            for item in payload["factor_loadings"]
        ),
        correlation_bucket=str(payload["correlation_bucket"]),
    )


def _candidate_to_dict(
    value: ProductionCandidateEvidence,
) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "candidate_identifier": value.candidate_identifier,
        "symbol": value.symbol,
        "as_of": value.as_of.isoformat(),
        "knowledge_cutoff": value.knowledge_cutoff.isoformat(),
        "analysis_completed_at": value.analysis_completed_at.isoformat(),
        "macro": _macro_to_dict(value.macro),
        "market": _market_to_dict(value.market),
        "company": (
            None if value.company is None else _company_to_dict(value.company)
        ),
        "forecast": (
            None if value.forecast is None else _forecast_to_dict(value.forecast)
        ),
        "asset_valuation": (
            None
            if value.asset_valuation is None
            else _asset_valuation_to_dict(value.asset_valuation)
        ),
        "exposure_profile": _profile_to_dict(value.exposure_profile),
        "fundamental_evidence_identifiers": list(
            value.fundamental_evidence_identifiers
        ),
        "fundamental_model_version": value.fundamental_model_version,
        "lineage": _lineage_to_dict(value.lineage),
    }


def _candidate_from_dict(
    payload: Mapping[str, Any],
) -> ProductionCandidateEvidence:
    company_payload = payload.get("company")
    forecast_payload = payload.get("forecast")
    asset_valuation_payload = payload.get("asset_valuation")
    return ProductionCandidateEvidence(
        identifier=str(payload["identifier"]),
        candidate_identifier=str(payload["candidate_identifier"]),
        symbol=str(payload["symbol"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        knowledge_cutoff=datetime.fromisoformat(
            str(payload["knowledge_cutoff"])
        ),
        analysis_completed_at=datetime.fromisoformat(
            str(payload["analysis_completed_at"])
        ),
        macro=_macro_from_dict(dict(payload["macro"])),
        market=_market_from_dict(dict(payload["market"])),
        company=(
            None
            if company_payload is None
            else _company_from_dict(dict(company_payload))
        ),
        exposure_profile=_profile_from_dict(
            dict(payload["exposure_profile"])
        ),
        fundamental_evidence_identifiers=tuple(
            str(item)
            for item in payload["fundamental_evidence_identifiers"]
        ),
        fundamental_model_version=str(
            payload["fundamental_model_version"]
        ),
        lineage=_lineage_from_dict(dict(payload["lineage"])),
        forecast=(
            None
            if forecast_payload is None
            else _forecast_from_dict(dict(forecast_payload))
        ),
        asset_valuation=(
            None
            if asset_valuation_payload is None
            else _asset_valuation_from_dict(dict(asset_valuation_payload))
        ),
    )


def _holding_to_dict(value: ProductionHoldingEvidence) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "symbol": value.symbol,
        "as_of": value.as_of.isoformat(),
        "knowledge_cutoff": value.knowledge_cutoff.isoformat(),
        "expected_return": value.expected_return,
        "evidence_quality": value.evidence_quality,
        "liquidity_score": value.liquidity_score,
        "sector": value.sector,
        "factor_loadings": [list(item) for item in value.factor_loadings],
        "correlation_bucket": value.correlation_bucket,
        "average_daily_dollar_volume": value.average_daily_dollar_volume,
        "transaction_cost_bps": value.transaction_cost_bps,
        "slippage_bps": value.slippage_bps,
        "minimum_weight": value.minimum_weight,
        "funding_eligible": value.funding_eligible,
        "lineage": _lineage_to_dict(value.lineage),
    }


def _holding_from_dict(
    payload: Mapping[str, Any],
) -> ProductionHoldingEvidence:
    return ProductionHoldingEvidence(
        identifier=str(payload["identifier"]),
        symbol=str(payload["symbol"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        knowledge_cutoff=datetime.fromisoformat(
            str(payload["knowledge_cutoff"])
        ),
        expected_return=float(payload["expected_return"]),
        evidence_quality=float(payload["evidence_quality"]),
        liquidity_score=float(payload["liquidity_score"]),
        sector=str(payload["sector"]),
        factor_loadings=tuple(
            (str(item[0]), float(item[1]))
            for item in payload["factor_loadings"]
        ),
        correlation_bucket=str(payload["correlation_bucket"]),
        average_daily_dollar_volume=float(
            payload["average_daily_dollar_volume"]
        ),
        transaction_cost_bps=float(payload["transaction_cost_bps"]),
        slippage_bps=float(payload["slippage_bps"]),
        minimum_weight=float(payload["minimum_weight"]),
        funding_eligible=bool(payload["funding_eligible"]),
        lineage=_lineage_from_dict(dict(payload["lineage"])),
    )


def _snapshot_to_dict(
    value: ProductionContextEvidenceSnapshot,
) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "screening_cycle_identifier": value.screening_cycle_identifier,
        "portfolio_code": value.portfolio_code,
        "as_of": value.as_of.isoformat(),
        "knowledge_cutoff": value.knowledge_cutoff.isoformat(),
        "cash_expected_return": value.cash_expected_return,
        "cash_evidence_quality": value.cash_evidence_quality,
        "cash_liquidity_score": value.cash_liquidity_score,
        "cash_lineage": _lineage_to_dict(value.cash_lineage),
        "candidate_evidence": [
            _candidate_to_dict(item) for item in value.candidate_evidence
        ],
        "holding_evidence": [
            _holding_to_dict(item) for item in value.holding_evidence
        ],
        "schema_version": value.schema_version,
    }


def _snapshot_from_dict(
    payload: Mapping[str, Any],
) -> ProductionContextEvidenceSnapshot:
    return ProductionContextEvidenceSnapshot(
        identifier=str(payload["identifier"]),
        screening_cycle_identifier=str(
            payload["screening_cycle_identifier"]
        ),
        portfolio_code=str(payload["portfolio_code"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        knowledge_cutoff=datetime.fromisoformat(
            str(payload["knowledge_cutoff"])
        ),
        cash_expected_return=float(payload["cash_expected_return"]),
        cash_evidence_quality=float(payload["cash_evidence_quality"]),
        cash_liquidity_score=float(payload["cash_liquidity_score"]),
        cash_lineage=_lineage_from_dict(dict(payload["cash_lineage"])),
        candidate_evidence=tuple(
            _candidate_from_dict(dict(item))
            for item in payload.get("candidate_evidence", ())
        ),
        holding_evidence=tuple(
            _holding_from_dict(dict(item))
            for item in payload.get("holding_evidence", ())
        ),
        schema_version=str(payload.get(
            "schema_version",
            "production-context-evidence.v1",
        )),
    )


__all__ = [
    "EvidenceCertificationState",
    "GovernedEvidenceLineage",
    "ProductionCandidateEvidence",
    "ProductionContextError",
    "ProductionContextEvidenceSnapshot",
    "ProductionHoldingEvidence",
    "RepositoryProductionCanonicalCIOContextProvider",
    "SQLiteProductionContextStore",
    "build_production_context_provider",
]
