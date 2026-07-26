"""Provider certification contract and append-only registry tests."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from data import (
    AssetClass,
    IdentifierAssignment,
    IdentifierScheme,
    Instrument,
    InstrumentIdentifier,
    InstrumentRecord,
    InstrumentType,
    Issuer,
    IssuerRecord,
    ListingRecord,
    ListingStatus,
    ProviderCapabilityManifest,
    ProviderCertificationDecision,
    ProviderCertificationHarness,
    ProviderCertificationIntegrityError,
    ProviderCertificationScenario,
    ProviderCertificationScenarioKind,
    SQLiteProviderCertificationStore,
    SecurityEntityType,
    SecurityMasterAction,
    SecurityMasterActionType,
    SecurityMasterCatalog,
    SecurityMasterCatalogDelivery,
    SecurityMasterCoverage,
    SecurityMasterIngestionQuery,
    SecurityMasterActivationMode,
    TradingCalendar,
)

UTC = timezone.utc
CERTIFIED_AT = datetime(2026, 7, 26, 18, tzinfo=UTC)


def manifest(**changes) -> ProviderCapabilityManifest:
    values = dict(
        provider="LICENSED_A",
        product="Global Security Master",
        manifest_version="manifest.v1",
        source_version="licensed-a.v1",
        license_reference="contract-2026-001",
        license_verified=True,
        complete_eligible_universe=True,
        point_in_time_delivery=True,
        historical_identifiers=True,
        listing_and_venue_history=True,
        delisted_securities=True,
        corporate_actions=True,
        revision_history=True,
        provenance_complete=True,
        cross_venue_adjustment_policy="Primary listing follows effective venue history; prices remain venue-specific.",
        service_level_reference="sla-2026-001",
        maximum_delivery_age_hours=24.0,
        valid_from=CERTIFIED_AT - timedelta(days=1),
        valid_until=CERTIFIED_AT + timedelta(days=365),
    )
    values.update(changes)
    return ProviderCapabilityManifest(**values)


def catalog() -> SecurityMasterCatalog:
    issuer = Issuer(
        issuer_id="issuer:acme",
        name="Acme Corporation",
        identifiers=(
            InstrumentIdentifier(IdentifierScheme.CIK, "1234567", provider="LICENSED_A"),
        ),
    )
    successor_issuer = Issuer(
        issuer_id="issuer:successor",
        name="Acme Successor",
        identifiers=(
            InstrumentIdentifier(IdentifierScheme.CIK, "7654321", provider="LICENSED_A"),
        ),
    )
    acme = Instrument(
        instrument_id="instrument:acme",
        name="Acme Common",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
        issuer_id=issuer.issuer_id,
        identifiers=(
            InstrumentIdentifier(IdentifierScheme.FIGI, "BBG000000001", provider="LICENSED_A"),
        ),
    )
    dead = Instrument(
        instrument_id="instrument:dead",
        name="Dead Common",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
        issuer_id=issuer.issuer_id,
        identifiers=(
            InstrumentIdentifier(IdentifierScheme.FIGI, "BBG000000002", provider="LICENSED_A"),
        ),
    )
    successor = Instrument(
        instrument_id="instrument:successor",
        name="Acme Successor Common",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
        issuer_id=successor_issuer.issuer_id,
        identifiers=(
            InstrumentIdentifier(IdentifierScheme.FIGI, "BBG000000003", provider="LICENSED_A"),
        ),
    )
    start = datetime(2020, 1, 2, tzinfo=UTC)
    symbol_change = datetime(2023, 1, 3, tzinfo=UTC)
    delisting = datetime(2024, 6, 3, tzinfo=UTC)
    venue_change = datetime(2025, 1, 2, tzinfo=UTC)
    future = datetime(2026, 8, 3, tzinfo=UTC)
    issuers = (
        IssuerRecord("issuer-acme", issuer, start, None, start, "src:issuer:acme"),
        IssuerRecord("issuer-successor", successor_issuer, start, None, start, "src:issuer:successor"),
    )
    instruments = tuple(
        InstrumentRecord(
            f"record:{item.instrument_id}", item, start, None, start, f"src:{item.instrument_id}"
        )
        for item in (acme, dead, successor)
    )
    identifiers = tuple(
        IdentifierAssignment(
            record_identifier=f"identifier:{item.instrument_id}",
            assignment_identifier=f"assignment:{item.instrument_id}",
            entity_type=SecurityEntityType.INSTRUMENT,
            entity_identifier=item.instrument_id,
            identifier=item.identifiers[0],
            effective_from=start,
            effective_until=None,
            available_at=start,
            source_identifier=f"src:identifier:{item.instrument_id}",
        )
        for item in (acme, dead, successor)
    )
    listings = (
        ListingRecord(
            "listing-old", "listing:acme:old", acme.instrument_id, "NASDAQ", "OLD", "US",
            TradingCalendar.EXCHANGE, ListingStatus.ACTIVE, True, start, symbol_change,
            start, "src:listing:old",
        ),
        ListingRecord(
            "listing-acme-nasdaq", "listing:acme:nasdaq", acme.instrument_id, "NASDAQ", "ACME", "US",
            TradingCalendar.EXCHANGE, ListingStatus.ACTIVE, True, symbol_change, venue_change,
            symbol_change, "src:listing:acme:nasdaq",
        ),
        ListingRecord(
            "listing-acme-nyse", "listing:acme:nyse", acme.instrument_id, "NYSE", "ACME", "US",
            TradingCalendar.EXCHANGE, ListingStatus.ACTIVE, True, venue_change, None,
            venue_change, "src:listing:acme:nyse",
        ),
        ListingRecord(
            "listing-dead-active", "listing:dead:active", dead.instrument_id, "NYSE", "DEAD", "US",
            TradingCalendar.EXCHANGE, ListingStatus.ACTIVE, True, start, delisting,
            start, "src:listing:dead:active",
        ),
        ListingRecord(
            "listing-dead-delisted", "listing:dead:delisted", dead.instrument_id, "NYSE", "DEAD", "US",
            TradingCalendar.EXCHANGE, ListingStatus.DELISTED, True, delisting, None,
            delisting, "src:listing:dead:delisted",
        ),
        ListingRecord(
            "listing-future", "listing:successor:future", successor.instrument_id, "NASDAQ", "FUTR", "US",
            TradingCalendar.EXCHANGE, ListingStatus.ACTIVE, True, future, None,
            datetime(2026, 7, 30, tzinfo=UTC), "src:listing:future",
        ),
    )
    actions = (
        SecurityMasterAction(
            "action-symbol", "action:acme:symbol", acme.instrument_id,
            SecurityMasterActionType.SYMBOL_CHANGE, symbol_change - timedelta(days=10),
            symbol_change, symbol_change - timedelta(days=10), "src:action:symbol", new_symbol="ACME",
        ),
        SecurityMasterAction(
            "action-venue", "action:acme:venue", acme.instrument_id,
            SecurityMasterActionType.VENUE_CHANGE, venue_change - timedelta(days=10),
            venue_change, venue_change - timedelta(days=10), "src:action:venue", new_venue="NYSE",
        ),
        SecurityMasterAction(
            "action-delisting", "action:dead:delisting", dead.instrument_id,
            SecurityMasterActionType.DELISTING, delisting - timedelta(days=30),
            delisting, delisting - timedelta(days=30), "src:action:delisting",
        ),
        SecurityMasterAction(
            "action-merger", "action:acme:merger", acme.instrument_id,
            SecurityMasterActionType.MERGER, datetime(2026, 6, 1, tzinfo=UTC),
            datetime(2026, 7, 15, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC), "src:action:merger",
            successor_instrument_identifier=successor.instrument_id, ratio=1.0,
        ),
        SecurityMasterAction(
            "action-spinoff", "action:acme:spinoff", acme.instrument_id,
            SecurityMasterActionType.SPINOFF, datetime(2026, 5, 1, tzinfo=UTC),
            datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 5, 1, tzinfo=UTC),
            "src:action:spinoff", successor_instrument_identifier=successor.instrument_id, ratio=0.2,
        ),
    )
    return SecurityMasterCatalog(
        identifier="catalog:licensed-a",
        version="security-master.v1",
        issuers=issuers,
        instruments=instruments,
        identifiers=identifiers,
        listings=listings,
        actions=actions,
        coverage=SecurityMasterCoverage(
            source="LICENSED_A",
            source_version="licensed-a.v1",
            licensed=True,
            complete_universe=True,
            point_in_time=True,
            historical_identifiers=True,
            listing_history=True,
            delistings=True,
            corporate_actions=True,
            provenance_complete=True,
            service_level_defined=True,
        ),
    )


class StaticProvider:
    name = "LICENSED_A"

    def __init__(self, value: SecurityMasterCatalog | None = None) -> None:
        self.value = value or catalog()

    def fetch_security_master_delivery(self, query: SecurityMasterIngestionQuery) -> SecurityMasterCatalogDelivery:
        return SecurityMasterCatalogDelivery(
            catalog=self.value,
            observed_at=query.requested_at - timedelta(hours=1),
            retrieved_at=query.requested_at,
            request_identifier=query.identifier,
        )


def query(identifier: str, as_of: datetime, cutoff: datetime) -> SecurityMasterIngestionQuery:
    return SecurityMasterIngestionQuery(
        identifier=identifier,
        as_of=as_of,
        knowledge_cutoff=cutoff,
        requested_at=CERTIFIED_AT,
        activation_mode=SecurityMasterActivationMode.STORE_ONLY,
    )


def required_scenarios() -> tuple[ProviderCertificationScenario, ...]:
    return (
        ProviderCertificationScenario(
            "historical-symbol", ProviderCertificationScenarioKind.HISTORICAL_IDENTITY,
            "Historical symbol must be reproduced.",
            query("historical-symbol", datetime(2022, 6, 1, tzinfo=UTC), datetime(2022, 6, 1, tzinfo=UTC)),
            expected_symbols=("OLD",), excluded_symbols=("ACME", "FUTR"),
            expected_listings=(("OLD", "NASDAQ", ListingStatus.ACTIVE),),
        ),
        ProviderCertificationScenario(
            "symbol-change", ProviderCertificationScenarioKind.SYMBOL_CHANGE,
            "Symbol change must be effective at the correct boundary.",
            query("symbol-change", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)),
            expected_symbols=("ACME",), excluded_symbols=("OLD",),
            expected_action_types=(SecurityMasterActionType.SYMBOL_CHANGE,),
        ),
        ProviderCertificationScenario(
            "venue-change", ProviderCertificationScenarioKind.VENUE_CHANGE,
            "Venue history must preserve the effective listing.",
            query("venue-change", datetime(2025, 2, 1, tzinfo=UTC), datetime(2025, 2, 1, tzinfo=UTC)),
            expected_listings=(("ACME", "NYSE", ListingStatus.ACTIVE),),
            expected_action_types=(SecurityMasterActionType.VENUE_CHANGE,),
        ),
        ProviderCertificationScenario(
            "delisting", ProviderCertificationScenarioKind.DELISTING,
            "Delisted securities must remain historically visible.",
            query("delisting", datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC)),
            expected_listings=(("DEAD", "NYSE", ListingStatus.DELISTED),),
            expected_action_types=(SecurityMasterActionType.DELISTING,),
        ),
        ProviderCertificationScenario(
            "corporate-actions", ProviderCertificationScenarioKind.MERGER,
            "Merger and spinoff lineage must be available before the current boundary.",
            query("corporate-actions", datetime(2026, 7, 26, tzinfo=UTC), datetime(2026, 7, 26, tzinfo=UTC)),
            expected_action_types=(SecurityMasterActionType.MERGER, SecurityMasterActionType.SPINOFF),
            excluded_symbols=("FUTR",), minimum_instrument_count=3,
        ),
        ProviderCertificationScenario(
            "full-universe", ProviderCertificationScenarioKind.FULL_UNIVERSE_COVERAGE,
            "The acceptance sample must meet the declared population floor.",
            query("full-universe", datetime(2026, 7, 26, tzinfo=UTC), datetime(2026, 7, 26, tzinfo=UTC)),
            minimum_instrument_count=3,
        ),
    )


def approved_report():
    return ProviderCertificationHarness().certify(
        StaticProvider(), manifest(), required_scenarios(),
        identifier="certification:licensed-a:20260726", certified_at=CERTIFIED_AT,
    )


def test_complete_provider_is_approved() -> None:
    report = approved_report()

    assert report.decision is ProviderCertificationDecision.APPROVED
    assert report.required_failures == ()
    assert all(item.passed for item in report.scenario_results)


def test_manifest_deficiency_rejects_provider_without_running_around_contract() -> None:
    report = ProviderCertificationHarness().certify(
        StaticProvider(), manifest(license_verified=False), required_scenarios(),
        identifier="certification:rejected", certified_at=CERTIFIED_AT,
    )

    assert report.decision is ProviderCertificationDecision.REJECTED
    assert "commercial license is not verified" in report.manifest_deficiencies


def test_optional_scenario_failure_is_conditional_not_approved() -> None:
    optional = ProviderCertificationScenario(
        "optional-missing", ProviderCertificationScenarioKind.CURRENT_IDENTITY,
        "Optional symbol sample.",
        query("optional-missing", datetime(2026, 7, 26, tzinfo=UTC), datetime(2026, 7, 26, tzinfo=UTC)),
        required=False, expected_symbols=("MISSING",),
    )
    report = ProviderCertificationHarness().certify(
        StaticProvider(), manifest(), (*required_scenarios(), optional),
        identifier="certification:conditional", certified_at=CERTIFIED_AT,
    )

    assert report.decision is ProviderCertificationDecision.CONDITIONALLY_APPROVED
    assert report.required_failures == ()
    assert report.warnings


def test_future_known_listing_is_excluded_by_cutoff() -> None:
    report = approved_report()
    corporate = next(item for item in report.scenario_results if item.scenario_identifier == "corporate-actions")

    assert corporate.passed is True


def test_registry_is_append_only_idempotent_and_expires(tmp_path) -> None:
    store = SQLiteProviderCertificationStore(tmp_path / "certification.db")
    report = approved_report()

    first = store.append(report)
    repeated = store.append(report)

    assert first.content_hash == repeated.content_hash
    assert store.require_approved("licensed_a", evaluated_at=CERTIFIED_AT).identifier == report.identifier
    with pytest.raises(Exception, match="expired"):
        store.require_approved("LICENSED_A", evaluated_at=report.valid_until + timedelta(seconds=1))
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE provider_certifications SET provider = 'X'")


def test_registry_detects_tampering(tmp_path) -> None:
    store = SQLiteProviderCertificationStore(tmp_path / "certification.db")
    store.append(approved_report())
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER provider_certifications_no_update")
        connection.execute("UPDATE provider_certifications SET content_hash = 'tampered'")

    with pytest.raises(ProviderCertificationIntegrityError, match="content hash"):
        store.verify_integrity()


def test_latest_rejected_report_revokes_prior_approval(tmp_path) -> None:
    store = SQLiteProviderCertificationStore(tmp_path / "certification.db")
    approved = approved_report()
    store.append(approved)
    rejected = ProviderCertificationHarness().certify(
        StaticProvider(), manifest(license_verified=False), required_scenarios(),
        identifier="certification:revoked", certified_at=CERTIFIED_AT + timedelta(days=1),
    )
    store.append(rejected)

    with pytest.raises(Exception, match="not approved"):
        store.require_approved("LICENSED_A", evaluated_at=rejected.certified_at)
