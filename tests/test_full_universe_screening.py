"""Complete-universe orchestration, retry, publication, and integrity tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from cio import CandidateDecisionRecord, EvidenceQuality
from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from data import (
    AssetClass,
    Instrument,
    InstrumentRecord,
    InstrumentType,
    ListingRecord,
    ListingStatus,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
    SecurityMasterMarketMetrics,
    TradingCalendar,
)
from operations import FullUniverseCycleStatus, SQLiteOperationalSLOStore
from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext
from screening import (
    CandidateScreeningDecision,
    FullUniverseScreeningError,
    FullUniverseScreeningOrchestrator,
    FullUniverseScreeningRequest,
    SQLiteFullUniverseScreeningStore,
    ScreeningEventType,
)


UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 12, tzinfo=UTC)
LISTED = datetime(2020, 1, 2, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = AS_OF) -> None:
        self.value = start

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class ActiveCatalogService:
    def __init__(self, value: SecurityMasterCatalog | Exception) -> None:
        self.value = value

    def active_catalog(self, *, evaluated_at: datetime):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class MetricsProvider:
    name = "TEST_METRICS"

    def __init__(self, metrics: tuple[SecurityMasterMarketMetrics, ...]) -> None:
        self.metrics = metrics
        self.calls = 0

    def fetch_metrics(self, snapshot):
        self.calls += 1
        return self.metrics


class CandidateProvider:
    name = "TEST_CANDIDATES"

    def __init__(
        self,
        *,
        exclude: tuple[str, ...] = ("instrument:bbb",),
        failures: dict[str, int] | None = None,
    ) -> None:
        self.exclude = set(exclude)
        self.failures = dict(failures or {})
        self.calls: list[str] = []

    def screen(self, constituent, *, as_of, opportunity_cost_return):
        instrument_id = constituent.instrument.instrument_id
        self.calls.append(instrument_id)
        remaining = self.failures.get(instrument_id, 0)
        if remaining > 0:
            self.failures[instrument_id] = remaining - 1
            raise RuntimeError(f"temporary failure for {instrument_id}")
        if instrument_id in self.exclude:
            return CandidateScreeningDecision(
                candidate=None,
                reasons=("fundamental coverage is insufficient",),
            )
        return CandidateScreeningDecision(
            candidate=_candidate(
                constituent.instrument,
                as_of=as_of,
                opportunity_cost_return=opportunity_cost_return,
            )
        )


def _coverage() -> SecurityMasterCoverage:
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


def _catalog() -> SecurityMasterCatalog:
    instruments = (
        Instrument(
            instrument_id="instrument:aaa",
            name="AAA Corporation",
            asset_class=AssetClass.EQUITY,
            instrument_type=InstrumentType.COMMON_STOCK,
        ),
        Instrument(
            instrument_id="instrument:bbb",
            name="BBB Corporation",
            asset_class=AssetClass.EQUITY,
            instrument_type=InstrumentType.COMMON_STOCK,
        ),
        Instrument(
            instrument_id="instrument:crypto",
            name="Bitcoin spot",
            asset_class=AssetClass.CRYPTO,
            instrument_type=InstrumentType.SPOT,
            base_asset="BTC",
            quote_currency="USD",
        ),
    )
    records = tuple(
        InstrumentRecord(
            record_identifier=f"record:{item.instrument_id}",
            instrument=item,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier=f"source:{item.instrument_id}",
        )
        for item in instruments
    )
    listings = tuple(
        ListingRecord(
            record_identifier=f"record:listing:{item.instrument_id}",
            listing_identifier=f"listing:{item.instrument_id}",
            instrument_identifier=item.instrument_id,
            venue="NASDAQ" if item.asset_class is AssetClass.EQUITY else "CRYPTO",
            symbol={
                "instrument:aaa": "AAA",
                "instrument:bbb": "BBB",
                "instrument:crypto": "BTCUSD",
            }[item.instrument_id],
            country_code="US",
            trading_calendar=(
                TradingCalendar.EXCHANGE
                if item.asset_class is AssetClass.EQUITY
                else TradingCalendar.CONTINUOUS
            ),
            status=ListingStatus.ACTIVE,
            primary=True,
            effective_from=LISTED,
            effective_until=None,
            available_at=LISTED,
            source_identifier=f"source:listing:{item.instrument_id}",
        )
        for item in instruments
    )
    return SecurityMasterCatalog(
        identifier="catalog:licensed:2026-07-27",
        version="reference.v1",
        issuers=(),
        instruments=records,
        identifiers=(),
        listings=listings,
        actions=(),
        coverage=_coverage(),
    )


def _metrics(*, omit: str | None = None):
    return tuple(
        SecurityMasterMarketMetrics(
            identifier=f"metrics:{instrument_id}",
            instrument_identifier=instrument_id,
            observed_at=AS_OF,
            available_at=AS_OF,
            average_daily_dollar_volume=100_000_000.0,
            analytical_coverage=0.95,
        )
        for instrument_id in (
            "instrument:aaa",
            "instrument:bbb",
            "instrument:crypto",
        )
        if instrument_id != omit
    )


def _context() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity-context:2026-07-27",
        as_of=AS_OF,
        alternatives=(
            AlternativeUse(
                identifier="cash",
                kind=AlternativeKind.CASH,
                expected_return=0.04,
                implementation_cost_return=0.0,
                evidence_quality=1.0,
                liquidity_score=1.0,
                current_weight=1.0,
            ),
        ),
    )


def _request(**overrides) -> FullUniverseScreeningRequest:
    values = {
        "identifier": "full-universe:2026-07-27",
        "scheduled_for": AS_OF,
        "as_of": AS_OF,
        "knowledge_cutoff": AS_OF,
        "started_at": AS_OF,
        "partition_size": 1,
        "maximum_partition_attempts": 2,
    }
    values.update(overrides)
    return FullUniverseScreeningRequest(**values)


def _candidate(instrument, *, as_of, opportunity_cost_return):
    return CandidateDecisionRecord(
        identifier=f"candidate:{instrument.symbol.lower()}:{as_of.isoformat()}",
        as_of=as_of,
        schema_version="candidate-decision.v1",
        instrument=instrument,
        current_price=100.0,
        decision_horizon_days=365,
        base_case_return=0.15,
        bull_case_return=0.30,
        bear_case_return=-0.10,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=115.0,
        expected_upside=0.30,
        expected_downside=-0.10,
        probability_of_success=0.70,
        primary_catalysts=("earnings and cash flow improve",),
        key_risks=("earnings may weaken",),
        critical_assumptions=("reported evidence remains representative",),
        invalidation_conditions=("expected return falls below cash",),
        supporting_evidence=("point-in-time filing and market evidence",),
        contradictory_evidence=(),
        evidence_quality=EvidenceQuality(
            reliability=0.95,
            freshness=0.95,
            relevance=0.95,
            independence=0.90,
            completeness=0.95,
            point_in_time_integrity=1.0,
        ),
        liquidity_score=1.0,
        transaction_cost_bps=5.0,
        slippage_bps=5.0,
        opportunity_cost_return=opportunity_cost_return,
        expected_portfolio_contribution=0.015,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("earnings", "cash flow"),
        review_at=as_of + timedelta(days=30),
        evidence_identifiers=("evidence:filing", "evidence:market"),
        model_versions=("candidate-model.v1",),
    )


def _orchestrator(tmp_path, *, metrics=None, provider=None, service=None, clock=None):
    screening_store = SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")
    slo_store = SQLiteOperationalSLOStore(tmp_path / "slo.db")
    journal = SQLiteCIOJournal(tmp_path / "journal.db", clock=clock or Clock())
    orchestrator = FullUniverseScreeningOrchestrator(
        security_master_service=service or ActiveCatalogService(_catalog()),
        metrics_provider=MetricsProvider(metrics or _metrics()),
        candidate_provider=provider or CandidateProvider(),
        screening_store=screening_store,
        slo_store=slo_store,
        journal=journal,
        clock=clock or Clock(),
    )
    return orchestrator, screening_store, slo_store, journal


def test_complete_cycle_publishes_only_after_every_constituent(tmp_path) -> None:
    orchestrator, store, slo_store, journal = _orchestrator(tmp_path)

    result = orchestrator.run(_request(), _context())

    assert result.publication.eligible_instrument_count == 2
    assert result.publication.screened_instrument_count == 2
    assert result.publication.candidate_count == 1
    assert result.publication.excluded_count == 1
    assert tuple(item.instrument.symbol for item in result.candidates) == ("AAA",)
    assert tuple(item.candidate.instrument.symbol for item in result.opportunity_queue.ranked) == (
        "AAA",
    )
    assert store.publication(_request().identifier) == result.publication
    cycle = slo_store.cycles(limit=1)[0]
    assert cycle.status is FullUniverseCycleStatus.COMPLETED
    assert cycle.eligible_instrument_count == cycle.screened_instrument_count == 2
    assert journal.events(event_type=CIOJournalEventType.CANDIDATE_DECISION)
    assert journal.events(event_type=CIOJournalEventType.OPPORTUNITY_QUEUE)
    assert store.verify_integrity() is True


def test_partition_retry_is_recorded_and_succeeds(tmp_path) -> None:
    provider = CandidateProvider(failures={"instrument:bbb": 1})
    orchestrator, store, _, _ = _orchestrator(tmp_path, provider=provider)

    result = orchestrator.run(_request(), _context())

    attempts = store.events(
        _request().identifier,
        event_type=ScreeningEventType.PARTITION_ATTEMPT,
    )
    bbb_attempts = [
        item for item in attempts if int(item.payload["partition_index"]) == 1
    ]
    assert [item.payload["status"] for item in bbb_attempts] == ["failed", "completed"]
    assert result.publication.screened_instrument_count == 2


def test_failed_cycle_never_publishes_or_reaches_cio_journal(tmp_path) -> None:
    provider = CandidateProvider(failures={"instrument:bbb": 5})
    orchestrator, store, slo_store, journal = _orchestrator(tmp_path, provider=provider)

    with pytest.raises(FullUniverseScreeningError, match="partition 1 failed"):
        orchestrator.run(_request(), _context())

    assert store.publication(_request().identifier) is None
    assert journal.count() == 0
    cycle = slo_store.cycles(limit=1)[0]
    assert cycle.status is FullUniverseCycleStatus.FAILED


def test_rerun_resumes_prior_results_without_rescreening_them(tmp_path) -> None:
    failing = CandidateProvider(failures={"instrument:bbb": 5})
    orchestrator, store, slo_store, journal = _orchestrator(tmp_path, provider=failing)
    with pytest.raises(FullUniverseScreeningError):
        orchestrator.run(_request(), _context())
    assert failing.calls.count("instrument:aaa") == 1

    healthy = CandidateProvider()
    resumed = FullUniverseScreeningOrchestrator(
        security_master_service=ActiveCatalogService(_catalog()),
        metrics_provider=MetricsProvider(_metrics()),
        candidate_provider=healthy,
        screening_store=store,
        slo_store=slo_store,
        journal=journal,
        clock=Clock(AS_OF + timedelta(minutes=1)),
    )
    result = resumed.run(_request(), _context())

    assert "instrument:aaa" not in healthy.calls
    assert healthy.calls == ["instrument:bbb"]
    assert result.publication.screened_instrument_count == 2


def test_persisted_publication_replays_without_active_provider_and_repairs_journal(
    tmp_path,
) -> None:
    store = SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")
    slo_store = SQLiteOperationalSLOStore(tmp_path / "slo.db")
    first_metrics = MetricsProvider(_metrics())
    first_candidates = CandidateProvider()
    first = FullUniverseScreeningOrchestrator(
        security_master_service=ActiveCatalogService(_catalog()),
        metrics_provider=first_metrics,
        candidate_provider=first_candidates,
        screening_store=store,
        slo_store=slo_store,
        journal=None,
        clock=Clock(),
    )
    original = first.run(_request(), _context())

    replay_metrics = MetricsProvider(())
    replay_candidates = CandidateProvider(exclude=())
    repaired_journal = SQLiteCIOJournal(
        tmp_path / "repaired-journal.db",
        clock=Clock(AS_OF + timedelta(minutes=2)),
    )
    replay = FullUniverseScreeningOrchestrator(
        security_master_service=ActiveCatalogService(
            LookupError("provider is no longer active")
        ),
        metrics_provider=replay_metrics,
        candidate_provider=replay_candidates,
        screening_store=store,
        slo_store=slo_store,
        journal=repaired_journal,
        clock=Clock(AS_OF + timedelta(minutes=2)),
    )

    restored = replay.run(_request(), _context())

    assert restored.publication == original.publication
    assert restored.universe is None
    assert replay_metrics.calls == 0
    assert replay_candidates.calls == []
    assert repaired_journal.events(
        event_type=CIOJournalEventType.CANDIDATE_DECISION
    )
    assert repaired_journal.events(
        event_type=CIOJournalEventType.OPPORTUNITY_QUEUE
    )
    assert slo_store.cycles(limit=1)[0].status is FullUniverseCycleStatus.COMPLETED


def test_missing_metrics_fail_closed_before_publication(tmp_path) -> None:
    orchestrator, store, slo_store, journal = _orchestrator(
        tmp_path,
        metrics=_metrics(omit="instrument:bbb"),
    )

    with pytest.raises(FullUniverseScreeningError, match="missing metrics"):
        orchestrator.run(_request(), _context())

    assert store.publication(_request().identifier) is None
    assert journal.count() == 0
    assert slo_store.cycles(limit=1)[0].status is FullUniverseCycleStatus.FAILED


def test_missing_certified_active_catalog_fails_closed(tmp_path) -> None:
    orchestrator, store, _, journal = _orchestrator(
        tmp_path,
        service=ActiveCatalogService(LookupError("no certified catalog")),
    )

    with pytest.raises(FullUniverseScreeningError, match="no certified catalog"):
        orchestrator.run(_request(), _context())

    assert store.publication(_request().identifier) is None
    assert journal.count() == 0


def test_screening_history_is_append_only_and_tamper_evident(tmp_path) -> None:
    orchestrator, store, _, _ = _orchestrator(tmp_path)
    orchestrator.run(_request(), _context())
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE full_universe_screening_events SET payload_json = '{}' WHERE sequence = 1"
            )
        connection.execute("DROP TRIGGER full_universe_screening_events_no_update")
        connection.execute(
            "UPDATE full_universe_screening_events SET payload_json = '{}' WHERE sequence = 1"
        )
    with pytest.raises(FullUniverseScreeningError, match="content hash"):
        store.verify_integrity()
