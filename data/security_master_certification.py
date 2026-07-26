"""Vendor-neutral security-master provider certification authority.

A provider adapter may be technically functional while still being unsafe for
point-in-time full-universe investment decisions.  Certification therefore
validates contractual capabilities and deterministic historical scenarios before
an ingested catalog may be activated for screening.
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
from typing import Any, Iterable

from data.security import SecurityMasterError
from data.security_master import ListingStatus, SecurityMasterActionType
from data.security_master_ingestion import (
    SecurityMasterIngestionQuery,
    SecurityMasterProvider,
    SecurityMasterProviderError,
)


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


def _finite(
    value: object,
    *,
    field_name: str,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return round(normalized, 10)


def _canonical_json(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("provider certification payload must be finite JSON") from error


class ProviderCertificationDecision(str, Enum):
    APPROVED = "approved"
    CONDITIONALLY_APPROVED = "conditionally_approved"
    REJECTED = "rejected"


class ProviderCertificationScenarioKind(str, Enum):
    CURRENT_IDENTITY = "current_identity"
    HISTORICAL_IDENTITY = "historical_identity"
    SYMBOL_CHANGE = "symbol_change"
    VENUE_CHANGE = "venue_change"
    DELISTING = "delisting"
    MERGER = "merger"
    SPINOFF = "spinoff"
    LATE_CORRECTION = "late_correction"
    FUTURE_KNOWLEDGE_EXCLUSION = "future_knowledge_exclusion"
    CROSS_VENUE_ADJUSTMENT = "cross_venue_adjustment"
    FULL_UNIVERSE_COVERAGE = "full_universe_coverage"


@dataclass(frozen=True, slots=True)
class ProviderCapabilityManifest:
    """Commercial and technical claims that must be independently verified."""

    provider: str
    product: str
    manifest_version: str
    source_version: str
    license_reference: str
    license_verified: bool
    complete_eligible_universe: bool
    point_in_time_delivery: bool
    historical_identifiers: bool
    listing_and_venue_history: bool
    delisted_securities: bool
    corporate_actions: bool
    revision_history: bool
    provenance_complete: bool
    cross_venue_adjustment_policy: str
    service_level_reference: str
    maximum_delivery_age_hours: float
    valid_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "product",
            "manifest_version",
            "source_version",
            "license_reference",
            "cross_venue_adjustment_policy",
            "service_level_reference",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "license_verified",
            "complete_eligible_universe",
            "point_in_time_delivery",
            "historical_identifiers",
            "listing_and_venue_history",
            "delisted_securities",
            "corporate_actions",
            "revision_history",
            "provenance_complete",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        object.__setattr__(
            self,
            "maximum_delivery_age_hours",
            _finite(
                self.maximum_delivery_age_hours,
                field_name="maximum_delivery_age_hours",
                minimum=0.0,
            ),
        )
        start = _aware(self.valid_from, field_name="valid_from")
        end = _aware(self.valid_until, field_name="valid_until")
        if end <= start:
            raise ValueError("valid_until must follow valid_from")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "valid_until", end)

    @property
    def hard_deficiencies(self) -> tuple[str, ...]:
        checks = (
            ("commercial license is not verified", self.license_verified),
            ("eligible-universe coverage is incomplete", self.complete_eligible_universe),
            ("point-in-time delivery is not supported", self.point_in_time_delivery),
            ("historical identifiers are not supported", self.historical_identifiers),
            ("listing and venue history is not supported", self.listing_and_venue_history),
            ("delisted securities are not supported", self.delisted_securities),
            ("corporate actions are not supported", self.corporate_actions),
            ("revision history is not supported", self.revision_history),
            ("provenance is incomplete", self.provenance_complete),
        )
        return tuple(message for message, passed in checks if not passed)

    def active_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return self.valid_from <= resolved <= self.valid_until


@dataclass(frozen=True, slots=True)
class ProviderCertificationScenario:
    """One deterministic point-in-time provider contract test."""

    identifier: str
    kind: ProviderCertificationScenarioKind
    description: str
    query: SecurityMasterIngestionQuery
    required: bool = True
    expected_symbols: tuple[str, ...] = ()
    excluded_symbols: tuple[str, ...] = ()
    expected_listings: tuple[tuple[str, str, ListingStatus], ...] = ()
    expected_action_types: tuple[SecurityMasterActionType, ...] = ()
    minimum_instrument_count: int = 0
    maximum_future_known_records: int = 0

    def __post_init__(self) -> None:
        for field_name in ("identifier", "description"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.kind, ProviderCertificationScenarioKind):
            raise TypeError("kind must be ProviderCertificationScenarioKind")
        if not isinstance(self.query, SecurityMasterIngestionQuery):
            raise TypeError("query must be SecurityMasterIngestionQuery")
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")
        object.__setattr__(
            self,
            "expected_symbols",
            tuple(_required_text(item, field_name="expected_symbol").upper() for item in self.expected_symbols),
        )
        object.__setattr__(
            self,
            "excluded_symbols",
            tuple(_required_text(item, field_name="excluded_symbol").upper() for item in self.excluded_symbols),
        )
        normalized_listings: list[tuple[str, str, ListingStatus]] = []
        for symbol, venue, status in self.expected_listings:
            if not isinstance(status, ListingStatus):
                raise TypeError("expected listing status must be ListingStatus")
            normalized_listings.append(
                (
                    _required_text(symbol, field_name="listing_symbol").upper(),
                    _required_text(venue, field_name="listing_venue").upper(),
                    status,
                )
            )
        object.__setattr__(self, "expected_listings", tuple(normalized_listings))
        if any(not isinstance(item, SecurityMasterActionType) for item in self.expected_action_types):
            raise TypeError("expected_action_types must contain SecurityMasterActionType")
        for field_name in ("minimum_instrument_count", "maximum_future_known_records"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} cannot be negative")


@dataclass(frozen=True, slots=True)
class ProviderCertificationScenarioResult:
    scenario_identifier: str
    kind: ProviderCertificationScenarioKind
    required: bool
    passed: bool
    observed_catalog_identifier: str | None
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_identifier",
            _required_text(self.scenario_identifier, field_name="scenario_identifier"),
        )
        if not isinstance(self.kind, ProviderCertificationScenarioKind):
            raise TypeError("kind must be ProviderCertificationScenarioKind")
        if not isinstance(self.required, bool) or not isinstance(self.passed, bool):
            raise TypeError("required and passed must be bool values")
        if self.observed_catalog_identifier is not None:
            object.__setattr__(
                self,
                "observed_catalog_identifier",
                _required_text(
                    self.observed_catalog_identifier,
                    field_name="observed_catalog_identifier",
                ),
            )
        object.__setattr__(
            self,
            "issues",
            tuple(_required_text(item, field_name="issue") for item in self.issues),
        )


@dataclass(frozen=True, slots=True)
class ProviderCertificationReport:
    identifier: str
    provider: str
    product: str
    manifest_version: str
    source_version: str
    certified_at: datetime
    valid_until: datetime
    decision: ProviderCertificationDecision
    manifest_deficiencies: tuple[str, ...]
    scenario_results: tuple[ProviderCertificationScenarioResult, ...]
    required_failures: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "provider",
            "product",
            "manifest_version",
            "source_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        certified = _aware(self.certified_at, field_name="certified_at")
        valid_until = _aware(self.valid_until, field_name="valid_until")
        if valid_until <= certified:
            raise ValueError("valid_until must follow certified_at")
        object.__setattr__(self, "certified_at", certified)
        object.__setattr__(self, "valid_until", valid_until)
        if not isinstance(self.decision, ProviderCertificationDecision):
            raise TypeError("decision must be ProviderCertificationDecision")
        for field_name in ("manifest_deficiencies", "required_failures", "warnings"):
            object.__setattr__(
                self,
                field_name,
                tuple(
                    _required_text(item, field_name=field_name)
                    for item in getattr(self, field_name)
                ),
            )
        if any(not isinstance(item, ProviderCertificationScenarioResult) for item in self.scenario_results):
            raise TypeError("scenario_results must contain ProviderCertificationScenarioResult")
        if self.decision is ProviderCertificationDecision.APPROVED and (
            self.manifest_deficiencies or self.required_failures
        ):
            raise ValueError("approved certification cannot contain required failures")

    @property
    def approved(self) -> bool:
        return self.decision is ProviderCertificationDecision.APPROVED

    def valid_at(self, timestamp: datetime) -> bool:
        resolved = _aware(timestamp, field_name="timestamp")
        return self.certified_at <= resolved <= self.valid_until


class ProviderCertificationHarness:
    """Execute deterministic manifest and point-in-time adapter acceptance tests."""

    def certify(
        self,
        provider: SecurityMasterProvider,
        manifest: ProviderCapabilityManifest,
        scenarios: Iterable[ProviderCertificationScenario],
        *,
        identifier: str,
        certified_at: datetime | None = None,
    ) -> ProviderCertificationReport:
        if not isinstance(provider, SecurityMasterProvider):
            raise TypeError("provider must implement SecurityMasterProvider")
        if not isinstance(manifest, ProviderCapabilityManifest):
            raise TypeError("manifest must be ProviderCapabilityManifest")
        provider_name = _required_text(provider.name, field_name="provider.name")
        if provider_name.upper() != manifest.provider.upper():
            raise ValueError("provider identity does not match capability manifest")
        evaluated = _aware(
            certified_at or datetime.now(timezone.utc),
            field_name="certified_at",
        )
        manifest_issues = list(manifest.hard_deficiencies)
        if not manifest.active_at(evaluated):
            manifest_issues.append("capability manifest is outside its validity interval")

        results = tuple(
            self._evaluate_scenario(provider, manifest, scenario)
            for scenario in tuple(scenarios)
        )
        required_failures = tuple(
            f"{item.scenario_identifier}: {issue}"
            for item in results
            if item.required and not item.passed
            for issue in (item.issues or ("scenario failed",))
        )
        warnings = tuple(
            f"{item.scenario_identifier}: {issue}"
            for item in results
            if not item.required and not item.passed
            for issue in (item.issues or ("optional scenario failed",))
        )
        if manifest_issues or required_failures:
            decision = ProviderCertificationDecision.REJECTED
        elif warnings:
            decision = ProviderCertificationDecision.CONDITIONALLY_APPROVED
        else:
            decision = ProviderCertificationDecision.APPROVED
        return ProviderCertificationReport(
            identifier=_required_text(identifier, field_name="identifier"),
            provider=manifest.provider,
            product=manifest.product,
            manifest_version=manifest.manifest_version,
            source_version=manifest.source_version,
            certified_at=evaluated,
            valid_until=manifest.valid_until,
            decision=decision,
            manifest_deficiencies=tuple(dict.fromkeys(manifest_issues)),
            scenario_results=results,
            required_failures=required_failures,
            warnings=warnings,
        )

    def _evaluate_scenario(
        self,
        provider: SecurityMasterProvider,
        manifest: ProviderCapabilityManifest,
        scenario: ProviderCertificationScenario,
    ) -> ProviderCertificationScenarioResult:
        if not isinstance(scenario, ProviderCertificationScenario):
            raise TypeError("scenarios must contain ProviderCertificationScenario")
        issues: list[str] = []
        catalog_identifier: str | None = None
        try:
            delivery = provider.fetch_security_master_delivery(scenario.query)
            if delivery.request_identifier != scenario.query.identifier:
                issues.append("delivery request identifier does not match the query")
            if delivery.catalog.coverage.source.upper() != manifest.provider.upper():
                issues.append("catalog source does not match the certified provider")
            if delivery.catalog.coverage.source_version != manifest.source_version:
                issues.append("catalog source version does not match the manifest")
            if delivery.observed_at > delivery.retrieved_at:
                issues.append("provider observation follows retrieval")
            delivery_age = (
                scenario.query.requested_at - delivery.observed_at
            ).total_seconds() / 3600.0
            if delivery_age < 0:
                issues.append("provider observation follows the request timestamp")
            elif delivery_age > manifest.maximum_delivery_age_hours:
                issues.append(
                    "provider delivery exceeds the manifest SLA: "
                    f"{delivery_age:.2f}h > {manifest.maximum_delivery_age_hours:.2f}h"
                )
            catalog = delivery.catalog
            catalog_identifier = catalog.identifier
            snapshot = catalog.snapshot(
                as_of=scenario.query.as_of,
                knowledge_cutoff=scenario.query.knowledge_cutoff,
            )
            symbols = {item.symbol.upper() for item in snapshot.listings}
            for symbol in scenario.expected_symbols:
                if symbol not in symbols:
                    issues.append(f"expected symbol {symbol} is missing")
            for symbol in scenario.excluded_symbols:
                if symbol in symbols:
                    issues.append(f"future or excluded symbol {symbol} is present")
            listing_keys = {
                (item.symbol.upper(), item.venue.upper(), item.status)
                for item in snapshot.listings
            }
            for expected in scenario.expected_listings:
                if expected not in listing_keys:
                    symbol, venue, status = expected
                    issues.append(
                        f"expected listing {venue}:{symbol}:{status.value} is missing"
                    )
            action_types = {item.action_type for item in snapshot.actions}
            for action_type in scenario.expected_action_types:
                if action_type not in action_types:
                    issues.append(f"expected action {action_type.value} is missing")
            if len(snapshot.instruments) < scenario.minimum_instrument_count:
                issues.append(
                    "instrument count is below scenario minimum: "
                    f"{len(snapshot.instruments)} < {scenario.minimum_instrument_count}"
                )
            records = (
                *catalog.issuers,
                *catalog.instruments,
                *catalog.identifiers,
                *catalog.listings,
                *catalog.actions,
            )
            future_known = sum(
                item.available_at > scenario.query.knowledge_cutoff
                and (
                    item in snapshot.issuers
                    or item in snapshot.instruments
                    or item in snapshot.identifiers
                    or item in snapshot.listings
                    or item in snapshot.actions
                )
                for item in records
            )
            if future_known > scenario.maximum_future_known_records:
                issues.append(
                    "snapshot contains records unavailable by the knowledge cutoff: "
                    f"{future_known} > {scenario.maximum_future_known_records}"
                )
        except (SecurityMasterProviderError, SecurityMasterError, LookupError, TypeError, ValueError) as error:
            issues.append(str(error))
        except Exception as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            issues.append(f"provider scenario raised {type(error).__name__}: {error}")
        return ProviderCertificationScenarioResult(
            scenario_identifier=scenario.identifier,
            kind=scenario.kind,
            required=scenario.required,
            passed=not issues,
            observed_catalog_identifier=catalog_identifier,
            issues=tuple(dict.fromkeys(issues)),
        )


class ProviderCertificationIntegrityError(SecurityMasterError):
    """Raised when append-only provider certification history is invalid."""


@dataclass(frozen=True, slots=True)
class ProviderCertificationEvent:
    sequence: int
    report_identifier: str
    provider: str
    certified_at: datetime
    payload_json: str
    previous_hash: str
    content_hash: str


class SQLiteProviderCertificationStore:
    """Append-only, hash-chained provider certification registry."""

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
                CREATE TABLE IF NOT EXISTS provider_certifications (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_identifier TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL,
                    certified_at TEXT NOT NULL,
                    valid_until TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_provider_certifications_provider_time
                    ON provider_certifications(provider, certified_at, sequence);
                CREATE TRIGGER IF NOT EXISTS provider_certifications_no_update
                BEFORE UPDATE ON provider_certifications
                BEGIN
                    SELECT RAISE(ABORT, 'provider certification history is append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS provider_certifications_no_delete
                BEFORE DELETE ON provider_certifications
                BEGIN
                    SELECT RAISE(ABORT, 'provider certification history is append-only');
                END;
                """
            )

    def append(self, report: ProviderCertificationReport) -> ProviderCertificationEvent:
        if not isinstance(report, ProviderCertificationReport):
            raise TypeError("report must be ProviderCertificationReport")
        payload_json = _canonical_json(_report_payload(report))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM provider_certifications WHERE report_identifier = ?",
                (report.identifier,),
            ).fetchone()
            if existing is not None:
                event = self._event(existing)
                if event.payload_json != payload_json:
                    raise ProviderCertificationIntegrityError(
                        "provider certification identifier already exists with different content"
                    )
                return event
            previous = connection.execute(
                "SELECT content_hash FROM provider_certifications ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = "" if previous is None else str(previous["content_hash"])
            content_hash = _report_hash(report, payload_json, previous_hash)
            connection.execute(
                """
                INSERT INTO provider_certifications (
                    report_identifier, provider, certified_at, valid_until,
                    decision, payload_json, previous_hash, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.identifier,
                    report.provider,
                    report.certified_at.isoformat(),
                    report.valid_until.isoformat(),
                    report.decision.value,
                    payload_json,
                    previous_hash,
                    content_hash,
                ),
            )
            row = connection.execute(
                "SELECT * FROM provider_certifications WHERE report_identifier = ?",
                (report.identifier,),
            ).fetchone()
        assert row is not None
        return self._event(row)

    def latest(
        self,
        provider: str,
        *,
        evaluated_at: datetime | None = None,
    ) -> ProviderCertificationReport | None:
        normalized = _required_text(provider, field_name="provider")
        evaluated = _aware(
            evaluated_at or datetime.now(timezone.utc),
            field_name="evaluated_at",
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM provider_certifications
                WHERE UPPER(provider) = UPPER(?) AND certified_at <= ?
                ORDER BY certified_at DESC, sequence DESC LIMIT 1
                """,
                (normalized, evaluated.isoformat()),
            ).fetchone()
        if row is None:
            return None
        return _report_from_payload(json.loads(str(row["payload_json"])))

    def require_approved(
        self,
        provider: str,
        *,
        evaluated_at: datetime,
    ) -> ProviderCertificationReport:
        self.verify_integrity()
        report = self.latest(provider, evaluated_at=evaluated_at)
        if report is None:
            raise SecurityMasterError(
                f"provider certification is missing for {provider}"
            )
        if not report.approved:
            raise SecurityMasterError(
                "latest provider certification is not approved: "
                f"{report.decision.value}"
            )
        if not report.valid_at(evaluated_at):
            raise SecurityMasterError("approved provider certification has expired")
        return report

    def events(self) -> tuple[ProviderCertificationEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provider_certifications ORDER BY sequence"
            ).fetchall()
        return tuple(self._event(row) for row in rows)

    def verify_integrity(self) -> bool:
        previous_hash = ""
        expected_sequence = 1
        for event in self.events():
            if event.sequence != expected_sequence:
                raise ProviderCertificationIntegrityError(
                    "provider certification sequence is not contiguous"
                )
            if event.previous_hash != previous_hash:
                raise ProviderCertificationIntegrityError(
                    "provider certification previous hash is invalid"
                )
            report = _report_from_payload(json.loads(event.payload_json))
            expected_hash = _report_hash(report, event.payload_json, previous_hash)
            if event.content_hash != expected_hash:
                raise ProviderCertificationIntegrityError(
                    "provider certification content hash is invalid"
                )
            previous_hash = event.content_hash
            expected_sequence += 1
        return True

    @staticmethod
    def _event(row: sqlite3.Row) -> ProviderCertificationEvent:
        return ProviderCertificationEvent(
            sequence=int(row["sequence"]),
            report_identifier=str(row["report_identifier"]),
            provider=str(row["provider"]),
            certified_at=datetime.fromisoformat(str(row["certified_at"])),
            payload_json=str(row["payload_json"]),
            previous_hash=str(row["previous_hash"]),
            content_hash=str(row["content_hash"]),
        )



def scenario_from_payload(payload: dict[str, Any]) -> ProviderCertificationScenario:
    query_payload = payload["query"]
    query = SecurityMasterIngestionQuery(
        identifier=str(query_payload["identifier"]),
        as_of=datetime.fromisoformat(str(query_payload["as_of"])),
        knowledge_cutoff=datetime.fromisoformat(str(query_payload["knowledge_cutoff"])),
        requested_at=datetime.fromisoformat(str(query_payload["requested_at"])),
    )
    return ProviderCertificationScenario(
        identifier=str(payload["identifier"]),
        kind=ProviderCertificationScenarioKind(str(payload["kind"])),
        description=str(payload["description"]),
        query=query,
        required=bool(payload.get("required", True)),
        expected_symbols=tuple(str(item) for item in payload.get("expected_symbols", ())),
        excluded_symbols=tuple(str(item) for item in payload.get("excluded_symbols", ())),
        expected_listings=tuple(
            (str(item["symbol"]), str(item["venue"]), ListingStatus(str(item["status"])))
            for item in payload.get("expected_listings", ())
        ),
        expected_action_types=tuple(
            SecurityMasterActionType(str(item))
            for item in payload.get("expected_action_types", ())
        ),
        minimum_instrument_count=int(payload.get("minimum_instrument_count", 0)),
        maximum_future_known_records=int(payload.get("maximum_future_known_records", 0)),
    )


def report_to_payload(value: ProviderCertificationReport) -> dict[str, Any]:
    if not isinstance(value, ProviderCertificationReport):
        raise TypeError("value must be ProviderCertificationReport")
    return _report_payload(value)


def _manifest_payload(value: ProviderCapabilityManifest) -> dict[str, Any]:
    return {
        "provider": value.provider,
        "product": value.product,
        "manifest_version": value.manifest_version,
        "source_version": value.source_version,
        "license_reference": value.license_reference,
        "license_verified": value.license_verified,
        "complete_eligible_universe": value.complete_eligible_universe,
        "point_in_time_delivery": value.point_in_time_delivery,
        "historical_identifiers": value.historical_identifiers,
        "listing_and_venue_history": value.listing_and_venue_history,
        "delisted_securities": value.delisted_securities,
        "corporate_actions": value.corporate_actions,
        "revision_history": value.revision_history,
        "provenance_complete": value.provenance_complete,
        "cross_venue_adjustment_policy": value.cross_venue_adjustment_policy,
        "service_level_reference": value.service_level_reference,
        "maximum_delivery_age_hours": value.maximum_delivery_age_hours,
        "valid_from": value.valid_from.isoformat(),
        "valid_until": value.valid_until.isoformat(),
    }


def manifest_from_payload(payload: dict[str, Any]) -> ProviderCapabilityManifest:
    return ProviderCapabilityManifest(
        provider=str(payload["provider"]),
        product=str(payload["product"]),
        manifest_version=str(payload["manifest_version"]),
        source_version=str(payload["source_version"]),
        license_reference=str(payload["license_reference"]),
        license_verified=bool(payload["license_verified"]),
        complete_eligible_universe=bool(payload["complete_eligible_universe"]),
        point_in_time_delivery=bool(payload["point_in_time_delivery"]),
        historical_identifiers=bool(payload["historical_identifiers"]),
        listing_and_venue_history=bool(payload["listing_and_venue_history"]),
        delisted_securities=bool(payload["delisted_securities"]),
        corporate_actions=bool(payload["corporate_actions"]),
        revision_history=bool(payload["revision_history"]),
        provenance_complete=bool(payload["provenance_complete"]),
        cross_venue_adjustment_policy=str(payload["cross_venue_adjustment_policy"]),
        service_level_reference=str(payload["service_level_reference"]),
        maximum_delivery_age_hours=float(payload["maximum_delivery_age_hours"]),
        valid_from=datetime.fromisoformat(str(payload["valid_from"])),
        valid_until=datetime.fromisoformat(str(payload["valid_until"])),
    )


def _scenario_result_payload(value: ProviderCertificationScenarioResult) -> dict[str, Any]:
    return {
        "scenario_identifier": value.scenario_identifier,
        "kind": value.kind.value,
        "required": value.required,
        "passed": value.passed,
        "observed_catalog_identifier": value.observed_catalog_identifier,
        "issues": list(value.issues),
    }


def _scenario_result_from_payload(payload: dict[str, Any]) -> ProviderCertificationScenarioResult:
    return ProviderCertificationScenarioResult(
        scenario_identifier=str(payload["scenario_identifier"]),
        kind=ProviderCertificationScenarioKind(str(payload["kind"])),
        required=bool(payload["required"]),
        passed=bool(payload["passed"]),
        observed_catalog_identifier=payload.get("observed_catalog_identifier"),
        issues=tuple(str(item) for item in payload["issues"]),
    )


def _report_payload(value: ProviderCertificationReport) -> dict[str, Any]:
    return {
        "identifier": value.identifier,
        "provider": value.provider,
        "product": value.product,
        "manifest_version": value.manifest_version,
        "source_version": value.source_version,
        "certified_at": value.certified_at.isoformat(),
        "valid_until": value.valid_until.isoformat(),
        "decision": value.decision.value,
        "manifest_deficiencies": list(value.manifest_deficiencies),
        "scenario_results": [
            _scenario_result_payload(item) for item in value.scenario_results
        ],
        "required_failures": list(value.required_failures),
        "warnings": list(value.warnings),
    }


def _report_from_payload(payload: dict[str, Any]) -> ProviderCertificationReport:
    return ProviderCertificationReport(
        identifier=str(payload["identifier"]),
        provider=str(payload["provider"]),
        product=str(payload["product"]),
        manifest_version=str(payload["manifest_version"]),
        source_version=str(payload["source_version"]),
        certified_at=datetime.fromisoformat(str(payload["certified_at"])),
        valid_until=datetime.fromisoformat(str(payload["valid_until"])),
        decision=ProviderCertificationDecision(str(payload["decision"])),
        manifest_deficiencies=tuple(str(item) for item in payload["manifest_deficiencies"]),
        scenario_results=tuple(
            _scenario_result_from_payload(item) for item in payload["scenario_results"]
        ),
        required_failures=tuple(str(item) for item in payload["required_failures"]),
        warnings=tuple(str(item) for item in payload["warnings"]),
    )


def _report_hash(
    report: ProviderCertificationReport,
    payload_json: str,
    previous_hash: str,
) -> str:
    material = "\n".join(
        (
            report.identifier,
            report.provider,
            report.certified_at.isoformat(),
            payload_json,
            previous_hash,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "ProviderCapabilityManifest",
    "ProviderCertificationDecision",
    "ProviderCertificationEvent",
    "ProviderCertificationHarness",
    "ProviderCertificationIntegrityError",
    "ProviderCertificationReport",
    "ProviderCertificationScenario",
    "ProviderCertificationScenarioKind",
    "ProviderCertificationScenarioResult",
    "SQLiteProviderCertificationStore",
    "manifest_from_payload",
    "report_to_payload",
    "scenario_from_payload",
]
