"""Persisted evidence assembly for controlled paper-product test readiness.

Readiness cannot be established by a caller-supplied collection of booleans.  The
canonical path resolves immutable gate certifications, an operational snapshot,
and active expanded-market approvals against one exact test baseline, investment
process version, and code version.  Missing or mismatched authority fails closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from cio import CandidateAssetClass
from governance.asset_class_scope import SQLiteAssetClassApprovalStore
from governance.product_readiness import ProductTestReadinessEvidence


class ReadinessEvidenceError(RuntimeError):
    """Raised when readiness evidence cannot be persisted or assembled safely."""


class ReadinessEvidenceIntegrityError(ReadinessEvidenceError):
    """Raised when the append-only readiness evidence chain is invalid."""


class ReadinessGate(str, Enum):
    CORE_US_MARKET = "core_us_market_ready"
    CRYPTO_MARKET = "crypto_market_ready"
    SPOT_FX_MARKET = "spot_fx_market_ready"
    INTERNATIONAL_EQUITY_MARKET = "international_equity_market_ready"
    CERTIFIED_DATA = "certified_data_ready"
    COMPLETE_SCREENING = "complete_screening_ready"
    PRODUCTION_CONTEXT = "production_context_ready"
    PORTFOLIO_CONSTRUCTION = "portfolio_construction_ready"
    PAPER_EXECUTION = "paper_execution_ready"
    THESIS_AND_EVALUATION = "thesis_and_evaluation_ready"
    DAILY_OPERATIONS = "daily_operations_ready"
    FOUR_SCREEN_PRODUCT = "four_screen_product_ready"
    SECURITY_SUITE = "security_suite_ready"
    RESILIENCE_CAMPAIGN = "resilience_campaign_ready"
    PAPER_ONLY_DISCLOSURES = "paper_only_disclosures_ready"


class ReadinessGateState(str, Enum):
    SATISFIED = "satisfied"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ReadinessEvidenceEventType(str, Enum):
    GATE_CERTIFICATION = "gate_certification"
    OPERATIONAL_SNAPSHOT = "operational_snapshot"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name=field_name)


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _count(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative integer")
    return value


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class ReadinessGateCertification:
    """One immutable conclusion for one readiness gate and test baseline."""

    identifier: str
    gate: ReadinessGate
    state: ReadinessGateState
    certified_at: datetime
    effective_at: datetime
    expires_at: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    evidence_identifiers: tuple[str, ...]
    authority_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "readiness-gate-certification.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.gate, ReadinessGate):
            raise TypeError("gate must be ReadinessGate")
        if not isinstance(self.state, ReadinessGateState):
            raise TypeError("state must be ReadinessGateState")
        for field_name in ("certified_at", "effective_at", "expires_at"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.effective_at < self.certified_at:
            raise ValueError("effective_at cannot predate certified_at")
        if self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
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
            "authority_identifiers",
            _texts(
                self.authority_identifiers,
                field_name="authority_identifiers",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )

    def active_at(self, assessed_at: datetime) -> bool:
        resolved = _aware(assessed_at, field_name="assessed_at")
        return self.effective_at <= resolved < self.expires_at

    @property
    def satisfied(self) -> bool:
        return self.state is ReadinessGateState.SATISFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "gate": self.gate.value,
            "state": self.state.value,
            "certified_at": self.certified_at.isoformat(),
            "effective_at": self.effective_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "evidence_identifiers": list(self.evidence_identifiers),
            "authority_identifiers": list(self.authority_identifiers),
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReadinessGateCertification":
        return cls(
            identifier=str(payload["identifier"]),
            gate=ReadinessGate(str(payload["gate"])),
            state=ReadinessGateState(str(payload["state"])),
            certified_at=datetime.fromisoformat(str(payload["certified_at"])),
            effective_at=datetime.fromisoformat(str(payload["effective_at"])),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            baseline_identifier=str(payload["baseline_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            evidence_identifiers=tuple(
                str(item) for item in payload["evidence_identifiers"]
            ),
            authority_identifiers=tuple(
                str(item) for item in payload["authority_identifiers"]
            ),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            schema_version=str(
                payload.get("schema_version", "readiness-gate-certification.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class OperationalReadinessSnapshot:
    """Point-in-time incident and reconciliation evidence for one baseline."""

    identifier: str
    observed_at: datetime
    knowledge_cutoff: datetime
    baseline_identifier: str
    process_version: str
    code_version: str
    unresolved_critical_incidents: int
    data_integrity_failures: int
    reconciliation_failures: int
    source_identifiers: tuple[str, ...]
    schema_version: str = "operational-readiness-snapshot.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "baseline_identifier",
            "process_version",
            "code_version",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.observed_at, field_name="observed_at")
        _aware(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.knowledge_cutoff < self.observed_at:
            raise ValueError("knowledge_cutoff cannot predate observed_at")
        for field_name in (
            "unresolved_critical_incidents",
            "data_integrity_failures",
            "reconciliation_failures",
        ):
            object.__setattr__(
                self,
                field_name,
                _count(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "source_identifiers",
            _texts(
                self.source_identifiers,
                field_name="source_identifiers",
                minimum=1,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "observed_at": self.observed_at.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "unresolved_critical_incidents": self.unresolved_critical_incidents,
            "data_integrity_failures": self.data_integrity_failures,
            "reconciliation_failures": self.reconciliation_failures,
            "source_identifiers": list(self.source_identifiers),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OperationalReadinessSnapshot":
        return cls(
            identifier=str(payload["identifier"]),
            observed_at=datetime.fromisoformat(str(payload["observed_at"])),
            knowledge_cutoff=datetime.fromisoformat(str(payload["knowledge_cutoff"])),
            baseline_identifier=str(payload["baseline_identifier"]),
            process_version=str(payload["process_version"]),
            code_version=str(payload["code_version"]),
            unresolved_critical_incidents=int(
                payload["unresolved_critical_incidents"]
            ),
            data_integrity_failures=int(payload["data_integrity_failures"]),
            reconciliation_failures=int(payload["reconciliation_failures"]),
            source_identifiers=tuple(
                str(item) for item in payload["source_identifiers"]
            ),
            schema_version=str(
                payload.get("schema_version", "operational-readiness-snapshot.v1")
            ),
        )


class SQLiteReadinessEvidenceStore:
    """Append-only SHA-256 authority for gate and operational evidence."""

    _TABLE = "product_readiness_evidence_events"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_identifier TEXT NOT NULL UNIQUE,
                    aggregate_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS readiness_evidence_lookup
                ON {self._TABLE}(aggregate_identifier, event_type, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'readiness evidence is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'readiness evidence is append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        sequence: int,
        event_identifier: str,
        aggregate_identifier: str,
        event_type: str,
        occurred_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                aggregate_identifier,
                event_type,
                occurred_at,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _append(
        self,
        *,
        event_identifier: str,
        aggregate_identifier: str,
        event_type: ReadinessEvidenceEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        event_id = _text(event_identifier, field_name="event_identifier")
        aggregate = _text(
            aggregate_identifier,
            field_name="aggregate_identifier",
        )
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = _json(payload)
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,event_type,payload_json FROM {self._TABLE} "
                "WHERE event_identifier=?",
                (event_id,),
            ).fetchone()
            if existing is not None:
                if existing[1] != event_type.value or existing[2] != payload_json:
                    raise ReadinessEvidenceError(
                        "readiness event identifier already exists with different content"
                    )
                return int(existing[0])
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous = self._GENESIS if tail is None else str(tail[1])
            content_hash = self._hash(
                sequence,
                event_id,
                aggregate,
                event_type.value,
                timestamp,
                payload_json,
                previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?,?,?)",
                (
                    sequence,
                    event_id,
                    aggregate,
                    event_type.value,
                    timestamp,
                    payload_json,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def append_gate(self, value: ReadinessGateCertification) -> int:
        if not isinstance(value, ReadinessGateCertification):
            raise TypeError("value must be ReadinessGateCertification")
        return self._append(
            event_identifier=value.identifier,
            aggregate_identifier=value.gate.value,
            event_type=ReadinessEvidenceEventType.GATE_CERTIFICATION,
            occurred_at=value.certified_at,
            payload=value.to_dict(),
        )

    def append_operational(self, value: OperationalReadinessSnapshot) -> int:
        if not isinstance(value, OperationalReadinessSnapshot):
            raise TypeError("value must be OperationalReadinessSnapshot")
        return self._append(
            event_identifier=value.identifier,
            aggregate_identifier=value.baseline_identifier,
            event_type=ReadinessEvidenceEventType.OPERATIONAL_SNAPSHOT,
            occurred_at=value.observed_at,
            payload=value.to_dict(),
        )

    def gate_history(
        self,
        gate: ReadinessGate,
    ) -> tuple[ReadinessGateCertification, ...]:
        if not isinstance(gate, ReadinessGate):
            raise TypeError("gate must be ReadinessGate")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE aggregate_identifier=? AND event_type=? ORDER BY sequence",
                (gate.value, ReadinessEvidenceEventType.GATE_CERTIFICATION.value),
            ).fetchall()
        return tuple(
            ReadinessGateCertification.from_dict(json.loads(str(row[0])))
            for row in rows
        )

    def active_gate(
        self,
        gate: ReadinessGate,
        *,
        assessed_at: datetime,
    ) -> ReadinessGateCertification | None:
        matching = tuple(
            item for item in self.gate_history(gate) if item.active_at(assessed_at)
        )
        return None if not matching else matching[-1]

    def latest_operational(
        self,
        *,
        assessed_at: datetime,
    ) -> OperationalReadinessSnapshot | None:
        timestamp = _aware(assessed_at, field_name="assessed_at")
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} "
                "WHERE event_type=? ORDER BY sequence DESC",
                (ReadinessEvidenceEventType.OPERATIONAL_SNAPSHOT.value,),
            ).fetchall()
        for row in rows:
            item = OperationalReadinessSnapshot.from_dict(json.loads(str(row[0])))
            if item.knowledge_cutoff <= timestamp:
                return item
        return None

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, 1):
            if int(row[0]) != expected or str(row[6]) != previous:
                raise ReadinessEvidenceIntegrityError(
                    "readiness evidence chain is not contiguous"
                )
            actual = self._hash(
                int(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                str(row[4]),
                str(row[5]),
                str(row[6]),
            )
            if str(row[7]) != actual:
                raise ReadinessEvidenceIntegrityError(
                    "readiness evidence content hash is invalid"
                )
            previous = actual
        return True


class ProductTestReadinessEvidenceAssembler:
    """Build one fail-closed readiness input from persisted authorities."""

    _ASSET_GATES = {
        ReadinessGate.CRYPTO_MARKET: CandidateAssetClass.CRYPTO,
        ReadinessGate.SPOT_FX_MARKET: CandidateAssetClass.FX,
        ReadinessGate.INTERNATIONAL_EQUITY_MARKET: (
            CandidateAssetClass.INTERNATIONAL_EQUITY
        ),
    }

    def __init__(
        self,
        *,
        evidence_store: SQLiteReadinessEvidenceStore,
        asset_class_store: SQLiteAssetClassApprovalStore,
        maximum_operational_snapshot_age: timedelta = timedelta(hours=24),
    ) -> None:
        if not isinstance(evidence_store, SQLiteReadinessEvidenceStore):
            raise TypeError("evidence_store must be SQLiteReadinessEvidenceStore")
        if not isinstance(asset_class_store, SQLiteAssetClassApprovalStore):
            raise TypeError("asset_class_store must be SQLiteAssetClassApprovalStore")
        if not isinstance(maximum_operational_snapshot_age, timedelta):
            raise TypeError("maximum_operational_snapshot_age must be timedelta")
        if maximum_operational_snapshot_age <= timedelta(0):
            raise ValueError("maximum_operational_snapshot_age must be positive")
        self.evidence_store = evidence_store
        self.asset_class_store = asset_class_store
        self.maximum_operational_snapshot_age = maximum_operational_snapshot_age

    def assemble(
        self,
        *,
        assessed_at: datetime,
        baseline_identifier: str | None,
        process_version: str | None,
        code_version: str,
        open_development_items: tuple[str, ...] = (),
    ) -> ProductTestReadinessEvidence:
        timestamp = _aware(assessed_at, field_name="assessed_at")
        baseline = _optional_text(
            baseline_identifier,
            field_name="baseline_identifier",
        )
        process = _optional_text(process_version, field_name="process_version")
        code = _text(code_version, field_name="code_version")
        self.evidence_store.verify_integrity()
        self.asset_class_store.verify_integrity()

        flags: dict[str, bool] = {}
        evidence_ids: list[str] = []
        development_items: list[str] = list(
            _texts(
                open_development_items,
                field_name="open_development_items",
            )
        )
        for gate in ReadinessGate:
            certification = self.evidence_store.active_gate(
                gate,
                assessed_at=timestamp,
            )
            valid = True
            if certification is None:
                valid = False
                development_items.append(f"{gate.value}: certification unavailable")
            else:
                evidence_ids.extend(
                    (
                        certification.identifier,
                        *certification.evidence_identifiers,
                        *certification.authority_identifiers,
                    )
                )
                if not certification.satisfied:
                    valid = False
                    development_items.append(
                        f"{gate.value}: state={certification.state.value}"
                    )
                if baseline is None or certification.baseline_identifier != baseline:
                    valid = False
                    development_items.append(
                        f"{gate.value}: baseline mismatch"
                    )
                if process is None or certification.process_version != process:
                    valid = False
                    development_items.append(
                        f"{gate.value}: process-version mismatch"
                    )
                if certification.code_version != code:
                    valid = False
                    development_items.append(
                        f"{gate.value}: code-version mismatch"
                    )

            asset_class = self._ASSET_GATES.get(gate)
            if asset_class is not None:
                approval = self.asset_class_store.active(
                    asset_class,
                    evaluated_at=timestamp,
                )
                if approval is None:
                    valid = False
                    development_items.append(
                        f"{gate.value}: active asset-class approval unavailable"
                    )
                else:
                    evidence_ids.extend(
                        (
                            approval.identifier,
                            approval.governance_identifier,
                            *approval.profile.source_identifiers,
                        )
                    )
                    if not approval.profile.paper_eligible:
                        valid = False
                        development_items.append(
                            f"{gate.value}: asset class is not paper eligible"
                        )
                    if process is None or approval.process_version != process:
                        valid = False
                        development_items.append(
                            f"{gate.value}: asset approval process mismatch"
                        )
                    if approval.code_version != code:
                        valid = False
                        development_items.append(
                            f"{gate.value}: asset approval code mismatch"
                        )
            flags[gate.value] = valid

        operational = self.evidence_store.latest_operational(assessed_at=timestamp)
        unresolved_incidents = 0
        data_failures = 0
        reconciliation_failures = 0
        operational_valid = True
        if operational is None:
            operational_valid = False
            development_items.append("operational readiness snapshot unavailable")
        else:
            evidence_ids.extend((operational.identifier, *operational.source_identifiers))
            unresolved_incidents = operational.unresolved_critical_incidents
            data_failures = operational.data_integrity_failures
            reconciliation_failures = operational.reconciliation_failures
            if timestamp - operational.knowledge_cutoff > self.maximum_operational_snapshot_age:
                operational_valid = False
                development_items.append("operational readiness snapshot is stale")
            if baseline is None or operational.baseline_identifier != baseline:
                operational_valid = False
                development_items.append("operational snapshot baseline mismatch")
            if process is None or operational.process_version != process:
                operational_valid = False
                development_items.append("operational snapshot process mismatch")
            if operational.code_version != code:
                operational_valid = False
                development_items.append("operational snapshot code mismatch")

        if not operational_valid:
            for gate in (
                ReadinessGate.DAILY_OPERATIONS,
                ReadinessGate.SECURITY_SUITE,
                ReadinessGate.RESILIENCE_CAMPAIGN,
            ):
                flags[gate.value] = False
        if unresolved_incidents:
            flags[ReadinessGate.SECURITY_SUITE.value] = False
            flags[ReadinessGate.RESILIENCE_CAMPAIGN.value] = False
        if data_failures or reconciliation_failures:
            flags[ReadinessGate.DAILY_OPERATIONS.value] = False
            flags[ReadinessGate.RESILIENCE_CAMPAIGN.value] = False

        assembly_identifier = (
            f"readiness-assembly:{baseline or 'unversioned'}:{timestamp.isoformat()}"
        )
        evidence = tuple(dict.fromkeys((assembly_identifier, *evidence_ids)))
        items = tuple(dict.fromkeys(development_items))
        return ProductTestReadinessEvidence(
            identifier=assembly_identifier,
            assessed_at=timestamp,
            test_baseline_identifier=baseline,
            process_version=process,
            code_version=code,
            development_remains_open=True,
            core_us_market_ready=flags[ReadinessGate.CORE_US_MARKET.value],
            crypto_market_ready=flags[ReadinessGate.CRYPTO_MARKET.value],
            spot_fx_market_ready=flags[ReadinessGate.SPOT_FX_MARKET.value],
            international_equity_market_ready=flags[
                ReadinessGate.INTERNATIONAL_EQUITY_MARKET.value
            ],
            certified_data_ready=flags[ReadinessGate.CERTIFIED_DATA.value],
            complete_screening_ready=flags[ReadinessGate.COMPLETE_SCREENING.value],
            production_context_ready=flags[ReadinessGate.PRODUCTION_CONTEXT.value],
            portfolio_construction_ready=flags[
                ReadinessGate.PORTFOLIO_CONSTRUCTION.value
            ],
            paper_execution_ready=flags[ReadinessGate.PAPER_EXECUTION.value],
            thesis_and_evaluation_ready=flags[
                ReadinessGate.THESIS_AND_EVALUATION.value
            ],
            daily_operations_ready=flags[ReadinessGate.DAILY_OPERATIONS.value],
            four_screen_product_ready=flags[ReadinessGate.FOUR_SCREEN_PRODUCT.value],
            security_suite_ready=flags[ReadinessGate.SECURITY_SUITE.value],
            resilience_campaign_ready=flags[
                ReadinessGate.RESILIENCE_CAMPAIGN.value
            ],
            paper_only_disclosures_ready=flags[
                ReadinessGate.PAPER_ONLY_DISCLOSURES.value
            ],
            unresolved_critical_incidents=unresolved_incidents,
            data_integrity_failures=data_failures,
            reconciliation_failures=reconciliation_failures,
            evidence_identifiers=evidence,
            open_development_items=items,
        )


__all__ = [
    "OperationalReadinessSnapshot",
    "ProductTestReadinessEvidenceAssembler",
    "ReadinessEvidenceError",
    "ReadinessEvidenceEventType",
    "ReadinessEvidenceIntegrityError",
    "ReadinessGate",
    "ReadinessGateCertification",
    "ReadinessGateState",
    "SQLiteReadinessEvidenceStore",
]
