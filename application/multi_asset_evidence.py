"""Asset-specific evidence contracts for crypto, FX, and global markets.

The canonical candidate record remains the comparable decision schema. This
module supplies the additional valuation, return-driver, liquidity, cost, and
originating-fact evidence required before an expanded-market candidate may enter
the scheduled CIO context.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from cio import CandidateAssetClass
from governance import EXPANSION_ASSET_CLASSES


class MultiAssetEvidenceError(RuntimeError):
    """Raised when expanded-market evidence is incomplete or inconsistent."""


class MultiAssetEvidenceIntegrityError(MultiAssetEvidenceError):
    """Raised when the append-only evidence chain is invalid."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


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


def _number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return round(normalized, 12)


def _metrics(value: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(value, tuple):
        raise TypeError("metrics must be a tuple")
    normalized = tuple(
        (_text(name, field_name="metric name"), _number(number, field_name=name))
        for name, number in value
    )
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError("metric names must be unique")
    return normalized


def _versions(value: object, *, field_name: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        (
            _text(name, field_name=f"{field_name} name"),
            _text(version, field_name=f"{field_name} version"),
        )
        for name, version in value
    )
    names = tuple(name for name, _ in normalized)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class OriginatingFactObservation:
    """One downstream observation linked to its single originating economic fact."""

    observation_identifier: str
    originating_fact_identifier: str
    source_family: str
    source_identifier: str
    observed_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "observation_identifier",
            "originating_fact_identifier",
            "source_family",
            "source_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        _aware(self.observed_at, field_name="observed_at")
        _aware(self.available_at, field_name="available_at")
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot predate observed_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_identifier": self.observation_identifier,
            "originating_fact_identifier": self.originating_fact_identifier,
            "source_family": self.source_family,
            "source_identifier": self.source_identifier,
            "observed_at": self.observed_at.isoformat(),
            "available_at": self.available_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OriginatingFactObservation":
        return cls(
            observation_identifier=str(value["observation_identifier"]),
            originating_fact_identifier=str(value["originating_fact_identifier"]),
            source_family=str(value["source_family"]),
            source_identifier=str(value["source_identifier"]),
            observed_at=datetime.fromisoformat(str(value["observed_at"])),
            available_at=datetime.fromisoformat(str(value["available_at"])),
        )


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True, slots=True)
class AssetMetricDefinition:
    name: str
    unit: str
    direction: MetricDirection
    applicable_horizon: str

    def __post_init__(self) -> None:
        for field_name in ("name", "unit", "applicable_horizon"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.direction, MetricDirection):
            raise TypeError("direction must be MetricDirection")


@dataclass(frozen=True, slots=True)
class TypedAssetMetric:
    definition: AssetMetricDefinition
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.definition, AssetMetricDefinition):
            raise TypeError("definition must be AssetMetricDefinition")
        object.__setattr__(
            self,
            "value",
            _number(self.value, field_name=self.definition.name),
        )


_METRIC_DEFINITIONS: dict[str, AssetMetricDefinition] = {
    "valuation_signal": AssetMetricDefinition("valuation_signal", "standardized_score", MetricDirection.HIGHER_IS_BETTER, "decision_horizon"),
    "supply_demand_signal": AssetMetricDefinition("supply_demand_signal", "standardized_score", MetricDirection.HIGHER_IS_BETTER, "decision_horizon"),
    "liquidity_score": AssetMetricDefinition("liquidity_score", "ratio", MetricDirection.HIGHER_IS_BETTER, "current"),
    "implementation_cost_return": AssetMetricDefinition("implementation_cost_return", "return_fraction", MetricDirection.LOWER_IS_BETTER, "implementation"),
    "rate_differential": AssetMetricDefinition("rate_differential", "annual_return_fraction", MetricDirection.CONTEXTUAL, "annual"),
    "fundamental_quality": AssetMetricDefinition("fundamental_quality", "standardized_score", MetricDirection.HIGHER_IS_BETTER, "decision_horizon"),
    "currency_exposure": AssetMetricDefinition("currency_exposure", "base_currency_fraction", MetricDirection.CONTEXTUAL, "decision_horizon"),
    "yield_to_worst": AssetMetricDefinition("yield_to_worst", "annual_return_fraction", MetricDirection.HIGHER_IS_BETTER, "annual"),
    "duration": AssetMetricDefinition("duration", "years", MetricDirection.CONTEXTUAL, "current"),
    "credit_spread": AssetMetricDefinition("credit_spread", "basis_points", MetricDirection.CONTEXTUAL, "current"),
    "curve_carry": AssetMetricDefinition("curve_carry", "annual_return_fraction", MetricDirection.HIGHER_IS_BETTER, "annual"),
    "rate_sensitivity": AssetMetricDefinition("rate_sensitivity", "standardized_beta", MetricDirection.CONTEXTUAL, "decision_horizon"),
    "underlying_return_signal": AssetMetricDefinition("underlying_return_signal", "standardized_score", MetricDirection.HIGHER_IS_BETTER, "decision_horizon"),
    "margin_requirement": AssetMetricDefinition("margin_requirement", "portfolio_fraction", MetricDirection.LOWER_IS_BETTER, "implementation"),
    "implied_volatility": AssetMetricDefinition("implied_volatility", "annualized_volatility", MetricDirection.CONTEXTUAL, "contract_horizon"),
    "delta": AssetMetricDefinition("delta", "option_delta", MetricDirection.CONTEXTUAL, "current"),
    "gamma": AssetMetricDefinition("gamma", "option_gamma", MetricDirection.CONTEXTUAL, "current"),
    "theta": AssetMetricDefinition("theta", "return_per_day", MetricDirection.CONTEXTUAL, "daily"),
    "maximum_loss": AssetMetricDefinition("maximum_loss", "portfolio_fraction", MetricDirection.LOWER_IS_BETTER, "contract_horizon"),
    "implied_realized_spread": AssetMetricDefinition("implied_realized_spread", "annualized_volatility", MetricDirection.CONTEXTUAL, "contract_horizon"),
    "term_structure": AssetMetricDefinition("term_structure", "standardized_slope", MetricDirection.CONTEXTUAL, "contract_horizon"),
    "strategy_exposure": AssetMetricDefinition("strategy_exposure", "standardized_score", MetricDirection.CONTEXTUAL, "decision_horizon"),
    "expected_return_impact": AssetMetricDefinition("expected_return_impact", "return_fraction", MetricDirection.HIGHER_IS_BETTER, "decision_horizon"),
}


def metric_definition(name: str) -> AssetMetricDefinition:
    resolved = _text(name, field_name="metric name")
    return _METRIC_DEFINITIONS.get(
        resolved,
        AssetMetricDefinition(
            resolved,
            "provider_native_unit",
            MetricDirection.CONTEXTUAL,
            "decision_horizon",
        ),
    )


_REQUIRED_METRICS: dict[CandidateAssetClass, frozenset[str]] = {
    CandidateAssetClass.CRYPTO: frozenset(
        {
            "valuation_signal",
            "supply_demand_signal",
            "liquidity_score",
            "implementation_cost_return",
        }
    ),
    CandidateAssetClass.FX: frozenset(
        {
            "rate_differential",
            "valuation_signal",
            "liquidity_score",
            "implementation_cost_return",
        }
    ),
    CandidateAssetClass.INTERNATIONAL_EQUITY: frozenset(
        {
            "fundamental_quality",
            "valuation_signal",
            "currency_exposure",
            "liquidity_score",
            "implementation_cost_return",
        }
    ),
    CandidateAssetClass.FIXED_INCOME: frozenset({
        "yield_to_worst", "duration", "credit_spread",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.COMMODITY: frozenset({
        "valuation_signal", "supply_demand_signal", "curve_carry",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.REAL_ESTATE: frozenset({
        "fundamental_quality", "valuation_signal", "rate_sensitivity",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.FUTURE: frozenset({
        "underlying_return_signal", "curve_carry", "margin_requirement",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.OPTION: frozenset({
        "implied_volatility", "delta", "gamma", "theta", "maximum_loss",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.VOLATILITY: frozenset({
        "implied_realized_spread", "term_structure", "curve_carry",
        "liquidity_score", "implementation_cost_return",
    }),
    CandidateAssetClass.ALTERNATIVE: frozenset({
        "valuation_signal", "strategy_exposure", "liquidity_score",
        "implementation_cost_return",
    }),
}


@dataclass(frozen=True, slots=True)
class AssetSpecificEvidencePacket:
    """Complete point-in-time asset-specific evidence for one screened candidate."""

    identifier: str
    screening_cycle_identifier: str
    candidate_identifier: str
    instrument_identifier: str
    asset_class: CandidateAssetClass
    asset_class_approval_identifier: str
    as_of: datetime
    knowledge_cutoff: datetime
    fresh_until: datetime
    metrics: tuple[tuple[str, float], ...]
    valuation_basis: tuple[str, ...]
    return_drivers: tuple[str, ...]
    risks: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    observations: tuple[OriginatingFactObservation, ...]
    provider_certification_identifiers: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    model_versions: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
    schema_version: str = "asset-specific-evidence-packet.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "screening_cycle_identifier",
            "candidate_identifier",
            "instrument_identifier",
            "asset_class_approval_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.asset_class not in EXPANSION_ASSET_CLASSES:
            raise ValueError("asset-specific packet is only for classified governed non-core markets")
        for field_name in ("as_of", "knowledge_cutoff", "fresh_until"):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.knowledge_cutoff < self.as_of:
            raise ValueError("knowledge_cutoff cannot predate as_of")
        if self.fresh_until < self.knowledge_cutoff:
            raise ValueError("asset-specific evidence is stale at the knowledge cutoff")
        object.__setattr__(self, "metrics", _metrics(self.metrics))
        metric_names = {name for name, _ in self.metrics}
        missing = sorted(_REQUIRED_METRICS[self.asset_class] - metric_names)
        if missing:
            raise ValueError(
                f"{self.asset_class.value} evidence is missing required metrics: {missing}"
            )
        for field_name, minimum in (
            ("valuation_basis", 1),
            ("return_drivers", 1),
            ("risks", 1),
            ("invalidation_conditions", 1),
            ("provider_certification_identifiers", 1),
            ("limitations", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, OriginatingFactObservation) for item in self.observations
        ):
            raise TypeError(
                "observations must contain OriginatingFactObservation values"
            )
        if not self.observations:
            raise ValueError("asset-specific evidence requires originating facts")
        observation_ids = tuple(item.observation_identifier for item in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation identifiers must be unique")
        for item in self.observations:
            if item.available_at > self.knowledge_cutoff:
                raise ValueError(
                    "asset-specific observation was unavailable at the knowledge cutoff"
                )
        object.__setattr__(
            self,
            "source_versions",
            _versions(self.source_versions, field_name="source_versions"),
        )
        object.__setattr__(
            self,
            "model_versions",
            _versions(self.model_versions, field_name="model_versions"),
        )
        if not self.model_versions:
            raise ValueError("asset-specific evidence requires model versions")

    @property
    def typed_metrics(self) -> tuple[TypedAssetMetric, ...]:
        return tuple(
            TypedAssetMetric(metric_definition(name), value)
            for name, value in self.metrics
        )

    @property
    def originating_fact_identifiers(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(item.originating_fact_identifier for item in self.observations)
        )

    @property
    def independent_origin_count(self) -> int:
        return len(self.originating_fact_identifiers)

    @property
    def evidence_identifiers(self) -> tuple[str, ...]:
        return tuple(item.observation_identifier for item in self.observations)

    def require_match(
        self,
        *,
        screening_cycle_identifier: str,
        candidate_identifier: str,
        instrument_identifier: str,
        asset_class: CandidateAssetClass,
        as_of: datetime,
        knowledge_cutoff: datetime,
    ) -> None:
        expected = {
            "screening_cycle_identifier": _text(
                screening_cycle_identifier,
                field_name="screening_cycle_identifier",
            ),
            "candidate_identifier": _text(
                candidate_identifier,
                field_name="candidate_identifier",
            ),
            "instrument_identifier": _text(
                instrument_identifier,
                field_name="instrument_identifier",
            ),
        }
        for field_name, value in expected.items():
            if getattr(self, field_name) != value:
                raise MultiAssetEvidenceError(
                    f"asset-specific evidence {field_name} does not match screening"
                )
        if self.asset_class is not asset_class:
            raise MultiAssetEvidenceError(
                "asset-specific evidence asset class does not match candidate"
            )
        if self.as_of != _aware(as_of, field_name="as_of"):
            raise MultiAssetEvidenceError(
                "asset-specific evidence timestamp does not match candidate"
            )
        if self.knowledge_cutoff != _aware(
            knowledge_cutoff,
            field_name="knowledge_cutoff",
        ):
            raise MultiAssetEvidenceError(
                "asset-specific evidence cutoff does not match production context"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "screening_cycle_identifier": self.screening_cycle_identifier,
            "candidate_identifier": self.candidate_identifier,
            "instrument_identifier": self.instrument_identifier,
            "asset_class": self.asset_class.value,
            "asset_class_approval_identifier": self.asset_class_approval_identifier,
            "as_of": self.as_of.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "fresh_until": self.fresh_until.isoformat(),
            "metrics": [list(item) for item in self.metrics],
            "valuation_basis": list(self.valuation_basis),
            "return_drivers": list(self.return_drivers),
            "risks": list(self.risks),
            "invalidation_conditions": list(self.invalidation_conditions),
            "observations": [item.to_dict() for item in self.observations],
            "originating_fact_identifiers": list(
                self.originating_fact_identifiers
            ),
            "provider_certification_identifiers": list(
                self.provider_certification_identifiers
            ),
            "source_versions": [list(item) for item in self.source_versions],
            "model_versions": [list(item) for item in self.model_versions],
            "limitations": list(self.limitations),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssetSpecificEvidencePacket":
        return cls(
            identifier=str(value["identifier"]),
            screening_cycle_identifier=str(value["screening_cycle_identifier"]),
            candidate_identifier=str(value["candidate_identifier"]),
            instrument_identifier=str(value["instrument_identifier"]),
            asset_class=CandidateAssetClass(str(value["asset_class"])),
            asset_class_approval_identifier=str(
                value["asset_class_approval_identifier"]
            ),
            as_of=datetime.fromisoformat(str(value["as_of"])),
            knowledge_cutoff=datetime.fromisoformat(str(value["knowledge_cutoff"])),
            fresh_until=datetime.fromisoformat(str(value["fresh_until"])),
            metrics=tuple((str(name), float(number)) for name, number in value["metrics"]),
            valuation_basis=tuple(str(item) for item in value["valuation_basis"]),
            return_drivers=tuple(str(item) for item in value["return_drivers"]),
            risks=tuple(str(item) for item in value["risks"]),
            invalidation_conditions=tuple(
                str(item) for item in value["invalidation_conditions"]
            ),
            observations=tuple(
                OriginatingFactObservation.from_dict(item)
                for item in value["observations"]
            ),
            provider_certification_identifiers=tuple(
                str(item) for item in value["provider_certification_identifiers"]
            ),
            source_versions=tuple(
                (str(name), str(version))
                for name, version in value.get("source_versions", ())
            ),
            model_versions=tuple(
                (str(name), str(version))
                for name, version in value["model_versions"]
            ),
            limitations=tuple(str(item) for item in value["limitations"]),
            schema_version=str(
                value.get("schema_version", "asset-specific-evidence-packet.v1")
            ),
        )


class SQLiteAssetSpecificEvidenceStore:
    """Append-only hash-chained authority for expanded-market evidence packets."""

    _TABLE = "asset_specific_evidence_packets"
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
                    event_identifier TEXT NOT NULL UNIQUE,
                    screening_cycle_identifier TEXT NOT NULL,
                    candidate_identifier TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS asset_specific_cycle_lookup
                ON {self._TABLE} (screening_cycle_identifier, as_of, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'asset-specific evidence is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'asset-specific evidence is append-only'); END;
                """
            )

    @classmethod
    def _hash(
        cls,
        *,
        sequence: int,
        event_identifier: str,
        screening_cycle_identifier: str,
        candidate_identifier: str,
        as_of: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        raw = "|".join(
            (
                str(sequence),
                event_identifier,
                screening_cycle_identifier,
                candidate_identifier,
                as_of,
                payload_json,
                previous_hash,
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def append(self, packet: AssetSpecificEvidencePacket) -> int:
        if not isinstance(packet, AssetSpecificEvidencePacket):
            raise TypeError("packet must be AssetSpecificEvidencePacket")
        self.verify_integrity()
        payload_json = _canonical_json(packet.to_dict())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence, payload_json FROM {self._TABLE} "
                "WHERE event_identifier = ?",
                (packet.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload_json:
                    raise MultiAssetEvidenceError(
                        "asset-specific packet identifier has conflicting content"
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
            as_of = packet.as_of.isoformat()
            content_hash = self._hash(
                sequence=sequence,
                event_identifier=packet.identifier,
                screening_cycle_identifier=packet.screening_cycle_identifier,
                candidate_identifier=packet.candidate_identifier,
                as_of=as_of,
                payload_json=payload_json,
                previous_hash=previous_hash,
            )
            connection.execute(
                f"""
                INSERT INTO {self._TABLE} (
                    sequence, event_identifier, screening_cycle_identifier,
                    candidate_identifier, as_of, payload_json, previous_hash,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence,
                    packet.identifier,
                    packet.screening_cycle_identifier,
                    packet.candidate_identifier,
                    as_of,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
        return sequence

    def packets_for_cycle(
        self,
        screening_cycle_identifier: str,
        *,
        as_of: datetime,
    ) -> tuple[AssetSpecificEvidencePacket, ...]:
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
            AssetSpecificEvidencePacket.from_dict(
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
                raise MultiAssetEvidenceIntegrityError(
                    "asset-specific evidence sequence is not contiguous"
                )
            if str(row["previous_hash"]) != previous_hash:
                raise MultiAssetEvidenceIntegrityError(
                    "asset-specific evidence previous hash is invalid"
                )
            expected_hash = self._hash(
                sequence=expected,
                event_identifier=str(row["event_identifier"]),
                screening_cycle_identifier=str(
                    row["screening_cycle_identifier"]
                ),
                candidate_identifier=str(row["candidate_identifier"]),
                as_of=str(row["as_of"]),
                payload_json=str(row["payload_json"]),
                previous_hash=previous_hash,
            )
            if str(row["content_hash"]) != expected_hash:
                raise MultiAssetEvidenceIntegrityError(
                    "asset-specific evidence content hash is invalid"
                )
            previous_hash = expected_hash
        return True


__all__ = [
    "AssetMetricDefinition",
    "AssetSpecificEvidencePacket",
    "MetricDirection",
    "MultiAssetEvidenceError",
    "MultiAssetEvidenceIntegrityError",
    "OriginatingFactObservation",
    "SQLiteAssetSpecificEvidenceStore",
    "TypedAssetMetric",
    "metric_definition",
]
