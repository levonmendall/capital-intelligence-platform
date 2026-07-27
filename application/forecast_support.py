"""Attach governed forecasts to canonical candidates without decision authority."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from application.production_context import ProductionContextError, _aware, _text
from application.production_context_adapter import (
    build_production_context_provider as _build_base_provider,
)
from application.production_context_contract import ProductionCanonicalCIOContext
from governance.forecast_evidence import (
    ForecastEvidenceError,
    GovernedForecastEvidence,
    SQLiteForecastEvidenceStore,
)


class ForecastSupportError(RuntimeError):
    """Raised when forecast support cannot be reconciled to canonical context."""


class ForecastSupportIntegrityError(ForecastSupportError):
    """Raised when the append-only forecast-reference chain is invalid."""


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _merge_versions(
    *groups: tuple[tuple[str, str], ...],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    merged: dict[str, str] = {}
    for group in groups:
        for name, version in group:
            resolved_name = _text(name, field_name=f"{field_name} name")
            resolved_version = _text(version, field_name=f"{field_name} version")
            existing = merged.get(resolved_name)
            if existing is not None and existing != resolved_version:
                raise ForecastSupportError(
                    f"{field_name} contains conflicting versions for {resolved_name}"
                )
            merged[resolved_name] = resolved_version
    return tuple(sorted(merged.items()))


@dataclass(frozen=True, slots=True)
class CandidateForecastSupport:
    """Immutable supporting-evidence references for one screened candidate."""

    identifier: str
    screening_cycle_identifier: str
    candidate_identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    forecast_identifiers: tuple[str, ...]
    rationale: str
    limitations: tuple[str, ...]
    supporting_only: bool = True
    schema_version: str = "candidate-forecast-support.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "screening_cycle_identifier",
            "candidate_identifier",
            "rationale",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.as_of, field_name="as_of")
        _aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.knowledge_cutoff > self.as_of:
            raise ValueError("forecast-support cutoff cannot follow decision as_of")
        object.__setattr__(
            self,
            "forecast_identifiers",
            _texts(
                self.forecast_identifiers,
                field_name="forecast_identifiers",
            ),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )
        if self.supporting_only is not True:
            raise ValueError("candidate forecast references must be supporting-only")
        if self.schema_version != "candidate-forecast-support.v1":
            raise ValueError("unsupported candidate forecast-support schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "screening_cycle_identifier": self.screening_cycle_identifier,
            "candidate_identifier": self.candidate_identifier,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "forecast_identifiers": list(self.forecast_identifiers),
            "rationale": self.rationale,
            "limitations": list(self.limitations),
            "supporting_only": True,
            "candidate_creation_authority": False,
            "ranking_authority": False,
            "sizing_authority": False,
            "decision_authority": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateForecastSupport":
        return cls(
            identifier=str(value["identifier"]),
            screening_cycle_identifier=str(value["screening_cycle_identifier"]),
            candidate_identifier=str(value["candidate_identifier"]),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            knowledge_cutoff=datetime.fromisoformat(
                str(value["knowledge_cutoff"])
            ),
            forecast_identifiers=tuple(
                str(item) for item in value["forecast_identifiers"]
            ),
            rationale=str(value["rationale"]),
            limitations=tuple(str(item) for item in value["limitations"]),
            supporting_only=bool(value.get("supporting_only", True)),
            schema_version=str(
                value.get("schema_version", "candidate-forecast-support.v1")
            ),
        )


class SQLiteCandidateForecastSupportStore:
    """Append-only hash chain of candidate-to-forecast references."""

    _TABLE = "candidate_forecast_support_events"
    _GENESIS_HASH = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    screening_cycle_identifier TEXT NOT NULL,
                    candidate_identifier TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS candidate_forecast_cycle_lookup
                ON {self._TABLE} (screening_cycle_identifier, as_of, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'forecast support is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'forecast support is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        identifier: str,
        screening_cycle_identifier: str,
        candidate_identifier: str,
        as_of: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    identifier,
                    screening_cycle_identifier,
                    candidate_identifier,
                    as_of,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def append(self, reference: CandidateForecastSupport) -> int:
        if not isinstance(reference, CandidateForecastSupport):
            raise TypeError("reference must be CandidateForecastSupport")
        self.verify_integrity()
        payload_json = _canonical_json(reference.to_dict())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE identifier = ?",
                (reference.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise ForecastSupportError(
                        "forecast-support identifier has conflicting content"
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
            as_of = reference.as_of.isoformat()
            content_hash = self._hash(
                sequence=sequence,
                identifier=reference.identifier,
                screening_cycle_identifier=reference.screening_cycle_identifier,
                candidate_identifier=reference.candidate_identifier,
                as_of=as_of,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, identifier, screening_cycle_identifier,
                    candidate_identifier, as_of, payload_json, previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    reference.identifier,
                    reference.screening_cycle_identifier,
                    reference.candidate_identifier,
                    as_of,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def references_for_cycle(
        self,
        screening_cycle_identifier: str,
        *,
        as_of: datetime,
    ) -> tuple[CandidateForecastSupport, ...]:
        cycle = _text(
            screening_cycle_identifier,
            field_name="screening_cycle_identifier",
        )
        timestamp = _aware(as_of, field_name="as_of").isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE screening_cycle_identifier = ? AND as_of = ? "
                "ORDER BY sequence",
                (cycle, timestamp),
            ).fetchall()
        return tuple(
            CandidateForecastSupport.from_dict(
                json.loads(str(row["payload_json"]))
            )
            for row in rows
        )

    def verify_integrity(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        previous_hash = self._GENESIS_HASH
        for expected, row in enumerate(rows, start=1):
            if int(row["sequence"]) != expected:
                raise ForecastSupportIntegrityError(
                    "forecast-support sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise ForecastSupportIntegrityError(
                    "forecast-support previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                identifier=str(row["identifier"]),
                screening_cycle_identifier=str(
                    row["screening_cycle_identifier"]
                ),
                candidate_identifier=str(row["candidate_identifier"]),
                as_of=str(row["as_of"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise ForecastSupportIntegrityError(
                    "forecast-support content hash is invalid"
                )
            previous_hash = expected_hash
        return True


class ForecastSupportingProductionContextProvider:
    """Enrich a completed canonical context with usable forecast lineage only."""

    name = "FORECAST_SUPPORTING_PRODUCTION_CONTEXT_PROVIDER"

    def __init__(
        self,
        *,
        delegate,
        forecast_store: SQLiteForecastEvidenceStore,
        reference_store: SQLiteCandidateForecastSupportStore,
    ) -> None:
        if not hasattr(delegate, "load_context"):
            raise TypeError("delegate must implement load_context")
        if not isinstance(forecast_store, SQLiteForecastEvidenceStore):
            raise TypeError("forecast_store must be SQLiteForecastEvidenceStore")
        if not isinstance(
            reference_store,
            SQLiteCandidateForecastSupportStore,
        ):
            raise TypeError(
                "reference_store must be SQLiteCandidateForecastSupportStore"
            )
        self.delegate = delegate
        self.forecast_store = forecast_store
        self.reference_store = reference_store

    @property
    def code_version(self) -> str:
        return self.delegate.code_version

    def load_context(
        self,
        *,
        as_of: datetime,
    ) -> ProductionCanonicalCIOContext:
        decision_time = _aware(as_of, field_name="as_of")
        self.forecast_store.verify_integrity()
        self.reference_store.verify_integrity()
        context = self.delegate.load_context(as_of=decision_time)
        if context.manifest is None:
            raise ProductionContextError(
                "forecast support requires an immutable production manifest"
            )
        references = self.reference_store.references_for_cycle(
            context.screening_cycle_identifier,
            as_of=decision_time,
        )
        if not references:
            return context
        by_candidate = {item.candidate_identifier: item for item in references}
        if len(by_candidate) != len(references):
            raise ProductionContextError(
                "forecast support contains duplicate candidate references"
            )
        candidates = set(context.manifest.candidate_identifiers)
        unknown = sorted(set(by_candidate) - candidates)
        if unknown:
            raise ProductionContextError(
                "forecast support references candidates outside the canonical "
                f"qualified set: {unknown}"
            )
        evidence_identifiers: list[str] = []
        source_versions: list[tuple[str, str]] = []
        model_versions: list[tuple[str, str]] = []
        for reference in references:
            if reference.knowledge_cutoff != context.knowledge_cutoff:
                raise ProductionContextError(
                    "forecast-support cutoff does not match production context"
                )
            evidence_identifiers.append(reference.identifier)
            for forecast_identifier in reference.forecast_identifiers:
                forecast = self.forecast_store.get(forecast_identifier)
                if forecast is None:
                    raise ProductionContextError(
                        "referenced forecast evidence is unavailable: "
                        f"{forecast_identifier}"
                    )
                try:
                    forecast.require_usable(
                        decision_timestamp=decision_time,
                        knowledge_cutoff=context.knowledge_cutoff,
                    )
                except ForecastEvidenceError as error:
                    raise ProductionContextError(str(error)) from error
                evidence_identifiers.extend(
                    (
                        forecast.identifier,
                        *forecast.evidence_identifiers,
                        *forecast.originating_fact_identifiers,
                    )
                )
                source_versions.extend(forecast.data_versions)
                model_versions.extend(forecast.model_versions)
        manifest = replace(
            context.manifest,
            evidence_identifiers=tuple(
                dict.fromkeys(
                    context.manifest.evidence_identifiers
                    + tuple(evidence_identifiers)
                )
            ),
            source_versions=_merge_versions(
                context.manifest.source_versions,
                tuple(source_versions),
                field_name="source_versions",
            ),
            model_versions=_merge_versions(
                context.manifest.model_versions,
                tuple(model_versions),
                field_name="model_versions",
            ),
        )
        return replace(context, manifest=manifest)


def build_production_context_provider(
    *,
    forecast_evidence_database: str | Path | None = None,
    forecast_support_database: str | Path | None = None,
    **kwargs,
) -> ForecastSupportingProductionContextProvider:
    """Build the canonical provider with optional supporting forecast lineage."""

    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return ForecastSupportingProductionContextProvider(
        delegate=_build_base_provider(**kwargs),
        forecast_store=SQLiteForecastEvidenceStore(
            forecast_evidence_database
            or os.getenv("CAPITAL_INTELLIGENCE_FORECAST_EVIDENCE_DATABASE")
            or data_dir / "forecast_evidence.db"
        ),
        reference_store=SQLiteCandidateForecastSupportStore(
            forecast_support_database
            or os.getenv("CAPITAL_INTELLIGENCE_FORECAST_SUPPORT_DATABASE")
            or data_dir / "forecast_support.db"
        ),
    )


__all__ = [
    "CandidateForecastSupport",
    "ForecastSupportError",
    "ForecastSupportIntegrityError",
    "ForecastSupportingProductionContextProvider",
    "SQLiteCandidateForecastSupportStore",
    "build_production_context_provider",
]
