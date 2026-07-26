"""Operational security-master ingestion, reconciliation, and activation tests."""

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
    ReconciledSecurityMasterProvider,
    ProviderCertificationDecision,
    ProviderCertificationReport,
    SQLiteProviderCertificationStore,
    SQLiteSecurityMasterOperationalStore,
    SQLiteSecurityMasterStore,
    SecurityEntityType,
    SecurityMasterActivationError,
    SecurityMasterActivationMode,
    SecurityMasterActivationPolicy,
    SecurityMasterCatalog,
    SecurityMasterCatalogDelivery,
    SecurityMasterCoverage,
    SecurityMasterIngestionDisposition,
    SecurityMasterIngestionQuery,
    SecurityMasterIngestionService,
    SecurityMasterIntegrityError,
    SecurityMasterError,
    SecurityMasterOperationType,
    SecurityMasterProviderError,
    SecurityMasterReconciliationError,
    SecurityMasterReconciliationPolicy,
    SecurityMasterReconciler,
    TradingCalendar,
)


UTC = timezone.utc
AS_OF = datetime(2026, 7, 26, 16, tzinfo=UTC)
REQUESTED = AS_OF + timedelta(hours=1)
LISTED = datetime(2020, 1, 2, tzinfo=UTC)


def coverage(source: str, *, authoritative: bool) -> SecurityMasterCoverage:
    return SecurityMasterCoverage(
        source=source,
        source_version=f"{source.lower()}.v1",
        licensed=authoritative,
        complete_universe=authoritative,
        point_in_time=True,
        historical_identifiers=authoritative,
        listing_history=authoritative,
        delistings=authoritative,
        corporate_actions=authoritative,
        provenance_complete=True,
        service_level_defined=authoritative,
    )


def catalog(
    source: str = "LICENSED_A",
    *,
    authoritative: bool = True,
    available_at: datetime = AS_OF,
    identifier: str | None = None,
) -> SecurityMasterCatalog:
    issuer = Issuer(
        issuer_id="issuer:acme",
        name="Acme Corporation",
        identifiers=(
            InstrumentIdentifier(
                IdentifierScheme.CIK,
                "1234567",
                provider=source,
            ),
        ),
    )
    instrument = Instrument(
        instrument_id="instrument:acme-common",
        name="Acme Corporation Class A",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
        issuer_id=issuer.issuer_id,
        identifiers=(
            InstrumentIdentifier(
                IdentifierScheme.FIGI,
                "BBG000000001",
                provider=source,
            ),
        ),
    )
    catalog_identifier = identifier or f"security-master:{source.lower()}:20260726"
    return SecurityMasterCatalog(
        identifier=catalog_identifier,
        version="security-master.v1",
        coverage=coverage(source, authoritative=authoritative),
        issuers=(
            IssuerRecord(
                record_identifier=f"{source}:issuer",
                issuer=issuer,
                effective_from=LISTED,
                effective_until=None,
                available_at=available_at,
                source_identifier=f"{source}:issuer:source",
            ),
        ),
        instruments=(
            InstrumentRecord(
                record_identifier=f"{source}:instrument",
                instrument=instrument,
                effective_from=LISTED,
                effective_until=None,
                available_at=available_at,
                source_identifier=f"{source}:instrument:source",
            ),
        ),
        identifiers=(
            IdentifierAssignment(
                record_identifier=f"{source}:identifier",
                assignment_identifier="assignment:acme-figi",
                entity_type=SecurityEntityType.INSTRUMENT,
                entity_identifier=instrument.instrument_id,
                identifier=instrument.identifiers[0],
                effective_from=LISTED,
                effective_until=None,
                available_at=available_at,
                source_identifier=f"{source}:identifier:source",
            ),
        ),
        listings=(
            ListingRecord(
                record_identifier=f"{source}:listing",
                listing_identifier="listing:acme:primary",
                instrument_identifier=instrument.instrument_id,
                venue="NASDAQ",
                symbol="ACME",
                country_code="US",
                trading_calendar=TradingCalendar.EXCHANGE,
                status=ListingStatus.ACTIVE,
                primary=True,
                effective_from=LISTED,
                effective_until=None,
                available_at=available_at,
                source_identifier=f"{source}:listing:source",
            ),
        ),
        actions=(),
    )


class StaticProvider:
    def __init__(
        self,
        value: SecurityMasterCatalog,
        *,
        name: str | None = None,
    ) -> None:
        self.value = value
        self._name = name or value.coverage.source

    @property
    def name(self) -> str:
        return self._name

    def fetch_security_master_delivery(
        self,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterCatalogDelivery:
        return SecurityMasterCatalogDelivery(
            catalog=self.value,
            observed_at=self.value.instruments[0].available_at,
            retrieved_at=self.value.instruments[0].available_at,
            request_identifier=query.identifier,
        )


class FailingProvider:
    @property
    def name(self) -> str:
        return "FAIL"

    def fetch_security_master_delivery(
        self,
        query: SecurityMasterIngestionQuery,
    ) -> SecurityMasterCatalogDelivery:
        raise RuntimeError("provider unavailable")


def query(
    identifier: str = "daily-20260726",
    *,
    mode: SecurityMasterActivationMode = (
        SecurityMasterActivationMode.ACTIVATE_IF_ELIGIBLE
    ),
) -> SecurityMasterIngestionQuery:
    return SecurityMasterIngestionQuery(
        identifier=identifier,
        as_of=AS_OF,
        knowledge_cutoff=AS_OF,
        requested_at=REQUESTED,
        activation_mode=mode,
    )


def approved_certification(provider: str) -> ProviderCertificationReport:
    return ProviderCertificationReport(
        identifier=f"certification:{provider.lower()}:approved",
        provider=provider,
        product="Test Security Master",
        manifest_version="manifest.v1",
        source_version="test.v1",
        certified_at=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=365),
        decision=ProviderCertificationDecision.APPROVED,
        manifest_deficiencies=(),
        scenario_results=(),
        required_failures=(),
        warnings=(),
    )


def service(
    tmp_path,
    *,
    policy=None,
    certified_provider: str | None = "LICENSED_A",
) -> SecurityMasterIngestionService:
    path = tmp_path / "security-master.db"
    certification_store = SQLiteProviderCertificationStore(path)
    if certified_provider is not None:
        certification_store.append(approved_certification(certified_provider))
    return SecurityMasterIngestionService(
        SQLiteSecurityMasterStore(path),
        SQLiteSecurityMasterOperationalStore(path),
        activation_policy=policy,
        certification_store=certification_store,
    )


def test_authoritative_catalog_is_activated_and_retrievable(tmp_path) -> None:
    ingestion = service(tmp_path)

    result = ingestion.ingest(StaticProvider(catalog()), query())

    assert result.disposition is SecurityMasterIngestionDisposition.ACTIVATED
    assert result.quality.activatable is True
    assert result.activation_identifier == "daily-20260726"
    assert ingestion.active_catalog(evaluated_at=REQUESTED).identifier == result.catalog_identifier
    assert ingestion.operational_store.verify_integrity() is True
    assert tuple(
        item.operation_type for item in ingestion.operational_store.events()
    ) == (
        SecurityMasterOperationType.INGESTION,
        SecurityMasterOperationType.ACTIVATION,
    )




def test_activation_requires_current_approved_provider_certification(tmp_path) -> None:
    ingestion = service(tmp_path, certified_provider=None)

    result = ingestion.ingest(StaticProvider(catalog()), query())

    assert result.disposition is SecurityMasterIngestionDisposition.STORED_NOT_ACTIVATED
    assert result.quality.certification_identifier is None
    assert any("certification is missing" in item for item in result.reasons)


def test_later_rejected_certification_revokes_active_catalog(tmp_path) -> None:
    ingestion = service(tmp_path)
    ingestion.ingest(StaticProvider(catalog()), query())
    rejected = ProviderCertificationReport(
        identifier="certification:licensed_a:revoked",
        provider="LICENSED_A",
        product="Test Security Master",
        manifest_version="manifest.v2",
        source_version="test.v2",
        certified_at=REQUESTED + timedelta(hours=1),
        valid_until=REQUESTED + timedelta(days=365),
        decision=ProviderCertificationDecision.REJECTED,
        manifest_deficiencies=("commercial license is not verified",),
        scenario_results=(),
        required_failures=(),
        warnings=(),
    )
    ingestion.certification_store.append(rejected)

    with pytest.raises(SecurityMasterError, match="not approved"):
        ingestion.active_catalog(evaluated_at=rejected.certified_at)


def test_active_catalog_expires_without_mutating_activation_history(tmp_path) -> None:
    ingestion = service(
        tmp_path,
        policy=SecurityMasterActivationPolicy(maximum_catalog_age_hours=24.0),
    )
    ingestion.ingest(StaticProvider(catalog()), query())

    status = ingestion.status(evaluated_at=AS_OF + timedelta(hours=25))

    assert status.screening_ready is False
    assert status.active_catalog_identifier is not None
    assert status.active_source_age_hours == 25.0
    assert any("stale" in item for item in status.reasons)
    assert len(
        ingestion.operational_store.events(SecurityMasterOperationType.ACTIVATION)
    ) == 1
    with pytest.raises(SecurityMasterError, match="stale"):
        ingestion.active_catalog(evaluated_at=AS_OF + timedelta(hours=25))


def test_status_exposes_latest_non_authoritative_ingestion(tmp_path) -> None:
    ingestion = service(tmp_path)
    ingestion.ingest(
        StaticProvider(catalog("SEC_EDGAR", authoritative=False)),
        query(),
    )

    status = ingestion.status(evaluated_at=REQUESTED)

    assert status.screening_ready is False
    assert status.latest_ingestion is not None
    assert status.latest_ingestion.provider == "SEC_EDGAR"
    assert status.latest_activation is None
    assert status.catalog_integrity_verified is True
    assert status.operation_integrity_verified is True

def test_current_only_catalog_is_stored_but_never_activated(tmp_path) -> None:
    ingestion = service(tmp_path)
    partial = catalog("SEC_EDGAR", authoritative=False)

    result = ingestion.ingest(StaticProvider(partial), query())

    assert result.disposition is (
        SecurityMasterIngestionDisposition.STORED_NOT_ACTIVATED
    )
    assert result.quality.authoritative_coverage is False
    assert "coverage missing licensed source" in result.reasons
    assert ingestion.catalog_store.get(partial.identifier) == partial
    with pytest.raises(LookupError, match="no security-master catalog"):
        ingestion.active_catalog()


def test_required_activation_records_rejection_before_raising(tmp_path) -> None:
    ingestion = service(tmp_path)

    with pytest.raises(SecurityMasterActivationError) as captured:
        ingestion.ingest(
            StaticProvider(catalog("PUBLIC", authoritative=False)),
            query(mode=SecurityMasterActivationMode.REQUIRE_ACTIVATION),
        )

    assert captured.value.result.disposition is (
        SecurityMasterIngestionDisposition.ACTIVATION_REJECTED
    )
    events = ingestion.operational_store.events()
    assert len(events) == 1
    assert events[0].operation_type is SecurityMasterOperationType.INGESTION


def test_store_only_never_activates_even_when_catalog_is_eligible(tmp_path) -> None:
    ingestion = service(tmp_path)

    result = ingestion.ingest(
        StaticProvider(catalog()),
        query(mode=SecurityMasterActivationMode.STORE_ONLY),
    )

    assert result.disposition is SecurityMasterIngestionDisposition.STORED_ONLY
    assert result.quality.activatable is True
    assert result.reasons == ("activation was not requested",)
    assert ingestion.operational_store.latest_activation() is None


def test_stale_catalog_is_blocked_by_sla_policy(tmp_path) -> None:
    ingestion = service(
        tmp_path,
        policy=SecurityMasterActivationPolicy(maximum_catalog_age_hours=24.0),
    )
    stale = catalog(available_at=AS_OF - timedelta(hours=72))

    result = ingestion.ingest(StaticProvider(stale), query())

    assert result.disposition is (
        SecurityMasterIngestionDisposition.STORED_NOT_ACTIVATED
    )
    assert result.quality.source_age_hours == 73.0
    assert any("source observation age exceeds" in item for item in result.reasons)


def test_ingestion_is_idempotent_for_same_request_and_catalog(tmp_path) -> None:
    ingestion = service(tmp_path)
    provider = StaticProvider(catalog())
    request = query()

    first = ingestion.ingest(provider, request)
    second = ingestion.ingest(provider, request)

    assert second == first
    assert len(ingestion.catalog_store.events()) == 1
    assert len(ingestion.operational_store.events()) == 2


def test_provider_failures_and_identity_mismatch_are_typed(tmp_path) -> None:
    ingestion = service(tmp_path)
    with pytest.raises(SecurityMasterProviderError, match="FAIL failed"):
        ingestion.ingest(FailingProvider(), query())

    mismatched = StaticProvider(
        replace(
            catalog("LICENSED_A"),
            coverage=replace(catalog("LICENSED_A").coverage, source="OTHER"),
        ),
        name="LICENSED_A",
    )
    with pytest.raises(SecurityMasterProviderError, match="provider identity"):
        ingestion.ingest(mismatched, query("mismatch"))


def test_operation_store_detects_out_of_band_tampering(tmp_path) -> None:
    ingestion = service(tmp_path)
    ingestion.ingest(StaticProvider(catalog()), query())
    path = ingestion.operational_store.path
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER security_master_operations_no_update")
        connection.execute(
            "UPDATE security_master_operations SET payload_json = '{}' WHERE sequence = 1"
        )

    with pytest.raises(SecurityMasterIntegrityError, match="content hash"):
        ingestion.operational_store.verify_integrity()


def test_reconciler_deduplicates_agreeing_sources_by_explicit_priority() -> None:
    first = catalog("LICENSED_A")
    second = catalog("LICENSED_B", identifier="security-master:b")
    reconciler = SecurityMasterReconciler(
        SecurityMasterReconciliationPolicy(
            version="reconciliation.v1",
            source_priority=("LICENSED_A", "LICENSED_B"),
        )
    )

    result = reconciler.reconcile(
        (second, first),
        identifier="security-master:reconciled",
        version="security-master.reconciled.v1",
    )

    assert result.report.sources == ("LICENSED_A", "LICENSED_B")
    assert result.report.selected_record_count == 4
    assert result.report.duplicate_record_count == 4
    assert result.catalog.coverage.authoritative is True
    assert result.catalog.listings[0].record_identifier == "LICENSED_A:listing"


def test_reconciler_rejects_conflicting_overlapping_facts() -> None:
    first = catalog("LICENSED_A")
    second = catalog("LICENSED_B", identifier="security-master:b")
    second = replace(
        second,
        listings=(replace(second.listings[0], symbol="DIFFERENT"),),
    )
    reconciler = SecurityMasterReconciler(
        SecurityMasterReconciliationPolicy(
            version="reconciliation.v1",
            source_priority=("LICENSED_A", "LICENSED_B"),
        )
    )

    with pytest.raises(SecurityMasterReconciliationError, match="listing"):
        reconciler.reconcile(
            (first, second),
            identifier="security-master:reconciled",
            version="security-master.reconciled.v1",
        )


def test_reconciled_provider_can_be_ingested_when_all_sources_are_authoritative(
    tmp_path,
) -> None:
    reconciler = SecurityMasterReconciler(
        SecurityMasterReconciliationPolicy(
            version="reconciliation.v1",
            source_priority=("LICENSED_A", "LICENSED_B"),
        )
    )
    provider = ReconciledSecurityMasterProvider(
        (
            StaticProvider(catalog("LICENSED_A")),
            StaticProvider(catalog("LICENSED_B", identifier="security-master:b")),
        ),
        reconciler,
    )

    result = service(
        tmp_path, certified_provider="RECONCILED_SECURITY_MASTER"
    ).ingest(provider, query("reconciled"))

    assert result.disposition is SecurityMasterIngestionDisposition.ACTIVATED
    assert provider.last_report is not None
    assert provider.last_report.duplicate_record_count == 4


def test_future_known_records_block_activation_even_when_coverage_claims_authority(
    tmp_path,
) -> None:
    future = catalog(available_at=AS_OF + timedelta(minutes=30))

    result = service(tmp_path).ingest(StaticProvider(future), query("future"))

    assert result.disposition is (
        SecurityMasterIngestionDisposition.STORED_NOT_ACTIVATED
    )
    assert result.quality.future_known_record_count == 4
    assert any("unavailable by the knowledge cutoff" in item for item in result.reasons)


def test_query_requires_ordered_point_in_time_boundaries() -> None:
    with pytest.raises(ValueError, match="knowledge_cutoff"):
        SecurityMasterIngestionQuery(
            identifier="bad",
            as_of=AS_OF,
            knowledge_cutoff=AS_OF - timedelta(seconds=1),
            requested_at=REQUESTED,
        )
