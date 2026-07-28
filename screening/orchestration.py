"""Resumable, all-or-nothing full-universe screening orchestration.

The orchestrator is deliberately downstream of provider certification and
security-master activation.  It cannot discover or upgrade data authority.  It
may publish candidates and an opportunity queue only after every constituent in
one immutable Version 1 universe snapshot has a terminal screening result.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
    PayoffDistributionPoint,
)
from cio.persistence import (
    SQLiteCIOJournal,
    serialize_candidate_decision,
    serialize_opportunity_queue,
)
from data import (
    PointInTimeSecurityMasterSnapshot,
    SecurityMasterCatalog,
    SecurityMasterMarketMetrics,
    Version1UniverseBuilder,
    Version1UniverseConstituent,
    Version1UniverseSnapshot,
)
from operations import (
    FullUniverseCycleRecord,
    FullUniverseCycleStatus,
    SQLiteOperationalSLOStore,
)
from opportunity import OpportunityEngine, OpportunityQueue, OpportunitySetContext


class FullUniverseScreeningError(RuntimeError):
    """Raised when a governed cycle cannot produce a complete publication."""


class ScreeningEventType(str, Enum):
    CYCLE_STARTED = "cycle_started"
    PARTITION_ATTEMPT = "partition_attempt"
    INSTRUMENT_RESULT = "instrument_result"
    PUBLICATION = "publication"
    CYCLE_FAILED = "cycle_failed"


class ScreeningDisposition(str, Enum):
    CANDIDATE = "candidate"
    EXCLUDED = "excluded"


def _required_text(value: object, *, field_name: str) -> str:
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


def _non_negative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("screening payload must be finite JSON") from error


@dataclass(frozen=True, slots=True)
class FullUniverseScreeningRequest:
    identifier: str
    scheduled_for: datetime
    as_of: datetime
    knowledge_cutoff: datetime
    started_at: datetime
    partition_size: int = 250
    maximum_partition_attempts: int = 3
    require_complete_metric_coverage: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(self.identifier, field_name="identifier"),
        )
        for field_name in (
            "scheduled_for",
            "as_of",
            "knowledge_cutoff",
            "started_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _aware(getattr(self, field_name), field_name=field_name),
            )
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        if self.started_at < self.scheduled_for:
            raise ValueError("started_at cannot predate scheduled_for")
        for field_name in ("partition_size", "maximum_partition_attempts"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 1:
                raise ValueError(f"{field_name} must be positive")
        if not isinstance(self.require_complete_metric_coverage, bool):
            raise TypeError("require_complete_metric_coverage must be a bool")


@dataclass(frozen=True, slots=True)
class CandidateScreeningDecision:
    candidate: CandidateDecisionRecord | None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate is not None and not isinstance(
            self.candidate,
            CandidateDecisionRecord,
        ):
            raise TypeError("candidate must be a CandidateDecisionRecord or None")
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")
        if self.candidate is None and not self.reasons:
            raise ValueError("an excluded instrument must explain its exclusion")


@dataclass(frozen=True, slots=True)
class InstrumentScreeningResult:
    cycle_identifier: str
    partition_index: int
    instrument_identifier: str
    symbol: str
    disposition: ScreeningDisposition
    completed_at: datetime
    candidate_payload: Mapping[str, Any] | None = None
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "cycle_identifier",
            "instrument_identifier",
            "symbol",
        ):
            value = _required_text(getattr(self, field_name), field_name=field_name)
            if field_name == "symbol":
                value = value.upper()
            object.__setattr__(self, field_name, value)
        if isinstance(self.partition_index, bool) or not isinstance(
            self.partition_index,
            int,
        ):
            raise TypeError("partition_index must be an integer")
        if self.partition_index < 0:
            raise ValueError("partition_index cannot be negative")
        if not isinstance(self.disposition, ScreeningDisposition):
            raise TypeError("disposition must be a ScreeningDisposition")
        object.__setattr__(
            self,
            "completed_at",
            _aware(self.completed_at, field_name="completed_at"),
        )
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.reasons
        ):
            raise TypeError("reasons must contain non-empty strings")
        if self.disposition is ScreeningDisposition.CANDIDATE:
            if self.candidate_payload is None:
                raise ValueError("candidate result requires candidate_payload")
            _canonical_json(self.candidate_payload)
            if self.reasons:
                raise ValueError("candidate result cannot contain exclusion reasons")
        else:
            if self.candidate_payload is not None:
                raise ValueError("excluded result cannot contain candidate_payload")
            if not self.reasons:
                raise ValueError("excluded result must explain its exclusion")

    @property
    def event_identifier(self) -> str:
        return (
            f"screening:{self.cycle_identifier}:instrument:"
            f"{self.instrument_identifier}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_identifier": self.cycle_identifier,
            "partition_index": self.partition_index,
            "instrument_identifier": self.instrument_identifier,
            "symbol": self.symbol,
            "disposition": self.disposition.value,
            "completed_at": self.completed_at.isoformat(),
            "candidate_payload": (
                None if self.candidate_payload is None else dict(self.candidate_payload)
            ),
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "InstrumentScreeningResult":
        candidate_payload = payload.get("candidate_payload")
        return cls(
            cycle_identifier=str(payload["cycle_identifier"]),
            partition_index=int(payload["partition_index"]),
            instrument_identifier=str(payload["instrument_identifier"]),
            symbol=str(payload["symbol"]),
            disposition=ScreeningDisposition(str(payload["disposition"])),
            completed_at=datetime.fromisoformat(str(payload["completed_at"])),
            candidate_payload=(
                None if candidate_payload is None else dict(candidate_payload)
            ),
            reasons=tuple(str(item) for item in payload.get("reasons", ())),
        )


@dataclass(frozen=True, slots=True)
class FullUniverseScreeningPublication:
    identifier: str
    cycle_identifier: str
    published_at: datetime
    security_master_catalog_identifier: str
    security_master_snapshot_identifier: str
    universe_snapshot_identifier: str
    opportunity_context_identifier: str
    eligible_instrument_count: int
    screened_instrument_count: int
    candidate_count: int
    excluded_count: int
    candidate_payloads: tuple[Mapping[str, Any], ...]
    exclusions: tuple[Mapping[str, Any], ...]
    opportunity_queue_payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "cycle_identifier",
            "security_master_catalog_identifier",
            "security_master_snapshot_identifier",
            "universe_snapshot_identifier",
            "opportunity_context_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "published_at",
            _aware(self.published_at, field_name="published_at"),
        )
        for field_name in (
            "eligible_instrument_count",
            "screened_instrument_count",
            "candidate_count",
            "excluded_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_integer(getattr(self, field_name), field_name=field_name),
            )
        if self.screened_instrument_count != self.eligible_instrument_count:
            raise ValueError("publication requires complete eligible-universe coverage")
        if self.candidate_count + self.excluded_count != self.screened_instrument_count:
            raise ValueError("candidate and exclusion counts must reconcile")
        if len(self.candidate_payloads) != self.candidate_count:
            raise ValueError("candidate_payloads do not match candidate_count")
        if len(self.exclusions) != self.excluded_count:
            raise ValueError("exclusions do not match excluded_count")
        for payload in (*self.candidate_payloads, *self.exclusions):
            _canonical_json(payload)
        _canonical_json(self.opportunity_queue_payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "cycle_identifier": self.cycle_identifier,
            "published_at": self.published_at.isoformat(),
            "security_master_catalog_identifier": self.security_master_catalog_identifier,
            "security_master_snapshot_identifier": self.security_master_snapshot_identifier,
            "universe_snapshot_identifier": self.universe_snapshot_identifier,
            "opportunity_context_identifier": self.opportunity_context_identifier,
            "eligible_instrument_count": self.eligible_instrument_count,
            "screened_instrument_count": self.screened_instrument_count,
            "candidate_count": self.candidate_count,
            "excluded_count": self.excluded_count,
            "candidate_payloads": [dict(item) for item in self.candidate_payloads],
            "exclusions": [dict(item) for item in self.exclusions],
            "opportunity_queue_payload": dict(self.opportunity_queue_payload),
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "FullUniverseScreeningPublication":
        return cls(
            identifier=str(payload["identifier"]),
            cycle_identifier=str(payload["cycle_identifier"]),
            published_at=datetime.fromisoformat(str(payload["published_at"])),
            security_master_catalog_identifier=str(
                payload["security_master_catalog_identifier"]
            ),
            security_master_snapshot_identifier=str(
                payload["security_master_snapshot_identifier"]
            ),
            universe_snapshot_identifier=str(payload["universe_snapshot_identifier"]),
            opportunity_context_identifier=str(payload["opportunity_context_identifier"]),
            eligible_instrument_count=int(payload["eligible_instrument_count"]),
            screened_instrument_count=int(payload["screened_instrument_count"]),
            candidate_count=int(payload["candidate_count"]),
            excluded_count=int(payload["excluded_count"]),
            candidate_payloads=tuple(dict(item) for item in payload["candidate_payloads"]),
            exclusions=tuple(dict(item) for item in payload["exclusions"]),
            opportunity_queue_payload=dict(payload["opportunity_queue_payload"]),
        )


@dataclass(frozen=True, slots=True)
class FullUniverseScreeningRun:
    publication: FullUniverseScreeningPublication
    universe: Version1UniverseSnapshot | None
    candidates: tuple[CandidateDecisionRecord, ...]
    opportunity_queue: OpportunityQueue


@dataclass(frozen=True, slots=True)
class ScreeningEvent:
    sequence: int
    event_identifier: str
    cycle_identifier: str
    event_type: ScreeningEventType
    occurred_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


@runtime_checkable
class UniverseMetricsProvider(Protocol):
    @property
    def name(self) -> str: ...

    def fetch_metrics(
        self,
        snapshot: PointInTimeSecurityMasterSnapshot,
    ) -> tuple[SecurityMasterMarketMetrics, ...]: ...


@runtime_checkable
class CandidateScreeningProvider(Protocol):
    @property
    def name(self) -> str: ...

    def screen(
        self,
        constituent: Version1UniverseConstituent,
        *,
        as_of: datetime,
        opportunity_cost_return: float,
    ) -> CandidateScreeningDecision: ...


class SQLiteFullUniverseScreeningStore:
    """One append-only SHA-256 chain for cycle, retry, result, and publication events."""

    _TABLE = "full_universe_screening_events"
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
                    cycle_identifier TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS full_universe_screening_cycle_sequence
                ON {self._TABLE} (cycle_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'full-universe screening history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN
                    SELECT RAISE(ABORT, 'full-universe screening history is append-only');
                END;
                """
            )

    @staticmethod
    def _hash(
        *,
        sequence: int,
        event_identifier: str,
        cycle_identifier: str,
        event_type: ScreeningEventType,
        occurred_at: datetime,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                cycle_identifier,
                event_type.value,
                occurred_at.isoformat(),
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(
        self,
        *,
        event_identifier: str,
        cycle_identifier: str,
        event_type: ScreeningEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> ScreeningEvent:
        return self.append_many(
            (
                (
                    event_identifier,
                    cycle_identifier,
                    event_type,
                    occurred_at,
                    payload,
                ),
            )
        )[0]

    def append_many(
        self,
        values: tuple[
            tuple[str, str, ScreeningEventType, datetime, Mapping[str, Any]], ...
        ],
    ) -> tuple[ScreeningEvent, ...]:
        if not isinstance(values, tuple) or not values:
            raise ValueError("values must be a non-empty tuple")
        self.verify_integrity()
        connection = self._connect()
        events: list[ScreeningEvent] = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous_row = connection.execute(
                f"SELECT sequence, content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = int(previous_row["sequence"]) if previous_row else 0
            previous_hash = (
                str(previous_row["content_hash"])
                if previous_row is not None
                else self._GENESIS_HASH
            )
            for raw_identifier, raw_cycle, event_type, raw_time, payload in values:
                identifier = _required_text(raw_identifier, field_name="event_identifier")
                cycle = _required_text(raw_cycle, field_name="cycle_identifier")
                if not isinstance(event_type, ScreeningEventType):
                    raise TypeError("event_type must be a ScreeningEventType")
                occurred_at = _aware(raw_time, field_name="occurred_at")
                payload_json = _canonical_json(payload)
                existing = connection.execute(
                    f"SELECT * FROM {self._TABLE} WHERE event_identifier = ?",
                    (identifier,),
                ).fetchone()
                if existing is not None:
                    event = self._event(existing)
                    if (
                        event.cycle_identifier != cycle
                        or event.event_type is not event_type
                        or event.occurred_at != occurred_at
                        or event.payload_json != payload_json
                    ):
                        raise ValueError(
                            "screening event identifier cannot be reused for different content"
                        )
                    events.append(event)
                    continue
                sequence += 1
                content_hash = self._hash(
                    sequence=sequence,
                    event_identifier=identifier,
                    cycle_identifier=cycle,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    payload_json=payload_json,
                    previous_hash=previous_hash,
                )
                connection.execute(
                    f"""
                    INSERT INTO {self._TABLE} (
                        sequence, event_identifier, cycle_identifier, event_type,
                        occurred_at, payload_json, previous_hash, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        identifier,
                        cycle,
                        event_type.value,
                        occurred_at.isoformat(),
                        payload_json,
                        previous_hash,
                        content_hash,
                    ),
                )
                event = ScreeningEvent(
                    sequence=sequence,
                    event_identifier=identifier,
                    cycle_identifier=cycle,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    payload_json=payload_json,
                    previous_hash=previous_hash,
                    content_hash=content_hash,
                )
                events.append(event)
                previous_hash = content_hash
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return tuple(events)

    def events(
        self,
        cycle_identifier: str,
        *,
        event_type: ScreeningEventType | None = None,
    ) -> tuple[ScreeningEvent, ...]:
        cycle = _required_text(cycle_identifier, field_name="cycle_identifier")
        if not self.path.exists():
            return ()
        query = f"SELECT * FROM {self._TABLE} WHERE cycle_identifier = ?"
        parameters: list[object] = [cycle]
        if event_type is not None:
            if not isinstance(event_type, ScreeningEventType):
                raise TypeError("event_type must be a ScreeningEventType")
            query += " AND event_type = ?"
            parameters.append(event_type.value)
        query += " ORDER BY sequence"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return tuple(self._event(row) for row in rows)

    def instrument_results(
        self,
        cycle_identifier: str,
    ) -> tuple[InstrumentScreeningResult, ...]:
        return tuple(
            InstrumentScreeningResult.from_dict(event.payload)
            for event in self.events(
                cycle_identifier,
                event_type=ScreeningEventType.INSTRUMENT_RESULT,
            )
        )

    def partition_attempt_count(
        self,
        cycle_identifier: str,
        partition_index: int,
    ) -> int:
        return sum(
            1
            for event in self.events(
                cycle_identifier,
                event_type=ScreeningEventType.PARTITION_ATTEMPT,
            )
            if int(event.payload["partition_index"]) == partition_index
        )

    def publication(
        self,
        cycle_identifier: str,
    ) -> FullUniverseScreeningPublication | None:
        events = self.events(
            cycle_identifier,
            event_type=ScreeningEventType.PUBLICATION,
        )
        if not events:
            return None
        if len(events) != 1:
            raise FullUniverseScreeningError("cycle contains multiple publications")
        return FullUniverseScreeningPublication.from_dict(events[0].payload)

    def verify_integrity(self) -> bool:
        if not self.path.exists():
            return True
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        expected_sequence = 1
        previous_hash = self._GENESIS_HASH
        for row in rows:
            event = self._event(row)
            if event.sequence != expected_sequence:
                raise FullUniverseScreeningError(
                    "screening event sequence is not contiguous"
                )
            if event.previous_hash != previous_hash:
                raise FullUniverseScreeningError(
                    "screening event previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=event.sequence,
                event_identifier=event.event_identifier,
                cycle_identifier=event.cycle_identifier,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                payload_json=event.payload_json,
                previous_hash=event.previous_hash,
            )
            if event.content_hash != expected_hash:
                raise FullUniverseScreeningError(
                    "screening event content hash is invalid"
                )
            previous_hash = event.content_hash
            expected_sequence += 1
        return True

    @staticmethod
    def _event(row: sqlite3.Row) -> ScreeningEvent:
        return ScreeningEvent(
            sequence=int(row["sequence"]),
            event_identifier=str(row["event_identifier"]),
            cycle_identifier=str(row["cycle_identifier"]),
            event_type=ScreeningEventType(str(row["event_type"])),
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )


class FullUniverseScreeningOrchestrator:
    """Execute one complete eligible-universe cycle with resumable partitions."""

    def __init__(
        self,
        *,
        security_master_service: object,
        metrics_provider: UniverseMetricsProvider,
        candidate_provider: CandidateScreeningProvider,
        screening_store: SQLiteFullUniverseScreeningStore,
        slo_store: SQLiteOperationalSLOStore,
        universe_builder: Version1UniverseBuilder | None = None,
        opportunity_engine: OpportunityEngine | None = None,
        journal: SQLiteCIOJournal | None = None,
        clock=None,
    ) -> None:
        active_catalog = getattr(security_master_service, "active_catalog", None)
        if not callable(active_catalog):
            raise TypeError("security_master_service must expose active_catalog")
        if not isinstance(metrics_provider, UniverseMetricsProvider):
            raise TypeError("metrics_provider must implement UniverseMetricsProvider")
        if not isinstance(candidate_provider, CandidateScreeningProvider):
            raise TypeError("candidate_provider must implement CandidateScreeningProvider")
        if not isinstance(screening_store, SQLiteFullUniverseScreeningStore):
            raise TypeError("screening_store must be SQLiteFullUniverseScreeningStore")
        if not isinstance(slo_store, SQLiteOperationalSLOStore):
            raise TypeError("slo_store must be SQLiteOperationalSLOStore")
        self.security_master_service = security_master_service
        self.metrics_provider = metrics_provider
        self.candidate_provider = candidate_provider
        self.screening_store = screening_store
        self.slo_store = slo_store
        self.universe_builder = universe_builder or Version1UniverseBuilder()
        self.opportunity_engine = opportunity_engine or OpportunityEngine()
        self.journal = journal
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        request: FullUniverseScreeningRequest,
        context: OpportunitySetContext,
    ) -> FullUniverseScreeningRun:
        if not isinstance(request, FullUniverseScreeningRequest):
            raise TypeError("request must be FullUniverseScreeningRequest")
        if not isinstance(context, OpportunitySetContext):
            raise TypeError("context must be OpportunitySetContext")
        if context.as_of != request.as_of:
            raise ValueError("opportunity context and screening request must share as_of")
        existing_publication = self.screening_store.publication(request.identifier)
        if existing_publication is not None:
            if (
                existing_publication.opportunity_context_identifier
                != context.identifier
            ):
                raise ValueError(
                    "persisted publication belongs to a different opportunity context"
                )
            candidates = tuple(
                _candidate_from_payload(payload)
                for payload in existing_publication.candidate_payloads
            )
            queue = self.opportunity_engine.build_queue(candidates, context)
            self._record_completed_downstream(
                request=request,
                publication=existing_publication,
                candidates=candidates,
                queue=queue,
            )
            return FullUniverseScreeningRun(
                publication=existing_publication,
                universe=None,
                candidates=candidates,
                opportunity_queue=queue,
            )

        try:
            catalog, master_snapshot, universe = self._prepare_universe(request)
            self._record_cycle_start(request, catalog, master_snapshot, universe, context)
            self._screen_partitions(request, universe, context)
            return self._publish(
                request=request,
                catalog=catalog,
                master_snapshot=master_snapshot,
                universe=universe,
                context=context,
            )
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            self._record_cycle_failure(request, error)
            if isinstance(error, FullUniverseScreeningError):
                raise
            raise FullUniverseScreeningError(str(error)) from error

    def _prepare_universe(
        self,
        request: FullUniverseScreeningRequest,
    ) -> tuple[
        SecurityMasterCatalog,
        PointInTimeSecurityMasterSnapshot,
        Version1UniverseSnapshot,
    ]:
        catalog = self.security_master_service.active_catalog(
            evaluated_at=request.knowledge_cutoff
        )
        if not isinstance(catalog, SecurityMasterCatalog):
            raise FullUniverseScreeningError(
                "active security-master service returned an invalid catalog"
            )
        snapshot = catalog.snapshot(
            as_of=request.as_of,
            knowledge_cutoff=request.knowledge_cutoff,
            require_authoritative=True,
        )
        metrics = self.metrics_provider.fetch_metrics(snapshot)
        if not isinstance(metrics, tuple) or not all(
            isinstance(item, SecurityMasterMarketMetrics) for item in metrics
        ):
            raise FullUniverseScreeningError(
                "metrics provider returned invalid point-in-time metrics"
            )
        metric_ids = tuple(item.instrument_identifier for item in metrics)
        if len(metric_ids) != len(set(metric_ids)):
            raise FullUniverseScreeningError(
                "metrics provider returned duplicate instruments"
            )
        if request.require_complete_metric_coverage:
            master_ids = {item.instrument.instrument_id for item in snapshot.instruments}
            provided_ids = set(metric_ids)
            missing = sorted(master_ids - provided_ids)
            extra = sorted(provided_ids - master_ids)
            if missing or extra:
                detail = []
                if missing:
                    detail.append(f"missing metrics for {len(missing)} instruments")
                if extra:
                    detail.append(f"metrics contain {len(extra)} unknown instruments")
                raise FullUniverseScreeningError("; ".join(detail))
        universe = self.universe_builder.build(
            snapshot,
            metrics,
            require_authoritative=True,
        )
        if not universe.authoritative:
            raise FullUniverseScreeningError(
                "Version 1 universe snapshot is not authoritative"
            )
        return catalog, snapshot, universe

    def _record_cycle_start(
        self,
        request: FullUniverseScreeningRequest,
        catalog: SecurityMasterCatalog,
        snapshot: PointInTimeSecurityMasterSnapshot,
        universe: Version1UniverseSnapshot,
        context: OpportunitySetContext,
    ) -> None:
        payload = {
            "cycle_identifier": request.identifier,
            "scheduled_for": request.scheduled_for.isoformat(),
            "started_at": request.started_at.isoformat(),
            "as_of": request.as_of.isoformat(),
            "knowledge_cutoff": request.knowledge_cutoff.isoformat(),
            "metrics_provider": self.metrics_provider.name,
            "candidate_provider": self.candidate_provider.name,
            "catalog_identifier": catalog.identifier,
            "security_master_snapshot_identifier": snapshot.identifier,
            "universe_snapshot_identifier": universe.identifier,
            "policy_version": universe.policy_version,
            "opportunity_context_identifier": context.identifier,
            "eligible_instrument_count": len(universe.constituents),
            "structural_exclusion_count": len(universe.exclusions),
            "partition_size": request.partition_size,
            "maximum_partition_attempts": request.maximum_partition_attempts,
        }
        self.screening_store.append(
            event_identifier=f"screening:{request.identifier}:start",
            cycle_identifier=request.identifier,
            event_type=ScreeningEventType.CYCLE_STARTED,
            occurred_at=request.started_at,
            payload=payload,
        )

    def _screen_partitions(
        self,
        request: FullUniverseScreeningRequest,
        universe: Version1UniverseSnapshot,
        context: OpportunitySetContext,
    ) -> None:
        completed = {
            item.instrument_identifier: item
            for item in self.screening_store.instrument_results(request.identifier)
        }
        constituents = universe.constituents
        for partition_index, offset in enumerate(
            range(0, len(constituents), request.partition_size)
        ):
            partition = constituents[offset : offset + request.partition_size]
            if all(
                item.instrument.instrument_id in completed for item in partition
            ):
                continue
            prior_attempts = self.screening_store.partition_attempt_count(
                request.identifier,
                partition_index,
            )
            succeeded = False
            last_error: Exception | None = None
            for attempt in range(
                prior_attempts + 1,
                prior_attempts + request.maximum_partition_attempts + 1,
            ):
                attempt_started = _aware(self.clock(), field_name="clock")
                try:
                    pending_results: list[InstrumentScreeningResult] = []
                    for constituent in partition:
                        instrument_id = constituent.instrument.instrument_id
                        if instrument_id in completed:
                            continue
                        decision = self.candidate_provider.screen(
                            constituent,
                            as_of=request.as_of,
                            opportunity_cost_return=(
                                context.best_alternative().net_expected_return
                            ),
                        )
                        if not isinstance(decision, CandidateScreeningDecision):
                            raise TypeError(
                                "candidate provider must return CandidateScreeningDecision"
                            )
                        completed_at = _aware(self.clock(), field_name="clock")
                        if decision.candidate is None:
                            result = InstrumentScreeningResult(
                                cycle_identifier=request.identifier,
                                partition_index=partition_index,
                                instrument_identifier=instrument_id,
                                symbol=constituent.instrument.symbol,
                                disposition=ScreeningDisposition.EXCLUDED,
                                completed_at=completed_at,
                                reasons=decision.reasons,
                            )
                        else:
                            self._validate_candidate(
                                decision.candidate,
                                constituent,
                                request=request,
                                context=context,
                            )
                            result = InstrumentScreeningResult(
                                cycle_identifier=request.identifier,
                                partition_index=partition_index,
                                instrument_identifier=instrument_id,
                                symbol=constituent.instrument.symbol,
                                disposition=ScreeningDisposition.CANDIDATE,
                                completed_at=completed_at,
                                candidate_payload=serialize_candidate_decision(
                                    decision.candidate
                                ),
                            )
                        pending_results.append(result)
                    completed_at = _aware(self.clock(), field_name="clock")
                    values: list[
                        tuple[
                            str,
                            str,
                            ScreeningEventType,
                            datetime,
                            Mapping[str, Any],
                        ]
                    ] = [
                        (
                            f"screening:{request.identifier}:partition:"
                            f"{partition_index}:attempt:{attempt}",
                            request.identifier,
                            ScreeningEventType.PARTITION_ATTEMPT,
                            completed_at,
                            {
                                "partition_index": partition_index,
                                "attempt": attempt,
                                "status": "completed",
                                "started_at": attempt_started.isoformat(),
                                "completed_at": completed_at.isoformat(),
                                "instrument_count": len(partition),
                            },
                        )
                    ]
                    values.extend(
                        (
                            result.event_identifier,
                            request.identifier,
                            ScreeningEventType.INSTRUMENT_RESULT,
                            result.completed_at,
                            result.to_dict(),
                        )
                        for result in pending_results
                    )
                    self.screening_store.append_many(tuple(values))
                    completed.update(
                        {
                            result.instrument_identifier: result
                            for result in pending_results
                        }
                    )
                    succeeded = True
                    break
                except Exception as error:
                    if isinstance(error, (KeyboardInterrupt, SystemExit)):
                        raise
                    last_error = error
                    failed_at = _aware(self.clock(), field_name="clock")
                    self.screening_store.append(
                        event_identifier=(
                            f"screening:{request.identifier}:partition:"
                            f"{partition_index}:attempt:{attempt}"
                        ),
                        cycle_identifier=request.identifier,
                        event_type=ScreeningEventType.PARTITION_ATTEMPT,
                        occurred_at=failed_at,
                        payload={
                            "partition_index": partition_index,
                            "attempt": attempt,
                            "status": "failed",
                            "started_at": attempt_started.isoformat(),
                            "completed_at": failed_at.isoformat(),
                            "instrument_count": len(partition),
                            "error": str(error)[:1000],
                        },
                    )
            if not succeeded:
                raise FullUniverseScreeningError(
                    f"partition {partition_index} failed after "
                    f"{request.maximum_partition_attempts} attempts: {last_error}"
                )

    @staticmethod
    def _validate_candidate(
        candidate: CandidateDecisionRecord,
        constituent: Version1UniverseConstituent,
        *,
        request: FullUniverseScreeningRequest,
        context: OpportunitySetContext,
    ) -> None:
        if candidate.as_of != request.as_of:
            raise ValueError("candidate as_of does not match screening cycle")
        if candidate.instrument.instrument_id != constituent.instrument.instrument_id:
            raise ValueError("candidate instrument does not match universe constituent")
        if candidate.instrument.symbol != constituent.instrument.symbol:
            raise ValueError("candidate symbol does not match universe constituent")
        if (
            candidate.instrument.security_master_snapshot_identifier
            != constituent.instrument.security_master_snapshot_identifier
        ):
            raise ValueError("candidate security-master snapshot lineage is invalid")
        if set(candidate.instrument.security_master_record_identifiers) != set(
            constituent.instrument.security_master_record_identifiers
        ):
            raise ValueError("candidate security-master record lineage is invalid")
        expected_cost = context.best_alternative().net_expected_return
        if abs(candidate.opportunity_cost_return - expected_cost) > 0.000001:
            raise ValueError(
                "candidate opportunity cost does not match the point-in-time context"
            )

    def _publish(
        self,
        *,
        request: FullUniverseScreeningRequest,
        catalog: SecurityMasterCatalog,
        master_snapshot: PointInTimeSecurityMasterSnapshot,
        universe: Version1UniverseSnapshot,
        context: OpportunitySetContext,
    ) -> FullUniverseScreeningRun:
        results = self.screening_store.instrument_results(request.identifier)
        by_instrument = {item.instrument_identifier: item for item in results}
        eligible_ids = {
            item.instrument.instrument_id for item in universe.constituents
        }
        if set(by_instrument) != eligible_ids:
            missing = sorted(eligible_ids - set(by_instrument))
            extra = sorted(set(by_instrument) - eligible_ids)
            raise FullUniverseScreeningError(
                "cycle cannot publish without exact eligible-universe coverage: "
                f"missing={len(missing)} extra={len(extra)}"
            )
        ordered_results = tuple(
            by_instrument[item.instrument.instrument_id]
            for item in universe.constituents
        )
        candidate_payloads = tuple(
            dict(item.candidate_payload)
            for item in ordered_results
            if item.disposition is ScreeningDisposition.CANDIDATE
            and item.candidate_payload is not None
        )
        candidates = tuple(
            _candidate_from_payload(payload) for payload in candidate_payloads
        )
        queue = self.opportunity_engine.build_queue(candidates, context)
        exclusions = tuple(
            {
                "instrument_identifier": item.instrument_identifier,
                "symbol": item.symbol,
                "reasons": list(item.reasons),
            }
            for item in ordered_results
            if item.disposition is ScreeningDisposition.EXCLUDED
        )
        published_at = _aware(self.clock(), field_name="clock")
        publication = FullUniverseScreeningPublication(
            identifier=f"publication:{request.identifier}",
            cycle_identifier=request.identifier,
            published_at=published_at,
            security_master_catalog_identifier=catalog.identifier,
            security_master_snapshot_identifier=master_snapshot.identifier,
            universe_snapshot_identifier=universe.identifier,
            opportunity_context_identifier=context.identifier,
            eligible_instrument_count=len(universe.constituents),
            screened_instrument_count=len(ordered_results),
            candidate_count=len(candidate_payloads),
            excluded_count=len(exclusions),
            candidate_payloads=candidate_payloads,
            exclusions=exclusions,
            opportunity_queue_payload=serialize_opportunity_queue(
                queue,
                occurred_at=request.as_of,
            ),
        )
        self.screening_store.append(
            event_identifier=f"screening:{request.identifier}:publication",
            cycle_identifier=request.identifier,
            event_type=ScreeningEventType.PUBLICATION,
            occurred_at=published_at,
            payload=publication.to_dict(),
        )
        self._record_completed_downstream(
            request=request,
            publication=publication,
            candidates=candidates,
            queue=queue,
        )
        return FullUniverseScreeningRun(
            publication=publication,
            universe=universe,
            candidates=candidates,
            opportunity_queue=queue,
        )

    def _record_completed_downstream(
        self,
        *,
        request: FullUniverseScreeningRequest,
        publication: FullUniverseScreeningPublication,
        candidates: tuple[CandidateDecisionRecord, ...],
        queue: OpportunityQueue,
    ) -> None:
        self.slo_store.append_cycle(
            FullUniverseCycleRecord(
                identifier=request.identifier,
                scheduled_for=request.scheduled_for,
                started_at=request.started_at,
                completed_at=publication.published_at,
                status=FullUniverseCycleStatus.COMPLETED,
                security_master_catalog_identifier=(
                    publication.security_master_catalog_identifier
                ),
                universe_snapshot_identifier=(
                    publication.universe_snapshot_identifier
                ),
                eligible_instrument_count=(
                    publication.eligible_instrument_count
                ),
                screened_instrument_count=(
                    publication.screened_instrument_count
                ),
                qualified_candidate_count=len(queue.ranked),
            )
        )
        if self.journal is not None:
            for candidate in candidates:
                self.journal.append_candidate(candidate)
            self.journal.append_opportunity_queue(
                queue,
                occurred_at=request.as_of,
            )

    def _record_cycle_failure(
        self,
        request: FullUniverseScreeningRequest,
        error: Exception,
    ) -> None:
        observed_failure = _aware(self.clock(), field_name="clock")
        failed_at = max(observed_failure, request.started_at)
        message = str(error).strip() or error.__class__.__name__
        attempt = len(
            self.screening_store.events(
                request.identifier,
                event_type=ScreeningEventType.CYCLE_FAILED,
            )
        ) + 1
        self.screening_store.append(
            event_identifier=(
                f"screening:{request.identifier}:failed:{attempt}"
            ),
            cycle_identifier=request.identifier,
            event_type=ScreeningEventType.CYCLE_FAILED,
            occurred_at=failed_at,
            payload={
                "cycle_identifier": request.identifier,
                "failed_at": failed_at.isoformat(),
                "error": message[:1000],
            },
        )
        self.slo_store.append_cycle(
            FullUniverseCycleRecord(
                identifier=f"{request.identifier}:failed:{attempt}",
                scheduled_for=request.scheduled_for,
                started_at=request.started_at,
                completed_at=failed_at,
                status=FullUniverseCycleStatus.FAILED,
                security_master_catalog_identifier=None,
                universe_snapshot_identifier=None,
                eligible_instrument_count=0,
                screened_instrument_count=0,
                qualified_candidate_count=0,
                error=message[:1000],
            )
        )


def candidate_from_payload(payload: Mapping[str, Any]) -> CandidateDecisionRecord:
    """Reconstruct a canonical candidate from persisted screening evidence."""

    return _candidate_from_payload(payload)


def _candidate_from_payload(payload: Mapping[str, Any]) -> CandidateDecisionRecord:
    instrument_payload = dict(payload["instrument"])
    scenario_payload = dict(payload["scenarios"])
    base = dict(scenario_payload["base"])
    bull = dict(scenario_payload["bull"])
    bear = dict(scenario_payload["bear"])
    quality_payload = dict(payload["evidence_quality"])
    instrument = CandidateInstrument(
        instrument_id=str(instrument_payload["instrument_id"]),
        symbol=str(instrument_payload["symbol"]),
        name=str(instrument_payload["name"]),
        asset_class=CandidateAssetClass(str(instrument_payload["asset_class"])),
        venue=str(instrument_payload["venue"]),
        country_code=str(instrument_payload["country_code"]),
        average_daily_dollar_volume=float(
            instrument_payload["average_daily_dollar_volume"]
        ),
        data_age_hours=float(instrument_payload["data_age_hours"]),
        analytical_coverage=float(instrument_payload["analytical_coverage"]),
        security_master_snapshot_identifier=str(
            instrument_payload["security_master_snapshot_identifier"]
        ),
        security_master_record_identifiers=tuple(
            str(item)
            for item in instrument_payload["security_master_record_identifiers"]
        ),
        is_us_treasury=bool(instrument_payload.get("is_us_treasury", False)),
        effective_duration_years=(
            None
            if instrument_payload.get("effective_duration_years") is None
            else float(instrument_payload["effective_duration_years"])
        ),
        instrument_type=str(instrument_payload.get("instrument_type", "other")),
        economic_exposure_class=(
            None
            if instrument_payload.get("economic_exposure_class") is None
            else CandidateAssetClass(
                str(instrument_payload["economic_exposure_class"])
            )
        ),
        leverage_multiplier=float(
            instrument_payload.get("leverage_multiplier", 1.0)
        ),
        uses_derivatives=bool(
            instrument_payload.get("uses_derivatives", False)
        ),
        replication_method=(
            None
            if instrument_payload.get("replication_method") is None
            else str(instrument_payload["replication_method"])
        ),
    )
    quality = EvidenceQuality(
        reliability=float(quality_payload["reliability"]),
        freshness=float(quality_payload["freshness"]),
        relevance=float(quality_payload["relevance"]),
        independence=float(quality_payload["independence"]),
        completeness=float(quality_payload["completeness"]),
        point_in_time_integrity=float(
            quality_payload["point_in_time_integrity"]
        ),
    )
    return CandidateDecisionRecord(
        identifier=str(payload["identifier"]),
        as_of=datetime.fromisoformat(str(payload["as_of"])),
        schema_version=str(payload["schema_version"]),
        instrument=instrument,
        current_price=float(payload["current_price"]),
        decision_horizon_days=int(payload["decision_horizon_days"]),
        base_case_return=float(base["return"]),
        bull_case_return=float(bull["return"]),
        bear_case_return=float(bear["return"]),
        base_case_probability=float(base["probability"]),
        bull_case_probability=float(bull["probability"]),
        bear_case_probability=float(bear["probability"]),
        estimated_fair_value=float(payload["estimated_fair_value"]),
        expected_upside=float(payload["expected_upside"]),
        expected_downside=float(payload["expected_downside"]),
        probability_of_success=float(payload["probability_of_success"]),
        primary_catalysts=tuple(str(item) for item in payload["primary_catalysts"]),
        key_risks=tuple(str(item) for item in payload["key_risks"]),
        critical_assumptions=tuple(
            str(item) for item in payload["critical_assumptions"]
        ),
        invalidation_conditions=tuple(
            str(item) for item in payload["invalidation_conditions"]
        ),
        supporting_evidence=tuple(
            str(item) for item in payload["supporting_evidence"]
        ),
        contradictory_evidence=tuple(
            str(item) for item in payload["contradictory_evidence"]
        ),
        evidence_quality=quality,
        liquidity_score=float(payload["liquidity_score"]),
        transaction_cost_bps=float(payload["transaction_cost_bps"]),
        slippage_bps=float(payload["slippage_bps"]),
        opportunity_cost_return=float(payload["opportunity_cost_return"]),
        expected_portfolio_contribution=float(
            payload["expected_portfolio_contribution"]
        ),
        current_portfolio_weight=float(payload["current_portfolio_weight"]),
        maximum_position_weight=float(payload["maximum_position_weight"]),
        monitoring_indicators=tuple(
            str(item) for item in payload["monitoring_indicators"]
        ),
        review_at=datetime.fromisoformat(str(payload["review_at"])),
        evidence_identifiers=tuple(
            str(item) for item in payload["evidence_identifiers"]
        ),
        model_versions=tuple(str(item) for item in payload["model_versions"]),
        payoff_distribution=tuple(
            PayoffDistributionPoint(
                label=str(item["label"]),
                total_return=float(item["total_return"]),
                probability=float(item["probability"]),
            )
            for item in payload.get("payoff_distribution", ())
        ),
    )


__all__ = [
    "CandidateScreeningDecision",
    "CandidateScreeningProvider",
    "FullUniverseScreeningError",
    "FullUniverseScreeningOrchestrator",
    "FullUniverseScreeningPublication",
    "FullUniverseScreeningRequest",
    "FullUniverseScreeningRun",
    "InstrumentScreeningResult",
    "SQLiteFullUniverseScreeningStore",
    "ScreeningDisposition",
    "ScreeningEvent",
    "ScreeningEventType",
    "UniverseMetricsProvider",
]
