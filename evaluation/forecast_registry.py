"""Append-only claim-level forecast registry.

Every material prediction receives fixed resolution rules, an evidence cutoff, a model
version, and a base rate. Forecasts and revisions are separate immutable records;
poor outcomes cannot be deleted or overwritten.
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


class ForecastClass(str, Enum):
    MACRO_RELEASE = "macroeconomic_release"
    INFLATION = "inflation"
    POLICY_RATE = "policy_rate"
    EARNINGS_MARGIN = "earnings_and_margin"
    CREDIT_SPREAD = "credit_spread"
    VOLATILITY = "volatility"
    REGIME_TRANSITION = "regime_transition"
    CAPITAL_FLOW = "capital_flow_persistence"
    RELATIVE_PERFORMANCE = "relative_asset_performance"
    CATALYST = "catalyst"
    THESIS_MILESTONE = "thesis_milestone"
    DRAWDOWN = "drawdown_or_downside"


class ForecastDirection(str, Enum):
    ABOVE = "above"
    BELOW = "below"
    BETWEEN = "between"
    OCCURS = "occurs"
    DOES_NOT_OCCUR = "does_not_occur"


class ForecastStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    identifier: str
    claim: str
    forecast_class: ForecastClass
    target_variable: str
    direction: ForecastDirection
    range_low: float | None
    range_high: float | None
    probability: float
    created_at: datetime
    horizon_end: datetime
    resolution_date: datetime
    resolution_source: str
    resolution_rule: str
    evidence_cutoff: datetime
    model_version: str
    engine_identifier: str
    base_rate: float
    parent_identifier: str | None = None
    status: ForecastStatus = ForecastStatus.OPEN
    schema_version: str = "forecast-record.v1"

    def __post_init__(self) -> None:
        for name in (
            "identifier", "claim", "target_variable", "resolution_source",
            "resolution_rule", "model_version", "engine_identifier",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not isinstance(self.forecast_class, ForecastClass):
            raise TypeError("forecast_class must be ForecastClass")
        if not isinstance(self.direction, ForecastDirection):
            raise TypeError("direction must be ForecastDirection")
        if not isinstance(self.status, ForecastStatus):
            raise TypeError("status must be ForecastStatus")
        for name in ("created_at", "horizon_end", "resolution_date", "evidence_cutoff"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.evidence_cutoff > self.created_at:
            raise ValueError("evidence cutoff cannot follow forecast creation")
        if self.created_at >= self.resolution_date:
            raise ValueError("resolution date must follow forecast creation")
        if self.horizon_end > self.resolution_date:
            raise ValueError("horizon end cannot follow resolution date")
        for name in ("probability", "base_rate"):
            value = float(getattr(self, name))
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
        if self.direction is ForecastDirection.BETWEEN:
            if self.range_low is None or self.range_high is None:
                raise ValueError("between forecasts require a range")
            if float(self.range_low) > float(self.range_high):
                raise ValueError("forecast range must be ordered")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "claim": self.claim,
            "forecast_class": self.forecast_class.value,
            "target_variable": self.target_variable,
            "direction": self.direction.value,
            "range_low": self.range_low,
            "range_high": self.range_high,
            "probability": float(self.probability),
            "created_at": self.created_at.isoformat(),
            "horizon_end": self.horizon_end.isoformat(),
            "resolution_date": self.resolution_date.isoformat(),
            "resolution_source": self.resolution_source,
            "resolution_rule": self.resolution_rule,
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "model_version": self.model_version,
            "engine_identifier": self.engine_identifier,
            "base_rate": float(self.base_rate),
            "parent_identifier": self.parent_identifier,
            "status": self.status.value,
            "schema_version": self.schema_version,
            "authorizes_policy_change": False,
            "authorizes_portfolio_change": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ForecastRecord":
        return cls(
            identifier=str(payload["identifier"]),
            claim=str(payload["claim"]),
            forecast_class=ForecastClass(str(payload["forecast_class"])),
            target_variable=str(payload["target_variable"]),
            direction=ForecastDirection(str(payload["direction"])),
            range_low=None if payload.get("range_low") is None else float(payload["range_low"]),
            range_high=None if payload.get("range_high") is None else float(payload["range_high"]),
            probability=float(payload["probability"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            horizon_end=datetime.fromisoformat(str(payload["horizon_end"])),
            resolution_date=datetime.fromisoformat(str(payload["resolution_date"])),
            resolution_source=str(payload["resolution_source"]),
            resolution_rule=str(payload["resolution_rule"]),
            evidence_cutoff=datetime.fromisoformat(str(payload["evidence_cutoff"])),
            model_version=str(payload["model_version"]),
            engine_identifier=str(payload["engine_identifier"]),
            base_rate=float(payload["base_rate"]),
            parent_identifier=None if payload.get("parent_identifier") is None else str(payload["parent_identifier"]),
            status=ForecastStatus(str(payload.get("status", ForecastStatus.OPEN.value))),
            schema_version=str(payload.get("schema_version", "forecast-record.v1")),
        )


class ForecastRegistryIntegrityError(RuntimeError):
    pass


class SQLiteForecastRegistry:
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
                """
                CREATE TABLE IF NOT EXISTS forecast_registry (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    parent_identifier TEXT,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS forecast_registry_no_update
                BEFORE UPDATE ON forecast_registry
                BEGIN SELECT RAISE(ABORT, 'forecast registry is append only'); END;
                CREATE TRIGGER IF NOT EXISTS forecast_registry_no_delete
                BEFORE DELETE ON forecast_registry
                BEGIN SELECT RAISE(ABORT, 'forecast registry is append only'); END;
                """
            )

    @staticmethod
    def _hash(previous_hash: str | None, payload_json: str) -> str:
        return hashlib.sha256(((previous_hash or "") + "\n" + payload_json).encode()).hexdigest()

    def append(self, record: ForecastRecord) -> str:
        payload_json = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._connect() as connection:
            if record.parent_identifier is not None:
                parent = connection.execute(
                    "SELECT payload_json FROM forecast_registry WHERE identifier = ?",
                    (record.parent_identifier,),
                ).fetchone()
                if parent is None:
                    raise ForecastRegistryIntegrityError("forecast revision parent is missing")
                parent_record = ForecastRecord.from_dict(json.loads(str(parent[0])))
                fixed_fields = (
                    "target_variable", "resolution_date", "resolution_source",
                    "resolution_rule", "forecast_class",
                )
                if any(getattr(parent_record, name) != getattr(record, name) for name in fixed_fields):
                    raise ForecastRegistryIntegrityError("forecast revisions cannot change resolution rules")
            existing = connection.execute(
                "SELECT payload_json,content_hash FROM forecast_registry WHERE identifier = ?",
                (record.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) == payload_json:
                    return str(existing[1])
                raise ForecastRegistryIntegrityError("conflicting forecast identifier")
            prior = connection.execute(
                "SELECT content_hash FROM forecast_registry ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = str(prior[0]) if prior is not None else None
            content_hash = self._hash(previous_hash, payload_json)
            connection.execute(
                "INSERT INTO forecast_registry(identifier,parent_identifier,payload_json,previous_hash,content_hash) VALUES(?,?,?,?,?)",
                (record.identifier, record.parent_identifier, payload_json, previous_hash, content_hash),
            )
        return content_hash

    def records(self) -> tuple[ForecastRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload_json FROM forecast_registry ORDER BY sequence").fetchall()
        return tuple(ForecastRecord.from_dict(json.loads(str(row[0]))) for row in rows)

    def verify(self) -> None:
        previous_hash: str | None = None
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json,previous_hash,content_hash FROM forecast_registry ORDER BY sequence"
            ).fetchall()
        for row in rows:
            if row["previous_hash"] != previous_hash:
                raise ForecastRegistryIntegrityError("forecast previous hash mismatch")
            expected = self._hash(previous_hash, str(row["payload_json"]))
            if row["content_hash"] != expected:
                raise ForecastRegistryIntegrityError("forecast content hash mismatch")
            previous_hash = str(row["content_hash"])


__all__ = [
    "ForecastClass", "ForecastDirection", "ForecastRecord",
    "ForecastRegistryIntegrityError", "ForecastStatus", "SQLiteForecastRegistry",
]
