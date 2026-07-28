"""Point-in-time return attribution for universal governed markets.

The canonical evaluator already owns selection, sizing, timing, implementation
cost, alternative comparison, and process quality.  This module adds the missing
multi-asset decomposition: local asset return, currency translation, their
interaction, and net base-currency portfolio contribution.  It never rewrites the
original decision snapshot or changes an investment action.
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
from evaluation.point_in_time import (
    AlternativeRealizedReturn,
    DecisionEvidenceSnapshot,
    PointInTimeDecisionEvaluation,
    PointInTimeDecisionEvaluator,
    RealizedDecisionOutcome,
)
from governance import EXPANSION_ASSET_CLASSES


class MultiAssetEvaluationError(RuntimeError):
    """Raised when expanded-market outcome evidence is unsafe or inconsistent."""


class MultiAssetEvaluationIntegrityError(MultiAssetEvaluationError):
    """Raised when append-only multi-asset evaluation history is invalid."""


class MultiAssetEvaluationEventType(str, Enum):
    OBSERVATION = "observation"
    ATTRIBUTION = "attribution"
    CORE_EVALUATION = "core_evaluation"
    THESIS_ASSESSMENT = "thesis_assessment"


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
    return round(normalized, 12)


def _currency(value: object, *, field_name: str) -> str:
    normalized = _text(value, field_name=field_name).upper()
    if not 3 <= len(normalized) <= 12:
        raise ValueError(f"{field_name} must be a canonical currency or asset code")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class MultiAssetReturnObservation:
    """Immutable decision, implementation, and horizon prices with FX lineage."""

    identifier: str
    snapshot_identifier: str
    decision_identifier: str
    thesis_identifier: str
    instrument_identifier: str
    symbol: str
    asset_class: CandidateAssetClass
    approval_identifier: str
    evaluation_model_version: str
    base_currency: str
    price_currency: str
    decision_at: datetime
    implemented_at: datetime
    horizon_ended_at: datetime
    observed_at: datetime
    knowledge_cutoff: datetime
    decision_local_price: float
    implementation_local_price: float
    horizon_local_price: float
    decision_fx_to_base: float
    implementation_fx_to_base: float
    horizon_fx_to_base: float
    implementation_cost_return: float
    source_identifiers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    quote_source_identifiers: tuple[str, ...]
    fx_source_identifiers: tuple[str, ...]
    schema_version: str = "multi-asset-return-observation.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "snapshot_identifier",
            "decision_identifier",
            "thesis_identifier",
            "instrument_identifier",
            "approval_identifier",
            "evaluation_model_version",
            "schema_version",
        ):
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
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        if self.asset_class not in EXPANSION_ASSET_CLASSES:
            raise ValueError(
                "multi-asset attribution is limited to classified governed non-core markets"
            )
        object.__setattr__(
            self,
            "base_currency",
            _currency(self.base_currency, field_name="base_currency"),
        )
        object.__setattr__(
            self,
            "price_currency",
            _currency(self.price_currency, field_name="price_currency"),
        )
        for field_name in (
            "decision_at",
            "implemented_at",
            "horizon_ended_at",
            "observed_at",
            "knowledge_cutoff",
        ):
            _aware(getattr(self, field_name), field_name=field_name)
        if self.implemented_at < self.decision_at:
            raise ValueError("implemented_at cannot predate decision_at")
        if self.horizon_ended_at <= self.implemented_at:
            raise ValueError("horizon_ended_at must follow implementation")
        if self.observed_at < self.horizon_ended_at:
            raise ValueError("observed_at cannot predate the realized horizon")
        if self.knowledge_cutoff < self.observed_at:
            raise ValueError("knowledge_cutoff cannot predate observed_at")
        for field_name in (
            "decision_local_price",
            "implementation_local_price",
            "horizon_local_price",
            "decision_fx_to_base",
            "implementation_fx_to_base",
            "horizon_fx_to_base",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(
                    getattr(self, field_name),
                    field_name=field_name,
                    minimum=0.000000000001,
                ),
            )
        object.__setattr__(
            self,
            "implementation_cost_return",
            _number(
                self.implementation_cost_return,
                field_name="implementation_cost_return",
                minimum=0.0,
            ),
        )
        for field_name, minimum in (
            ("source_identifiers", 1),
            ("evidence_identifiers", 1),
            ("quote_source_identifiers", 2),
            ("fx_source_identifiers", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                _texts(getattr(self, field_name), field_name=field_name, minimum=minimum),
            )
        if self.price_currency == self.base_currency:
            rates = (
                self.decision_fx_to_base,
                self.implementation_fx_to_base,
                self.horizon_fx_to_base,
            )
            if any(abs(item - 1.0) > 0.000000000001 for item in rates):
                raise ValueError(
                    "base-currency observations must use FX rates of 1.0"
                )
        elif len(self.fx_source_identifiers) < 3:
            raise ValueError(
                "non-base-currency attribution requires decision, implementation, and horizon FX sources"
            )

    @staticmethod
    def _return(start: float, end: float) -> float:
        return round((end / start) - 1.0, 12)

    @property
    def decision_local_return(self) -> float:
        return self._return(self.decision_local_price, self.horizon_local_price)

    @property
    def implementation_local_return(self) -> float:
        return self._return(
            self.implementation_local_price,
            self.horizon_local_price,
        )

    @property
    def decision_currency_return(self) -> float:
        return self._return(self.decision_fx_to_base, self.horizon_fx_to_base)

    @property
    def implementation_currency_return(self) -> float:
        return self._return(
            self.implementation_fx_to_base,
            self.horizon_fx_to_base,
        )

    @property
    def decision_interaction_return(self) -> float:
        return round(
            self.decision_local_return * self.decision_currency_return,
            12,
        )

    @property
    def implementation_interaction_return(self) -> float:
        return round(
            self.implementation_local_return * self.implementation_currency_return,
            12,
        )

    @property
    def decision_gross_base_return(self) -> float:
        return self._return(
            self.decision_local_price * self.decision_fx_to_base,
            self.horizon_local_price * self.horizon_fx_to_base,
        )

    @property
    def implementation_gross_base_return(self) -> float:
        return self._return(
            self.implementation_local_price * self.implementation_fx_to_base,
            self.horizon_local_price * self.horizon_fx_to_base,
        )

    @property
    def implementation_net_base_return(self) -> float:
        return round(
            self.implementation_gross_base_return
            - self.implementation_cost_return,
            12,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "snapshot_identifier": self.snapshot_identifier,
            "decision_identifier": self.decision_identifier,
            "thesis_identifier": self.thesis_identifier,
            "instrument_identifier": self.instrument_identifier,
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "approval_identifier": self.approval_identifier,
            "evaluation_model_version": self.evaluation_model_version,
            "base_currency": self.base_currency,
            "price_currency": self.price_currency,
            "decision_at": self.decision_at.isoformat(),
            "implemented_at": self.implemented_at.isoformat(),
            "horizon_ended_at": self.horizon_ended_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "decision_local_price": self.decision_local_price,
            "implementation_local_price": self.implementation_local_price,
            "horizon_local_price": self.horizon_local_price,
            "decision_fx_to_base": self.decision_fx_to_base,
            "implementation_fx_to_base": self.implementation_fx_to_base,
            "horizon_fx_to_base": self.horizon_fx_to_base,
            "implementation_cost_return": self.implementation_cost_return,
            "decision_local_return": self.decision_local_return,
            "implementation_local_return": self.implementation_local_return,
            "decision_currency_return": self.decision_currency_return,
            "implementation_currency_return": self.implementation_currency_return,
            "decision_interaction_return": self.decision_interaction_return,
            "implementation_interaction_return": self.implementation_interaction_return,
            "decision_gross_base_return": self.decision_gross_base_return,
            "implementation_gross_base_return": self.implementation_gross_base_return,
            "implementation_net_base_return": self.implementation_net_base_return,
            "source_identifiers": list(self.source_identifiers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "quote_source_identifiers": list(self.quote_source_identifiers),
            "fx_source_identifiers": list(self.fx_source_identifiers),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MultiAssetReturnObservation":
        return cls(
            identifier=str(value["identifier"]),
            snapshot_identifier=str(value["snapshot_identifier"]),
            decision_identifier=str(value["decision_identifier"]),
            thesis_identifier=str(value["thesis_identifier"]),
            instrument_identifier=str(value["instrument_identifier"]),
            symbol=str(value["symbol"]),
            asset_class=CandidateAssetClass(str(value["asset_class"])),
            approval_identifier=str(value["approval_identifier"]),
            evaluation_model_version=str(value["evaluation_model_version"]),
            base_currency=str(value["base_currency"]),
            price_currency=str(value["price_currency"]),
            decision_at=datetime.fromisoformat(str(value["decision_at"])),
            implemented_at=datetime.fromisoformat(str(value["implemented_at"])),
            horizon_ended_at=datetime.fromisoformat(str(value["horizon_ended_at"])),
            observed_at=datetime.fromisoformat(str(value["observed_at"])),
            knowledge_cutoff=datetime.fromisoformat(str(value["knowledge_cutoff"])),
            decision_local_price=float(value["decision_local_price"]),
            implementation_local_price=float(value["implementation_local_price"]),
            horizon_local_price=float(value["horizon_local_price"]),
            decision_fx_to_base=float(value["decision_fx_to_base"]),
            implementation_fx_to_base=float(value["implementation_fx_to_base"]),
            horizon_fx_to_base=float(value["horizon_fx_to_base"]),
            implementation_cost_return=float(value["implementation_cost_return"]),
            source_identifiers=tuple(str(item) for item in value["source_identifiers"]),
            evidence_identifiers=tuple(str(item) for item in value["evidence_identifiers"]),
            quote_source_identifiers=tuple(
                str(item) for item in value["quote_source_identifiers"]
            ),
            fx_source_identifiers=tuple(
                str(item) for item in value["fx_source_identifiers"]
            ),
            schema_version=str(
                value.get("schema_version", "multi-asset-return-observation.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class MultiAssetReturnAttribution:
    """Position return decomposition and portfolio-level contribution."""

    observation_identifier: str
    snapshot_identifier: str
    asset_class: CandidateAssetClass
    implemented_weight: float
    local_asset_return: float
    currency_return: float
    interaction_return: float
    gross_base_return: float
    implementation_cost_return: float
    net_base_return: float
    local_asset_contribution: float
    currency_contribution: float
    interaction_contribution: float
    implementation_cost_contribution: float
    net_portfolio_contribution: float
    schema_version: str = "multi-asset-return-attribution.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "observation_identifier",
            "snapshot_identifier",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.asset_class, CandidateAssetClass):
            raise TypeError("asset_class must be CandidateAssetClass")
        object.__setattr__(
            self,
            "implemented_weight",
            _number(
                self.implemented_weight,
                field_name="implemented_weight",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        for field_name in (
            "local_asset_return",
            "currency_return",
            "interaction_return",
            "gross_base_return",
            "implementation_cost_return",
            "net_base_return",
            "local_asset_contribution",
            "currency_contribution",
            "interaction_contribution",
            "implementation_cost_contribution",
            "net_portfolio_contribution",
        ):
            object.__setattr__(
                self,
                field_name,
                _number(getattr(self, field_name), field_name=field_name),
            )
        gross = self.local_asset_return + self.currency_return + self.interaction_return
        if abs(gross - self.gross_base_return) > 0.0000001:
            raise ValueError("local, currency, and interaction returns must reconcile")
        if abs(
            self.gross_base_return
            - self.implementation_cost_return
            - self.net_base_return
        ) > 0.0000001:
            raise ValueError("net base return must reconcile after implementation cost")
        contribution = (
            self.local_asset_contribution
            + self.currency_contribution
            + self.interaction_contribution
            + self.implementation_cost_contribution
        )
        if abs(contribution - self.net_portfolio_contribution) > 0.0000001:
            raise ValueError("portfolio contributions must reconcile")

    @classmethod
    def from_observation(
        cls,
        observation: MultiAssetReturnObservation,
        *,
        implemented_weight: float,
    ) -> "MultiAssetReturnAttribution":
        if not isinstance(observation, MultiAssetReturnObservation):
            raise TypeError("observation must be MultiAssetReturnObservation")
        weight = _number(
            implemented_weight,
            field_name="implemented_weight",
            minimum=0.0,
            maximum=1.0,
        )
        local = observation.implementation_local_return
        currency = observation.implementation_currency_return
        interaction = observation.implementation_interaction_return
        cost = observation.implementation_cost_return
        return cls(
            observation_identifier=observation.identifier,
            snapshot_identifier=observation.snapshot_identifier,
            asset_class=observation.asset_class,
            implemented_weight=weight,
            local_asset_return=local,
            currency_return=currency,
            interaction_return=interaction,
            gross_base_return=observation.implementation_gross_base_return,
            implementation_cost_return=cost,
            net_base_return=observation.implementation_net_base_return,
            local_asset_contribution=round(weight * local, 12),
            currency_contribution=round(weight * currency, 12),
            interaction_contribution=round(weight * interaction, 12),
            implementation_cost_contribution=round(-weight * cost, 12),
            net_portfolio_contribution=round(
                weight * observation.implementation_net_base_return,
                12,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            field_name: (
                getattr(self, field_name).value
                if field_name == "asset_class"
                else getattr(self, field_name)
            )
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class MultiAssetPointInTimeEvaluation:
    """Canonical core evaluation plus transparent multi-asset decomposition."""

    identifier: str
    evaluated_at: datetime
    observation: MultiAssetReturnObservation
    attribution: MultiAssetReturnAttribution
    core_evaluation: PointInTimeDecisionEvaluation
    schema_version: str = "multi-asset-point-in-time-evaluation.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, field_name="schema_version"),
        )
        _aware(self.evaluated_at, field_name="evaluated_at")
        if not isinstance(self.observation, MultiAssetReturnObservation):
            raise TypeError("observation must be MultiAssetReturnObservation")
        if not isinstance(self.attribution, MultiAssetReturnAttribution):
            raise TypeError("attribution must be MultiAssetReturnAttribution")
        if not isinstance(self.core_evaluation, PointInTimeDecisionEvaluation):
            raise TypeError("core_evaluation must be PointInTimeDecisionEvaluation")
        if self.observation.snapshot_identifier != self.core_evaluation.snapshot_identifier:
            raise ValueError("core and multi-asset evaluations must share a snapshot")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "observation": self.observation.to_dict(),
            "attribution": self.attribution.to_dict(),
            "core_evaluation": self.core_evaluation.to_dict(),
            "schema_version": self.schema_version,
        }


class MultiAssetPointInTimeEvaluator:
    """Join realized multi-asset facts to an immutable decision snapshot."""

    def __init__(self, core: PointInTimeDecisionEvaluator | None = None) -> None:
        self.core = core or PointInTimeDecisionEvaluator()

    def evaluate(
        self,
        snapshot: DecisionEvidenceSnapshot,
        observation: MultiAssetReturnObservation,
        *,
        cash_return: float,
        benchmark_return: float,
        passive_portfolio_return: float,
        alternative_returns: tuple[AlternativeRealizedReturn, ...],
    ) -> MultiAssetPointInTimeEvaluation:
        if not isinstance(snapshot, DecisionEvidenceSnapshot):
            raise TypeError("snapshot must be DecisionEvidenceSnapshot")
        if not isinstance(observation, MultiAssetReturnObservation):
            raise TypeError("observation must be MultiAssetReturnObservation")
        if observation.snapshot_identifier != snapshot.identifier:
            raise MultiAssetEvaluationError("observation does not match decision snapshot")
        if observation.decision_identifier != snapshot.decision_identifier:
            raise MultiAssetEvaluationError("observation does not match CIO decision")
        if observation.thesis_identifier != snapshot.thesis_identifier:
            raise MultiAssetEvaluationError("observation does not match living thesis")
        if observation.symbol != snapshot.symbol:
            raise MultiAssetEvaluationError("observation symbol does not match snapshot")
        if observation.decision_at != snapshot.decision_as_of:
            raise MultiAssetEvaluationError("observation decision timestamp does not match snapshot")
        cost_contribution = round(
            snapshot.implemented_position_weight
            * observation.implementation_cost_return,
            12,
        )
        realized = RealizedDecisionOutcome(
            snapshot_identifier=snapshot.identifier,
            horizon_ended_at=observation.horizon_ended_at,
            observed_at=observation.observed_at,
            decision_to_horizon_return=observation.decision_gross_base_return,
            implementation_to_horizon_return=(
                observation.implementation_gross_base_return
            ),
            actual_implementation_cost_return=cost_contribution,
            cash_return=cash_return,
            benchmark_return=benchmark_return,
            passive_portfolio_return=passive_portfolio_return,
            alternative_returns=alternative_returns,
            source_identifiers=tuple(
                dict.fromkeys(
                    observation.source_identifiers
                    + observation.quote_source_identifiers
                    + observation.fx_source_identifiers
                )
            ),
        )
        core_evaluation = self.core.evaluate(snapshot, realized)
        attribution = MultiAssetReturnAttribution.from_observation(
            observation,
            implemented_weight=snapshot.implemented_position_weight,
        )
        return MultiAssetPointInTimeEvaluation(
            identifier=f"multi-asset:{core_evaluation.identifier}",
            evaluated_at=observation.observed_at,
            observation=observation,
            attribution=attribution,
            core_evaluation=core_evaluation,
        )


class SQLiteMultiAssetEvaluationStore:
    """Append-only SHA-256 event chain for observations and attributions."""

    _TABLE = "multi_asset_evaluation_events"
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
                CREATE INDEX IF NOT EXISTS multi_asset_evaluation_lookup
                ON {self._TABLE}(aggregate_identifier, sequence);
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'multi-asset evaluation history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'multi-asset evaluation history is append-only'); END;
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

    def append(
        self,
        *,
        event_identifier: str,
        aggregate_identifier: str,
        event_type: MultiAssetEvaluationEventType,
        occurred_at: datetime,
        payload: Mapping[str, Any],
    ) -> int:
        event_id = _text(event_identifier, field_name="event_identifier")
        aggregate_id = _text(
            aggregate_identifier,
            field_name="aggregate_identifier",
        )
        timestamp = _aware(occurred_at, field_name="occurred_at").isoformat()
        payload_json = _canonical_json(payload)
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
                    raise MultiAssetEvaluationError(
                        "evaluation event identifier already exists with different content"
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
                aggregate_id,
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
                    aggregate_id,
                    event_type.value,
                    timestamp,
                    payload_json,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def events(self, aggregate_identifier: str) -> tuple[dict[str, Any], ...]:
        aggregate = _text(
            aggregate_identifier,
            field_name="aggregate_identifier",
        )
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT sequence,event_identifier,event_type,occurred_at,payload_json "
                f"FROM {self._TABLE} WHERE aggregate_identifier=? ORDER BY sequence",
                (aggregate,),
            ).fetchall()
        return tuple(
            {
                "sequence": int(row[0]),
                "event_identifier": str(row[1]),
                "event_type": str(row[2]),
                "occurred_at": str(row[3]),
                "payload": json.loads(str(row[4])),
            }
            for row in rows
        )

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, 1):
            if int(row[0]) != expected or str(row[6]) != previous:
                raise MultiAssetEvaluationIntegrityError(
                    "multi-asset evaluation chain is not contiguous"
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
                raise MultiAssetEvaluationIntegrityError(
                    "multi-asset evaluation content hash is invalid"
                )
            previous = actual
        return True


__all__ = [
    "MultiAssetEvaluationError",
    "MultiAssetEvaluationEventType",
    "MultiAssetEvaluationIntegrityError",
    "MultiAssetPointInTimeEvaluation",
    "MultiAssetPointInTimeEvaluator",
    "MultiAssetReturnAttribution",
    "MultiAssetReturnObservation",
    "SQLiteMultiAssetEvaluationStore",
]
