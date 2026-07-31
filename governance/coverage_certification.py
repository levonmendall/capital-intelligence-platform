"""Market-scope and point-in-time historical certification authority.

Monitoring, CIO decision evidence, and paper allocation are deliberately
separate.  A provider or dataset becoming observable never promotes either
downstream scope.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class CoverageLevel(str, Enum):
    MONITORED = "monitored"
    DECISION_CERTIFIED = "decision_certified"
    ALLOCATABLE = "allocatable"


@dataclass(frozen=True, slots=True)
class MarketCoverage:
    market: str
    monitored: bool
    decision_certification_identifier: str | None
    allocatable_instrument_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", _text(self.market, "market"))
        if not isinstance(self.monitored, bool):
            raise TypeError("monitored must be boolean")
        if self.decision_certification_identifier is not None:
            object.__setattr__(
                self,
                "decision_certification_identifier",
                _text(self.decision_certification_identifier, "decision_certification_identifier"),
            )
        for field in ("allocatable_instrument_identifiers", "limitations"):
            value = getattr(self, field)
            if not isinstance(value, tuple) or not all(isinstance(item, str) and item.strip() for item in value):
                raise TypeError(f"{field} must be a text tuple")
            if len(value) != len(set(value)):
                raise ValueError(f"{field} cannot contain duplicates")
        if self.decision_certification_identifier and not self.monitored:
            raise ValueError("decision-certified markets must be monitored")
        if self.allocatable_instrument_identifiers and not self.decision_certification_identifier:
            raise ValueError("allocatable instruments require decision certification")

    @property
    def decision_certified(self) -> bool:
        return self.decision_certification_identifier is not None

    def level_for(self, instrument_identifier: str | None = None) -> CoverageLevel | None:
        if instrument_identifier in self.allocatable_instrument_identifiers:
            return CoverageLevel.ALLOCATABLE
        if self.decision_certified:
            return CoverageLevel.DECISION_CERTIFIED
        if self.monitored:
            return CoverageLevel.MONITORED
        return None


@dataclass(frozen=True, slots=True)
class MarketCoverageRegistry:
    identifier: str
    portfolio_code: str
    markets: tuple[MarketCoverage, ...]
    schema_version: str = "market-coverage-registry.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, "identifier"))
        if self.portfolio_code != "COMPOUNDING":
            raise ValueError("market coverage registry must govern COMPOUNDING")
        names = tuple(item.market for item in self.markets)
        if len(names) != len(set(names)):
            raise ValueError("market coverage entries cannot repeat")
        instruments = [value for item in self.markets for value in item.allocatable_instrument_identifiers]
        if len(instruments) != len(set(instruments)):
            raise ValueError("one allocatable instrument cannot belong to multiple market scopes")

    def require_allocatable(self, *, market: str, instrument_identifier: str) -> None:
        entry = next((item for item in self.markets if item.market == market), None)
        if entry is None or entry.level_for(instrument_identifier) is not CoverageLevel.ALLOCATABLE:
            raise ValueError(f"{instrument_identifier} is not currently allocatable in {market}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "portfolio_code": self.portfolio_code,
            "schema_version": self.schema_version,
            "markets": [
                {
                    "market": item.market,
                    "monitored": item.monitored,
                    "decision_certified": item.decision_certified,
                    "decision_certification_identifier": item.decision_certification_identifier,
                    "allocatable_instrument_identifiers": list(item.allocatable_instrument_identifiers),
                    "limitations": list(item.limitations),
                }
                for item in self.markets
            ],
            "real_money_authorized": False,
        }


class HistoricalCertificationDomain(str, Enum):
    MACRO_VINTAGES = "macro_vintages"
    FILINGS_REVISIONS = "filings_revisions"
    LISTINGS_DELISTINGS = "listings_delistings"
    CORPORATE_ACTIONS = "corporate_actions"
    INDEX_MEMBERSHIP = "index_membership"
    LIQUIDITY_QUOTES = "liquidity_quotes"
    MARKET_CALENDARS = "market_calendars"
    PROVIDER_AVAILABILITY = "provider_availability"


class HistoricalCertificationState(str, Enum):
    CERTIFIED = "certified"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class HistoricalCertificationBoundary:
    domain: HistoricalCertificationDomain
    state: HistoricalCertificationState
    provider_identifier: str
    coverage_start: datetime | None
    coverage_end: datetime | None
    certification_identifier: str | None
    evidence_identifiers: tuple[str, ...]
    revision_safe: bool
    survivorship_safe: bool
    limitation: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.domain, HistoricalCertificationDomain):
            raise TypeError("domain must be HistoricalCertificationDomain")
        if not isinstance(self.state, HistoricalCertificationState):
            raise TypeError("state must be HistoricalCertificationState")
        object.__setattr__(self, "provider_identifier", _text(self.provider_identifier, "provider_identifier"))
        for field in ("coverage_start", "coverage_end"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _aware(value, field))
        if self.coverage_start and self.coverage_end and self.coverage_end < self.coverage_start:
            raise ValueError("coverage_end cannot predate coverage_start")
        if self.state is HistoricalCertificationState.CERTIFIED:
            if not self.certification_identifier or not self.evidence_identifiers:
                raise ValueError("certified boundaries require certification and evidence")
            if self.coverage_start is None:
                raise ValueError("certified boundaries require a provider availability start")
            if self.domain in {
                HistoricalCertificationDomain.MACRO_VINTAGES,
                HistoricalCertificationDomain.FILINGS_REVISIONS,
            } and not self.revision_safe:
                raise ValueError("revision-bearing domains must be revision safe")
            if self.domain in {
                HistoricalCertificationDomain.LISTINGS_DELISTINGS,
                HistoricalCertificationDomain.CORPORATE_ACTIONS,
                HistoricalCertificationDomain.INDEX_MEMBERSHIP,
            } and not self.survivorship_safe:
                raise ValueError("universe-changing domains must be survivorship safe")
        elif not self.limitation:
            raise ValueError("blocked historical boundaries require a limitation")

    def covers(self, cutoff: datetime) -> bool:
        timestamp = _aware(cutoff, "cutoff")
        return (
            self.state is HistoricalCertificationState.CERTIFIED
            and self.coverage_start is not None
            and self.coverage_start <= timestamp
            and (self.coverage_end is None or timestamp <= self.coverage_end)
        )


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceReference:
    identifier: str
    domain: HistoricalCertificationDomain
    provider_identifier: str
    observed_at: datetime
    available_at: datetime
    supersedes_identifier: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, "identifier"))
        object.__setattr__(self, "provider_identifier", _text(self.provider_identifier, "provider_identifier"))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, "observed_at"))
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        if self.available_at < self.observed_at:
            raise ValueError("available_at cannot predate observed_at")


@dataclass(frozen=True, slots=True)
class HistoricalCertificationReport:
    cutoff: datetime
    ready: bool
    blockers: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    schema_version: str = "historical-certification-report.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cutoff": self.cutoff.isoformat(),
            "ready": self.ready,
            "blockers": list(self.blockers),
            "evidence_identifiers": list(self.evidence_identifiers),
            "schema_version": self.schema_version,
            "research_only": not self.ready,
            "performance_claims_authorized": False,
            "policy_promotion_authorized": False,
            "real_money_authorized": False,
        }


def certify_historical_cutoff(
    *,
    cutoff: datetime,
    boundaries: Iterable[HistoricalCertificationBoundary],
    evidence: Iterable[HistoricalEvidenceReference],
    required_domains: Iterable[HistoricalCertificationDomain] = tuple(HistoricalCertificationDomain),
) -> HistoricalCertificationReport:
    timestamp = _aware(cutoff, "cutoff")
    by_domain = {item.domain: item for item in boundaries}
    blockers = []
    for domain in required_domains:
        boundary = by_domain.get(domain)
        if boundary is None:
            blockers.append(f"{domain.value}: certification boundary missing")
        elif not boundary.covers(timestamp):
            blockers.append(f"{domain.value}: not certified at cutoff")
    visible = []
    for item in evidence:
        boundary = by_domain.get(item.domain)
        if item.available_at > timestamp:
            blockers.append(f"{item.identifier}: future-known at cutoff")
            continue
        if boundary is None or item.provider_identifier != boundary.provider_identifier:
            blockers.append(f"{item.identifier}: provider outside certified boundary")
            continue
        if not boundary.covers(timestamp):
            blockers.append(f"{item.identifier}: provider unavailable at cutoff")
            continue
        visible.append(item.identifier)
    return HistoricalCertificationReport(
        cutoff=timestamp,
        ready=not blockers,
        blockers=tuple(sorted(set(blockers))),
        evidence_identifiers=tuple(sorted(visible)),
    )


def load_market_coverage(path: str | Path) -> MarketCoverageRegistry:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "market-coverage-registry.v1":
        raise ValueError("unsupported market coverage registry")
    return MarketCoverageRegistry(
        identifier=payload["identifier"],
        portfolio_code=payload["portfolio_code"],
        markets=tuple(
            MarketCoverage(
                market=item["market"],
                monitored=item["monitored"],
                decision_certification_identifier=item.get("decision_certification_identifier"),
                allocatable_instrument_identifiers=tuple(item.get("allocatable_instrument_identifiers", ())),
                limitations=tuple(item.get("limitations", ())),
            )
            for item in payload["markets"]
        ),
    )


def load_historical_boundaries(path: str | Path) -> tuple[HistoricalCertificationBoundary, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "historical-certification-boundaries.v1":
        raise ValueError("unsupported historical certification boundaries")
    return tuple(
        HistoricalCertificationBoundary(
            domain=HistoricalCertificationDomain(item["domain"]),
            state=HistoricalCertificationState(item["state"]),
            provider_identifier=item["provider_identifier"],
            coverage_start=None if item.get("coverage_start") is None else datetime.fromisoformat(item["coverage_start"]),
            coverage_end=None if item.get("coverage_end") is None else datetime.fromisoformat(item["coverage_end"]),
            certification_identifier=item.get("certification_identifier"),
            evidence_identifiers=tuple(item.get("evidence_identifiers", ())),
            revision_safe=bool(item.get("revision_safe", False)),
            survivorship_safe=bool(item.get("survivorship_safe", False)),
            limitation=item.get("limitation"),
        )
        for item in payload["boundaries"]
    )


class SQLiteCoverageCertificationStore:
    """Append-only registry snapshots; never an allocation authority itself."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS coverage_certifications(identifier TEXT PRIMARY KEY, recorded_at TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS coverage_no_update BEFORE UPDATE ON coverage_certifications BEGIN SELECT RAISE(ABORT, 'coverage certification is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS coverage_no_delete BEFORE DELETE ON coverage_certifications BEGIN SELECT RAISE(ABORT, 'coverage certification is append-only'); END;
                """
            )

    def append(self, *, identifier: str, recorded_at: datetime, payload: Mapping[str, Any]) -> None:
        normalized = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(normalized.encode()).hexdigest()
        with sqlite3.connect(self.path) as connection:
            existing = connection.execute("SELECT payload_hash FROM coverage_certifications WHERE identifier=?", (identifier,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("coverage identifier already exists with different content")
                return
            connection.execute("INSERT INTO coverage_certifications VALUES (?, ?, ?, ?)", (identifier, _aware(recorded_at, "recorded_at").isoformat(), normalized, digest))


__all__ = [
    "CoverageLevel", "HistoricalCertificationBoundary", "HistoricalCertificationDomain",
    "HistoricalCertificationReport", "HistoricalCertificationState", "HistoricalEvidenceReference",
    "MarketCoverage", "MarketCoverageRegistry", "SQLiteCoverageCertificationStore",
    "certify_historical_cutoff", "load_historical_boundaries", "load_market_coverage",
]
