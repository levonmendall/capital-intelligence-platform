"""Governed readiness assessment for controlled paper-product testing.

Readiness is evaluated against an immutable test baseline while normal product
development may continue on later commits. No result authorizes real money,
performance claims, or broker connectivity.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ProductTestReadiness(str, Enum):
    DEVELOPMENT_IN_PROGRESS = "development_in_progress"
    BLOCKED = "blocked"
    READY_FOR_CONTROLLED_PAPER_TEST = "ready_for_controlled_paper_test"


class TestReadinessIntegrityError(RuntimeError):
    """Raised when readiness history is not append-only and intact."""


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


def _texts(value: object, *, field_name: str, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(_text(item, field_name=field_name) for item in value)
    if len(normalized) < minimum:
        raise ValueError(f"{field_name} requires at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class ProductTestReadinessEvidence:
    identifier: str
    assessed_at: datetime
    test_baseline_identifier: str | None
    process_version: str | None
    code_version: str
    development_remains_open: bool
    core_us_market_ready: bool
    crypto_market_ready: bool
    spot_fx_market_ready: bool
    international_equity_market_ready: bool
    fixed_income_market_ready: bool
    commodity_market_ready: bool
    real_estate_market_ready: bool
    futures_market_ready: bool
    options_market_ready: bool
    volatility_market_ready: bool
    alternative_market_ready: bool
    certified_data_ready: bool
    complete_screening_ready: bool
    production_context_ready: bool
    portfolio_construction_ready: bool
    paper_execution_ready: bool
    thesis_and_evaluation_ready: bool
    daily_operations_ready: bool
    four_screen_product_ready: bool
    security_suite_ready: bool
    resilience_campaign_ready: bool
    paper_only_disclosures_ready: bool
    unresolved_critical_incidents: int
    data_integrity_failures: int
    reconciliation_failures: int
    evidence_identifiers: tuple[str, ...]
    open_development_items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "code_version"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name=field_name))
        _aware(self.assessed_at, field_name="assessed_at")
        for field_name in ("test_baseline_identifier", "process_version"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _text(value, field_name=field_name))
        boolean_fields = (
            "development_remains_open", "core_us_market_ready", "crypto_market_ready",
            "spot_fx_market_ready", "international_equity_market_ready",
            "fixed_income_market_ready", "commodity_market_ready",
            "real_estate_market_ready", "futures_market_ready",
            "options_market_ready", "volatility_market_ready",
            "alternative_market_ready", "certified_data_ready",
            "complete_screening_ready", "production_context_ready", "portfolio_construction_ready",
            "paper_execution_ready", "thesis_and_evaluation_ready", "daily_operations_ready",
            "four_screen_product_ready", "security_suite_ready", "resilience_campaign_ready",
            "paper_only_disclosures_ready",
        )
        for field_name in boolean_fields:
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        for field_name in (
            "unresolved_critical_incidents", "data_integrity_failures", "reconciliation_failures"
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a nonnegative integer")
        object.__setattr__(self, "evidence_identifiers", _texts(self.evidence_identifiers, field_name="evidence_identifiers", minimum=1))
        object.__setattr__(self, "open_development_items", _texts(self.open_development_items, field_name="open_development_items"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "test_baseline_identifier": self.test_baseline_identifier,
            "process_version": self.process_version,
            "code_version": self.code_version,
            "development_remains_open": self.development_remains_open,
            "core_us_market_ready": self.core_us_market_ready,
            "crypto_market_ready": self.crypto_market_ready,
            "spot_fx_market_ready": self.spot_fx_market_ready,
            "international_equity_market_ready": self.international_equity_market_ready,
            "fixed_income_market_ready": self.fixed_income_market_ready,
            "commodity_market_ready": self.commodity_market_ready,
            "real_estate_market_ready": self.real_estate_market_ready,
            "futures_market_ready": self.futures_market_ready,
            "options_market_ready": self.options_market_ready,
            "volatility_market_ready": self.volatility_market_ready,
            "alternative_market_ready": self.alternative_market_ready,
            "certified_data_ready": self.certified_data_ready,
            "complete_screening_ready": self.complete_screening_ready,
            "production_context_ready": self.production_context_ready,
            "portfolio_construction_ready": self.portfolio_construction_ready,
            "paper_execution_ready": self.paper_execution_ready,
            "thesis_and_evaluation_ready": self.thesis_and_evaluation_ready,
            "daily_operations_ready": self.daily_operations_ready,
            "four_screen_product_ready": self.four_screen_product_ready,
            "security_suite_ready": self.security_suite_ready,
            "resilience_campaign_ready": self.resilience_campaign_ready,
            "paper_only_disclosures_ready": self.paper_only_disclosures_ready,
            "unresolved_critical_incidents": self.unresolved_critical_incidents,
            "data_integrity_failures": self.data_integrity_failures,
            "reconciliation_failures": self.reconciliation_failures,
            "evidence_identifiers": list(self.evidence_identifiers),
            "open_development_items": list(self.open_development_items),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProductTestReadinessEvidence":
        normalized = dict(payload)
        # Older persisted evidence predated universal-market readiness gates.
        # Missing fields fail closed rather than being inferred as ready.
        for field_name in (
            "fixed_income_market_ready",
            "commodity_market_ready",
            "real_estate_market_ready",
            "futures_market_ready",
            "options_market_ready",
            "volatility_market_ready",
            "alternative_market_ready",
        ):
            normalized.setdefault(field_name, False)
        return cls(
            **{
                **normalized,
                "assessed_at": datetime.fromisoformat(str(payload["assessed_at"])),
                "evidence_identifiers": tuple(payload["evidence_identifiers"]),
                "open_development_items": tuple(payload.get("open_development_items", ())),
            }
        )


@dataclass(frozen=True, slots=True)
class ProductTestReadinessReport:
    identifier: str
    assessed_at: datetime
    state: ProductTestReadiness
    baseline_identifier: str | None
    process_version: str | None
    blockers: tuple[str, ...]
    development_items: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    real_money_authorized: bool = False
    performance_claims_permitted: bool = False

    def __post_init__(self) -> None:
        if self.real_money_authorized or self.performance_claims_permitted:
            raise ValueError("test readiness cannot authorize real money or performance claims")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "assessed_at": self.assessed_at.isoformat(),
            "state": self.state.value,
            "baseline_identifier": self.baseline_identifier,
            "process_version": self.process_version,
            "blockers": list(self.blockers),
            "development_items": list(self.development_items),
            "evidence_identifiers": list(self.evidence_identifiers),
            "real_money_authorized": False,
            "performance_claims_permitted": False,
        }


class ProductTestReadinessEvaluator:
    """Evaluate a versioned baseline without requiring main development to stop."""

    _REQUIRED_FLAGS = (
        "core_us_market_ready", "crypto_market_ready", "spot_fx_market_ready",
        "international_equity_market_ready", "fixed_income_market_ready",
        "commodity_market_ready", "real_estate_market_ready",
        "futures_market_ready", "options_market_ready",
        "volatility_market_ready", "alternative_market_ready",
        "certified_data_ready", "complete_screening_ready",
        "production_context_ready", "portfolio_construction_ready", "paper_execution_ready",
        "thesis_and_evaluation_ready", "daily_operations_ready", "four_screen_product_ready",
        "security_suite_ready", "resilience_campaign_ready", "paper_only_disclosures_ready",
    )

    def evaluate(self, evidence: ProductTestReadinessEvidence) -> ProductTestReadinessReport:
        if not isinstance(evidence, ProductTestReadinessEvidence):
            raise TypeError("evidence must be ProductTestReadinessEvidence")
        blockers = [name.removesuffix("_ready") for name in self._REQUIRED_FLAGS if not getattr(evidence, name)]
        if evidence.test_baseline_identifier is None:
            blockers.append("immutable_test_baseline")
        if evidence.process_version is None:
            blockers.append("versioned_investment_process")
        if evidence.unresolved_critical_incidents:
            blockers.append("unresolved_critical_incidents")
        if evidence.data_integrity_failures:
            blockers.append("data_integrity_failures")
        if evidence.reconciliation_failures:
            blockers.append("reconciliation_failures")
        if blockers:
            state = ProductTestReadiness.DEVELOPMENT_IN_PROGRESS if evidence.development_remains_open else ProductTestReadiness.BLOCKED
        else:
            state = ProductTestReadiness.READY_FOR_CONTROLLED_PAPER_TEST
        return ProductTestReadinessReport(
            identifier=f"test-readiness-report:{evidence.identifier}",
            assessed_at=evidence.assessed_at,
            state=state,
            baseline_identifier=evidence.test_baseline_identifier,
            process_version=evidence.process_version,
            blockers=tuple(sorted(set(blockers))),
            development_items=evidence.open_development_items,
            evidence_identifiers=evidence.evidence_identifiers,
        )


class SQLiteProductTestReadinessStore:
    _TABLE = "product_test_readiness_reports"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    assessed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'test readiness history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'test readiness history is append-only'); END;
            """)

    @staticmethod
    def _hash(sequence: int, identifier: str, assessed_at: str, payload: str, previous: str) -> str:
        return hashlib.sha256(f"{sequence}|{identifier}|{assessed_at}|{payload}|{previous}".encode()).hexdigest()

    def append(self, report: ProductTestReadinessReport) -> int:
        if not isinstance(report, ProductTestReadinessReport):
            raise TypeError("report must be ProductTestReadinessReport")
        self.verify_integrity()
        payload = _json(report.to_dict())
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute(f"SELECT sequence,payload_json FROM {self._TABLE} WHERE identifier=?", (report.identifier,)).fetchone()
            if existing is not None:
                if existing[1] != payload:
                    raise ValueError("report identifier already exists with different content")
                return int(existing[0])
            tail = connection.execute(f"SELECT sequence,content_hash FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1").fetchone()
            sequence = 1 if tail is None else int(tail[0]) + 1
            previous = self._GENESIS if tail is None else str(tail[1])
            content_hash = self._hash(sequence, report.identifier, report.assessed_at.isoformat(), payload, previous)
            connection.execute(f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?)", (sequence, report.identifier, report.assessed_at.isoformat(), payload, previous, content_hash))
        return sequence

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(f"SELECT * FROM {self._TABLE} ORDER BY sequence").fetchall()
        for expected, row in enumerate(rows, 1):
            if row[0] != expected or row[4] != previous:
                raise TestReadinessIntegrityError("test readiness chain is not contiguous")
            actual = self._hash(row[0], row[1], row[2], row[3], row[4])
            if row[5] != actual:
                raise TestReadinessIntegrityError("test readiness content hash is invalid")
            previous = actual
        return True


__all__ = [
    "ProductTestReadiness", "ProductTestReadinessEvidence", "ProductTestReadinessEvaluator",
    "ProductTestReadinessReport", "SQLiteProductTestReadinessStore", "TestReadinessIntegrityError",
]
