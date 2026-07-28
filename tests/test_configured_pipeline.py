from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from cio.persistence import serialize_candidate_decision
from cio.universe import UniverseAssessment, UniverseDisposition
from data import (
    AssetClass,
    Instrument,
    InstrumentRecord,
    InstrumentType,
    ListingRecord,
    ListingStatus,
    PointInTimeSecurityMasterSnapshot,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
    SecurityMasterIngestionQuery,
    SecurityMasterMarketMetrics,
    SecurityMasterUniverseMembership,
    TradingCalendar,
    Version1UniverseConstituent,
    serialize_security_master_catalog,
)
from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.configured_pipeline import (
    ConfiguredCandidateScreeningProvider,
    ConfiguredSecurityMasterProvider,
    ConfiguredUniverseMetricsProvider,
)
from tests.cio_test_fixtures import build_candidate

UTC = timezone.utc
AS_OF = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)


class DatasetProvider:
    name = "CONFIGURED_FIXTURE"

    def __init__(self, payloads):
        self.payloads = payloads

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version="fixture.v1",
            observed_at=query.start_at or query.as_of - timedelta(minutes=2),
            available_at=query.as_of - timedelta(minutes=1),
            retrieved_at=query.as_of,
            quality_state=DataQualityState.LIVE,
            availability_basis=AvailabilityBasis.PROVIDER_TIMESTAMP,
            payload=self.payloads[query.dataset_type],
            provider_record_id=f"record:{query.dataset_type.value}",
        )


def _catalog() -> SecurityMasterCatalog:
    instrument = Instrument(
        instrument_id="instrument:acme",
        name="ACME Corporation",
        asset_class=AssetClass.EQUITY,
        instrument_type=InstrumentType.COMMON_STOCK,
    )
    return SecurityMasterCatalog(
        identifier="catalog:configured",
        version="fixture.v1",
        issuers=(),
        instruments=(
            InstrumentRecord(
                record_identifier="record:instrument:acme",
                instrument=instrument,
                effective_from=AS_OF - timedelta(days=365),
                effective_until=None,
                available_at=AS_OF - timedelta(days=2),
                source_identifier="source:configured",
            ),
        ),
        identifiers=(),
        listings=(
            ListingRecord(
                record_identifier="record:listing:acme",
                listing_identifier="listing:acme:xnys",
                instrument_identifier=instrument.instrument_id,
                venue="NYSE",
                symbol="ACME",
                country_code="US",
                trading_calendar=TradingCalendar.EXCHANGE,
                status=ListingStatus.ACTIVE,
                primary=True,
                effective_from=AS_OF - timedelta(days=365),
                effective_until=None,
                available_at=AS_OF - timedelta(days=2),
                source_identifier="source:configured",
            ),
        ),
        actions=(),
        coverage=SecurityMasterCoverage(
            source="CONFIGURED_FIXTURE",
            source_version="fixture.v1",
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


def test_configured_security_master_adapter_returns_canonical_delivery() -> None:
    provider = ConfiguredSecurityMasterProvider(
        DatasetProvider(
            {
                ProviderDatasetType.SECURITY_MASTER: (
                    serialize_security_master_catalog(_catalog())
                )
            }
        )
    )
    query = SecurityMasterIngestionQuery(
        identifier="ingestion:configured",
        as_of=AS_OF,
        knowledge_cutoff=AS_OF + timedelta(minutes=5),
        requested_at=AS_OF + timedelta(minutes=6),
    )

    delivery = provider.fetch_security_master_delivery(query)

    assert delivery.catalog.identifier == "catalog:configured"
    assert delivery.request_identifier == "record:security_master"
    assert delivery.catalog.snapshot(
        as_of=AS_OF,
        knowledge_cutoff=query.knowledge_cutoff,
        require_authoritative=True,
    ).instruments[0].instrument.instrument_id == "instrument:acme"


def test_configured_metrics_adapter_returns_point_in_time_metrics() -> None:
    catalog = _catalog()
    snapshot: PointInTimeSecurityMasterSnapshot = catalog.snapshot(
        as_of=AS_OF,
        knowledge_cutoff=AS_OF + timedelta(minutes=5),
        require_authoritative=True,
    )
    payload = [
        {
            "identifier": "metric:acme",
            "instrument_identifier": "instrument:acme",
            "observed_at": AS_OF.isoformat(),
            "available_at": (AS_OF + timedelta(minutes=1)).isoformat(),
            "average_daily_dollar_volume": 250_000_000,
            "analytical_coverage": 0.95,
        }
    ]
    provider = ConfiguredUniverseMetricsProvider(
        DatasetProvider({ProviderDatasetType.QUOTES_LIQUIDITY: payload})
    )

    metrics = provider.fetch_metrics(snapshot)

    assert metrics == (
        SecurityMasterMarketMetrics(
            identifier="metric:acme",
            instrument_identifier="instrument:acme",
            observed_at=AS_OF,
            available_at=AS_OF + timedelta(minutes=1),
            average_daily_dollar_volume=250_000_000,
            analytical_coverage=0.95,
        ),
    )


def test_configured_candidate_adapter_preserves_constituent_identity() -> None:
    candidate = build_candidate(symbol="ACME")
    candidate = replace(
        candidate,
        as_of=AS_OF,
        review_at=AS_OF + timedelta(days=30),
    )
    # The fixture uses the same canonical identity needed by the constituent.
    constituent = Version1UniverseConstituent(
        instrument=candidate.instrument,
        assessment=UniverseAssessment(
            instrument_id=candidate.instrument.instrument_id,
            disposition=UniverseDisposition.DIRECT_RECOMMENDATION,
            policy_version="recommendation-universe.v1",
            reasons=("eligible",),
        ),
        listing_identifier="listing:acme",
        metrics_identifier="metric:acme",
        membership=SecurityMasterUniverseMembership(
            symbol="ACME",
            eligible_from=AS_OF - timedelta(days=1),
            eligible_until=None,
            source_identifier="membership:acme",
        ),
    )
    provider = ConfiguredCandidateScreeningProvider(
        DatasetProvider(
            {
                ProviderDatasetType.CANDIDATE_SCREENING: {
                    "schema_version": "candidate-screening-decision.v1",
                    "candidate": serialize_candidate_decision(candidate),
                    "reasons": [],
                }
            }
        )
    )

    decision = provider.screen(
        constituent,
        as_of=AS_OF,
        opportunity_cost_return=candidate.opportunity_cost_return,
    )

    assert decision.candidate is not None
    assert decision.candidate.instrument.instrument_id == constituent.instrument.instrument_id
    assert decision.reasons == ()
