"""Point-in-time, survivorship, persistence, and Version 1 universe tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from cio import CandidateInstrument
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
    SQLiteSecurityMasterStore,
    SecurityEntityType,
    SecurityMasterAction,
    SecurityMasterActionType,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
    SecurityMasterError,
    SecurityMasterIntegrityError,
    SecurityMasterMarketMetrics,
    SecurityMasterUniverseMembership,
    TradingCalendar,
    Version1UniverseBuilder,
    deserialize_security_master_catalog,
    serialize_security_master_catalog,
)
from evaluation import PointInTimeUniverseMembership


UTC = timezone.utc
LISTED = datetime(2020, 1, 2, tzinfo=UTC)
SYMBOL_ANNOUNCED = datetime(2024, 5, 15, 12, tzinfo=UTC)
SYMBOL_EFFECTIVE = datetime(2024, 6, 3, tzinfo=UTC)
DELIST_ANNOUNCED = datetime(2024, 8, 15, 12, tzinfo=UTC)
DELIST_EFFECTIVE = datetime(2024, 9, 3, tzinfo=UTC)


def authoritative_coverage() -> SecurityMasterCoverage:
    return SecurityMasterCoverage(
        source="LICENSED_REFERENCE",
        source_version="reference.v1",
        licensed=True,
        complete_universe=True,
        point_in_time=True,
        historical_identifiers=True,
        listing_history=True,
        delistings=True,
        corporate_actions=True,
        provenance_complete=True,
        service_level_defined=True,
    )


def partial_coverage() -> SecurityMasterCoverage:
    return SecurityMasterCoverage(
        source="PUBLIC_CURRENT_ONLY",
        source_version="current.v1",
        licensed=False,
        complete_universe=False,
        point_in_time=True,
        historical_identifiers=False,
        listing_history=False,
        delistings=False,
        corporate_actions=False,
        provenance_complete=True,
        service_level_defined=False,
    )


def _issuer() -> Issuer:
    return Issuer(
        issuer_id="issuer:acme",
        name="Acme Corporation",
        identifiers=(
            InstrumentIdentifier(
                IdentifierScheme.CIK,
                "1234567",
                provider="LICENSED_REFERENCE",
            ),
        ),
    )


def _instrument(
    identifier: str,
    name: str,
    asset_class: AssetClass,
    instrument_type: InstrumentType,
    *,
    issuer_id: str | None = None,
) -> Instrument:
    return Instrument(
        instrument_id=identifier,
        name=name,
        asset_class=asset_class,
        instrument_type=instrument_type,
        issuer_id=issuer_id,
    )


def catalog(*, coverage: SecurityMasterCoverage | None = None) -> SecurityMasterCatalog:
    issuer = _issuer()
    acme = _instrument(
        "instrument:acme-common",
        "Acme Corporation Class A",
        AssetClass.EQUITY,
        InstrumentType.COMMON_STOCK,
        issuer_id=issuer.issuer_id,
    )
    etf = _instrument(
        "instrument:market-etf",
        "Market ETF",
        AssetClass.ETF,
        InstrumentType.FUND,
    )
    treasury = _instrument(
        "instrument:treasury-bill",
        "Three Month Treasury Bill",
        AssetClass.FIXED_INCOME,
        InstrumentType.BOND,
    )
    crypto = _instrument(
        "instrument:bitcoin",
        "Bitcoin / U.S. Dollar",
        AssetClass.CRYPTO,
        InstrumentType.OTHER,
    )
    instruments = (acme, etf, treasury, crypto)
    records = tuple(
        InstrumentRecord(
            record_identifier=f"record:{item.instrument_id}",
            instrument=item,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier=f"reference:{item.instrument_id}",
        )
        for item in instruments
    )
    listings = (
        ListingRecord(
            record_identifier="record:listing:acme:original",
            listing_identifier="listing:acme:primary",
            instrument_identifier=acme.instrument_id,
            venue="NASDAQ",
            symbol="OLD",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier="reference:acme:original",
        ),
        ListingRecord(
            record_identifier="record:listing:acme:old-closed",
            listing_identifier="listing:acme:primary",
            instrument_identifier=acme.instrument_id,
            venue="NASDAQ",
            symbol="OLD",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=SYMBOL_EFFECTIVE,
            available_at=SYMBOL_ANNOUNCED,
            source_identifier="reference:acme:symbol-change",
        ),
        ListingRecord(
            record_identifier="record:listing:acme:new-open",
            listing_identifier="listing:acme:primary",
            instrument_identifier=acme.instrument_id,
            venue="NYSE",
            symbol="NEW",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=SYMBOL_EFFECTIVE,
            effective_until=None,
            available_at=SYMBOL_ANNOUNCED,
            source_identifier="reference:acme:symbol-change",
        ),
        ListingRecord(
            record_identifier="record:listing:acme:new-closed",
            listing_identifier="listing:acme:primary",
            instrument_identifier=acme.instrument_id,
            venue="NYSE",
            symbol="NEW",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=SYMBOL_EFFECTIVE,
            effective_until=DELIST_EFFECTIVE,
            available_at=DELIST_ANNOUNCED,
            source_identifier="reference:acme:delisting",
        ),
        ListingRecord(
            record_identifier="record:listing:acme:zz-delisted",
            listing_identifier="listing:acme:primary",
            instrument_identifier=acme.instrument_id,
            venue="NYSE",
            symbol="NEW",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.DELISTED,
            primary=True,
            effective_from=DELIST_EFFECTIVE,
            effective_until=None,
            available_at=DELIST_ANNOUNCED + timedelta(minutes=1),
            source_identifier="reference:acme:delisting",
        ),
        ListingRecord(
            record_identifier="record:listing:etf",
            listing_identifier="listing:etf:primary",
            instrument_identifier=etf.instrument_id,
            venue="NYSEARCA",
            symbol="MKT",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier="reference:etf",
        ),
        ListingRecord(
            record_identifier="record:listing:treasury",
            listing_identifier="listing:treasury:primary",
            instrument_identifier=treasury.instrument_id,
            venue="NYSEARCA",
            symbol="TBIL",
            country_code="US",
            trading_calendar=TradingCalendar.EXCHANGE,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier="reference:treasury",
        ),
        ListingRecord(
            record_identifier="record:listing:crypto",
            listing_identifier="listing:crypto:primary",
            instrument_identifier=crypto.instrument_id,
            venue="COINBASE",
            symbol="BTC-USD",
            country_code="US",
            trading_calendar=TradingCalendar.CONTINUOUS,
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier="reference:crypto",
        ),
    )
    return SecurityMasterCatalog(
        identifier="security-master:licensed:v1",
        version="security-master.v1",
        issuers=(
            IssuerRecord(
                record_identifier="record:issuer:acme",
                issuer=issuer,
                effective_from=LISTED,
                effective_until=None,
                available_at=LISTED,
                source_identifier="reference:issuer:acme",
            ),
        ),
        instruments=records,
        identifiers=(
            IdentifierAssignment(
                record_identifier="record:identifier:acme-cik",
                assignment_identifier="assignment:acme-cik",
                entity_type=SecurityEntityType.ISSUER,
                entity_identifier=issuer.issuer_id,
                identifier=issuer.identifiers[0],
                effective_from=LISTED,
                effective_until=None,
                available_at=LISTED,
                source_identifier="reference:issuer:acme:cik",
            ),
        ),
        listings=listings,
        actions=(
            SecurityMasterAction(
                record_identifier="record:action:acme-symbol",
                action_identifier="action:acme-symbol",
                instrument_identifier=acme.instrument_id,
                action_type=SecurityMasterActionType.SYMBOL_CHANGE,
                announced_at=SYMBOL_ANNOUNCED,
                effective_at=SYMBOL_EFFECTIVE,
                available_at=SYMBOL_ANNOUNCED,
                source_identifier="reference:action:acme-symbol",
                new_symbol="NEW",
            ),
            SecurityMasterAction(
                record_identifier="record:action:acme-delist",
                action_identifier="action:acme-delist",
                instrument_identifier=acme.instrument_id,
                action_type=SecurityMasterActionType.DELISTING,
                announced_at=DELIST_ANNOUNCED,
                effective_at=DELIST_EFFECTIVE,
                available_at=DELIST_ANNOUNCED,
                source_identifier="reference:action:acme-delist",
            ),
        ),
        coverage=coverage or authoritative_coverage(),
    )


def metrics(as_of: datetime) -> tuple[SecurityMasterMarketMetrics, ...]:
    observed = as_of - timedelta(hours=1)
    return (
        SecurityMasterMarketMetrics(
            identifier="metric:acme",
            instrument_identifier="instrument:acme-common",
            observed_at=observed,
            available_at=observed,
            average_daily_dollar_volume=25_000_000,
            analytical_coverage=0.95,
        ),
        SecurityMasterMarketMetrics(
            identifier="metric:etf",
            instrument_identifier="instrument:market-etf",
            observed_at=observed,
            available_at=observed,
            average_daily_dollar_volume=100_000_000,
            analytical_coverage=0.90,
        ),
        SecurityMasterMarketMetrics(
            identifier="metric:treasury",
            instrument_identifier="instrument:treasury-bill",
            observed_at=observed,
            available_at=observed,
            average_daily_dollar_volume=50_000_000,
            analytical_coverage=0.99,
            is_us_treasury=True,
            effective_duration_years=0.25,
        ),
        SecurityMasterMarketMetrics(
            identifier="metric:crypto",
            instrument_identifier="instrument:bitcoin",
            observed_at=observed,
            available_at=observed,
            average_daily_dollar_volume=500_000_000,
            analytical_coverage=0.99,
        ),
    )


def test_symbol_and_venue_history_resolve_at_each_decision_boundary() -> None:
    value = catalog()

    old = value.snapshot(as_of=datetime(2024, 5, 1, tzinfo=UTC))
    new = value.snapshot(as_of=datetime(2024, 7, 1, tzinfo=UTC))

    assert old.resolve_symbol("OLD", venue="NASDAQ").instrument_id == (
        "instrument:acme-common"
    )
    with pytest.raises(SecurityMasterError, match="not active"):
        old.resolve_symbol("NEW")
    assert new.resolve_symbol("NEW", venue="NYSE").instrument_id == (
        "instrument:acme-common"
    )
    with pytest.raises(SecurityMasterError, match="not active"):
        new.resolve_symbol("OLD")


def test_knowledge_cutoff_preserves_later_corrections_without_rewriting_history() -> None:
    value = catalog()
    as_of = datetime(2024, 5, 1, tzinfo=UTC)

    original = value.snapshot(as_of=as_of, knowledge_cutoff=as_of)
    corrected = value.snapshot(
        as_of=as_of,
        knowledge_cutoff=datetime(2024, 5, 20, tzinfo=UTC),
    )

    assert original.listings[0].record_identifier == "record:listing:acme:original"
    assert corrected.listings[0].record_identifier == "record:listing:acme:old-closed"
    assert original.resolve_symbol("OLD") == corrected.resolve_symbol("OLD")


def test_delisted_security_remains_in_historical_universe_but_not_future_snapshot() -> None:
    value = catalog()
    before = value.snapshot(as_of=datetime(2024, 8, 1, tzinfo=UTC))
    after = value.snapshot(as_of=datetime(2024, 10, 1, tzinfo=UTC))

    assert before.resolve_symbol("NEW").instrument_id == "instrument:acme-common"
    with pytest.raises(SecurityMasterError, match="not active"):
        after.resolve_symbol("NEW")
    assert any(
        item.action_type is SecurityMasterActionType.DELISTING
        for item in after.actions
    )


def test_version1_builder_creates_reproducible_structural_memberships() -> None:
    as_of = datetime(2024, 7, 1, tzinfo=UTC)
    master = catalog().snapshot(as_of=as_of, require_authoritative=True)

    universe = Version1UniverseBuilder().build(
        master,
        metrics(as_of),
        require_authoritative=True,
    )

    assert universe.authoritative is True
    assert [item.instrument.symbol for item in universe.constituents] == [
        "MKT",
        "NEW",
        "TBIL",
    ]
    acme = next(
        item for item in universe.constituents if item.instrument.symbol == "NEW"
    )
    assert acme.instrument.security_master_snapshot_identifier == master.identifier
    assert acme.instrument.security_master_record_identifiers == (
        "record:instrument:acme-common",
        "record:listing:acme:new-open",
    )
    assert acme.membership.eligible_from == SYMBOL_EFFECTIVE
    assert acme.membership.contains(as_of)
    walk_forward = acme.membership.to_walk_forward()
    assert isinstance(walk_forward, PointInTimeUniverseMembership)
    assert walk_forward.contains(as_of)
    crypto = next(item for item in universe.exclusions if item.symbol == "BTC-USD")
    assert "intelligence-only" in crypto.reasons[0]


def test_builder_excludes_missing_or_stale_dynamic_qualification_data() -> None:
    as_of = datetime(2024, 7, 1, tzinfo=UTC)
    master = catalog().snapshot(as_of=as_of)
    values = tuple(
        item
        for item in metrics(as_of)
        if item.instrument_identifier != "instrument:market-etf"
    )
    values = tuple(
        SecurityMasterMarketMetrics(
            identifier=item.identifier,
            instrument_identifier=item.instrument_identifier,
            observed_at=(
                as_of - timedelta(hours=30)
                if item.instrument_identifier == "instrument:acme-common"
                else item.observed_at
            ),
            available_at=(
                as_of - timedelta(hours=30)
                if item.instrument_identifier == "instrument:acme-common"
                else item.available_at
            ),
            average_daily_dollar_volume=item.average_daily_dollar_volume,
            analytical_coverage=item.analytical_coverage,
            is_us_treasury=item.is_us_treasury,
            effective_duration_years=item.effective_duration_years,
        )
        for item in values
    )

    universe = Version1UniverseBuilder().build(master, values)

    reasons = {
        item.instrument_identifier: item.reasons for item in universe.exclusions
    }
    assert "market data is older" in reasons["instrument:acme-common"][0]
    assert "liquidity and analytical coverage" in reasons["instrument:market-etf"][0]


def test_partial_coverage_cannot_be_mislabeled_authoritative() -> None:
    value = catalog(coverage=partial_coverage())

    snapshot = value.snapshot(as_of=datetime(2024, 7, 1, tzinfo=UTC))
    assert snapshot.coverage.authoritative is False
    assert "licensed source" in snapshot.coverage.deficiencies
    with pytest.raises(SecurityMasterError, match="not authoritative"):
        value.snapshot(
            as_of=datetime(2024, 7, 1, tzinfo=UTC),
            require_authoritative=True,
        )


def test_market_metrics_reject_lookahead_availability() -> None:
    as_of = datetime(2024, 7, 1, tzinfo=UTC)
    master = catalog().snapshot(as_of=as_of)
    future = SecurityMasterMarketMetrics(
        identifier="metric:future",
        instrument_identifier="instrument:acme-common",
        observed_at=as_of,
        available_at=as_of + timedelta(minutes=1),
        average_daily_dollar_volume=20_000_000,
        analytical_coverage=0.90,
    )

    with pytest.raises(ValueError, match="unavailable"):
        Version1UniverseBuilder().build(master, (future,))


def test_catalog_serialization_round_trip_preserves_temporal_identity() -> None:
    value = catalog()

    restored = deserialize_security_master_catalog(
        serialize_security_master_catalog(value)
    )

    assert restored == value
    assert restored.snapshot(as_of=datetime(2024, 7, 1, tzinfo=UTC)).resolve_symbol(
        "NEW"
    ).instrument_id == "instrument:acme-common"


def test_sqlite_store_is_idempotent_hash_chained_and_append_only(tmp_path) -> None:
    path = tmp_path / "security-master.db"
    store = SQLiteSecurityMasterStore(path)
    first_catalog = catalog()
    first = store.append(
        first_catalog,
        recorded_at=datetime(2024, 7, 1, 1, tzinfo=UTC),
    )
    repeated = store.append(
        first_catalog,
        recorded_at=datetime(2024, 7, 1, 2, tzinfo=UTC),
    )
    second_catalog = SecurityMasterCatalog(
        identifier="security-master:licensed:v2",
        version="security-master.v2",
        issuers=first_catalog.issuers,
        instruments=first_catalog.instruments,
        identifiers=first_catalog.identifiers,
        listings=first_catalog.listings,
        actions=first_catalog.actions,
        coverage=first_catalog.coverage,
    )
    second = store.append(
        second_catalog,
        recorded_at=datetime(2024, 7, 2, 1, tzinfo=UTC),
    )

    assert repeated == first
    assert second.previous_hash == first.content_hash
    assert store.latest() == second_catalog
    assert store.verify_integrity() is True
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE security_master_catalogs SET catalog_version = 'bad' WHERE sequence = 1"
            )


def test_integrity_verification_detects_out_of_band_tampering(tmp_path) -> None:
    path = tmp_path / "security-master.db"
    store = SQLiteSecurityMasterStore(path)
    store.append(
        catalog(),
        recorded_at=datetime(2024, 7, 1, 1, tzinfo=UTC),
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER security_master_catalogs_no_update")
        connection.execute(
            "UPDATE security_master_catalogs SET payload_json = '{}' WHERE sequence = 1"
        )

    with pytest.raises(SecurityMasterIntegrityError, match="content hash"):
        store.verify_integrity()


def test_candidate_instrument_requires_security_master_lineage() -> None:
    with pytest.raises(TypeError):
        CandidateInstrument(  # type: ignore[call-arg]
            instrument_id="instrument:missing-lineage",
            symbol="MISS",
            name="Missing Lineage",
            asset_class="us_equity",  # type: ignore[arg-type]
            venue="NASDAQ",
            country_code="US",
            average_daily_dollar_volume=10_000_000,
            data_age_hours=1.0,
            analytical_coverage=0.90,
        )


def test_membership_interval_rejects_invalid_boundaries() -> None:
    with pytest.raises(ValueError, match="follow"):
        SecurityMasterUniverseMembership(
            symbol="ACME",
            eligible_from=LISTED,
            eligible_until=LISTED,
            source_identifier="fixture",
        )
