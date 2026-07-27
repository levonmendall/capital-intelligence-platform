"""Production canonical scheduler and complete-publication boundary tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from application import (
    ProductionCanonicalCIOContext,
    ProductionCanonicalCIOExecutor,
)
from application.cio_cycle import CanonicalCIOCycle, CyclePortfolioState
from cio import CandidateAssetClass, CandidateDecisionRecord, CandidateInstrument, EvidenceQuality
from cio.persistence import serialize_candidate_decision
from delivery import ScheduledCanonicalCIOWorker, SQLiteAlertStore
from opportunity import AlternativeKind, AlternativeUse, OpportunitySetContext
from screening import (
    FullUniverseScreeningPublication,
    SQLiteFullUniverseScreeningStore,
    ScreeningEventType,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 11, tzinfo=UTC)


def _candidate() -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        identifier="candidate:spy:production",
        as_of=AS_OF,
        schema_version="candidate-decision.v1",
        instrument=CandidateInstrument(
            instrument_id="instrument:spy",
            symbol="SPY",
            name="SPDR S&P 500 ETF",
            asset_class=CandidateAssetClass.US_ETF,
            venue="NYSE",
            country_code="US",
            average_daily_dollar_volume=1_000_000_000.0,
            data_age_hours=1.0,
            analytical_coverage=0.99,
            security_master_snapshot_identifier="security-master:snapshot",
            security_master_record_identifiers=("security-master:record:spy",),
        ),
        current_price=600.0,
        decision_horizon_days=365,
        base_case_return=0.12,
        bull_case_return=0.25,
        bear_case_return=-0.12,
        base_case_probability=0.55,
        bull_case_probability=0.25,
        bear_case_probability=0.20,
        estimated_fair_value=672.0,
        expected_upside=0.25,
        expected_downside=-0.12,
        probability_of_success=0.67,
        primary_catalysts=("Earnings breadth supports returns",),
        key_risks=("Valuation compression",),
        critical_assumptions=("Evidence remains current",),
        invalidation_conditions=("Expected return falls below cash",),
        supporting_evidence=("Point-in-time market and fundamental evidence",),
        contradictory_evidence=("Valuation remains elevated",),
        evidence_quality=EvidenceQuality(
            reliability=0.95,
            freshness=0.95,
            relevance=0.95,
            independence=0.95,
            completeness=0.95,
            point_in_time_integrity=1.0,
        ),
        liquidity_score=1.0,
        transaction_cost_bps=2.0,
        slippage_bps=2.0,
        opportunity_cost_return=0.04,
        expected_portfolio_contribution=0.01,
        current_portfolio_weight=0.0,
        maximum_position_weight=0.10,
        monitoring_indicators=("Expected return",),
        review_at=AS_OF + timedelta(days=30),
        evidence_identifiers=("evidence:spy",),
        model_versions=("candidate.v1",),
    )


def _opportunity() -> OpportunitySetContext:
    return OpportunitySetContext(
        identifier="opportunity:production",
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


def _portfolio() -> CyclePortfolioState:
    return CyclePortfolioState(
        identifier="portfolio:production",
        as_of=AS_OF,
        portfolio_value=1_000_000.0,
        cash_weight=1.0,
        cash_expected_return=0.04,
        positions=(),
        exposure_profiles=(),
    )


def _publication(candidate: CandidateDecisionRecord) -> FullUniverseScreeningPublication:
    return FullUniverseScreeningPublication(
        identifier="publication:production",
        cycle_identifier="screening:production",
        published_at=AS_OF,
        security_master_catalog_identifier="catalog:production",
        security_master_snapshot_identifier="security-master:snapshot",
        universe_snapshot_identifier="universe:production",
        opportunity_context_identifier="opportunity:production",
        eligible_instrument_count=1,
        screened_instrument_count=1,
        candidate_count=1,
        excluded_count=0,
        candidate_payloads=(serialize_candidate_decision(candidate),),
        exclusions=(),
        opportunity_queue_payload={"identifier": "queue:production"},
    )


class CapturingCycle(CanonicalCIOCycle):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            identifier=kwargs["identifier"],
            briefing=SimpleNamespace(identifier=f"daily-cio:{kwargs['identifier']}"),
        )


class ContextProvider:
    name = "TEST_CONTEXT"

    def __init__(self, context: ProductionCanonicalCIOContext) -> None:
        self.context = context
        self.calls = []

    def load_context(self, *, as_of: datetime) -> ProductionCanonicalCIOContext:
        self.calls.append(as_of)
        return self.context


def _context() -> ProductionCanonicalCIOContext:
    return ProductionCanonicalCIOContext(
        identifier="canonical-cycle:production",
        screening_cycle_identifier="screening:production",
        opportunity_context=_opportunity(),
        specialist_contexts=(),
        portfolio=_portfolio(),
        code_version="commit:test",
    )


def _store(tmp_path: Path, candidate: CandidateDecisionRecord) -> SQLiteFullUniverseScreeningStore:
    store = SQLiteFullUniverseScreeningStore(tmp_path / "screening.db")
    publication = _publication(candidate)
    store.append(
        event_identifier="publication-event:production",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.PUBLICATION,
        occurred_at=AS_OF,
        payload=publication.to_dict(),
    )
    return store


def test_executor_uses_only_candidates_from_complete_publication(tmp_path: Path) -> None:
    candidate = _candidate()
    cycle = CapturingCycle()
    provider = ContextProvider(_context())
    executor = ProductionCanonicalCIOExecutor(
        cycle=cycle,
        screening_store=_store(tmp_path, candidate),
        context_provider=provider,
    )

    result = executor.run(as_of=AS_OF)

    assert result.briefing.identifier == "daily-cio:canonical-cycle:production"
    assert provider.calls == [AS_OF]
    assert cycle.calls[0]["candidates"] == (candidate,)
    assert cycle.calls[0]["opportunity_context"].identifier == "opportunity:production"


def test_executor_fails_closed_without_persisted_publication(tmp_path: Path) -> None:
    executor = ProductionCanonicalCIOExecutor(
        cycle=CapturingCycle(),
        screening_store=SQLiteFullUniverseScreeningStore(tmp_path / "screening.db"),
        context_provider=ContextProvider(_context()),
    )

    with pytest.raises(RuntimeError, match="persisted complete-universe publication"):
        executor.run(as_of=AS_OF)


def test_executor_rejects_context_timestamp_mismatch(tmp_path: Path) -> None:
    context = _context()
    shifted = ProductionCanonicalCIOContext(
        identifier=context.identifier,
        screening_cycle_identifier=context.screening_cycle_identifier,
        opportunity_context=OpportunitySetContext(
            identifier=context.opportunity_context.identifier,
            as_of=AS_OF + timedelta(minutes=1),
            alternatives=context.opportunity_context.alternatives,
        ),
        specialist_contexts=(),
        portfolio=CyclePortfolioState(
            identifier=context.portfolio.identifier,
            as_of=AS_OF + timedelta(minutes=1),
            portfolio_value=context.portfolio.portfolio_value,
            cash_weight=context.portfolio.cash_weight,
            cash_expected_return=context.portfolio.cash_expected_return,
            positions=(),
            exposure_profiles=(),
        ),
    )
    executor = ProductionCanonicalCIOExecutor(
        cycle=CapturingCycle(),
        screening_store=_store(tmp_path, _candidate()),
        context_provider=ContextProvider(shifted),
    )

    with pytest.raises(ValueError, match="scheduled decision timestamp"):
        executor.run(as_of=AS_OF)


def test_worker_claims_one_canonical_cycle_and_replays_idempotently(tmp_path: Path) -> None:
    class Executor:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, *, as_of: datetime):
            self.calls += 1
            return SimpleNamespace(briefing=SimpleNamespace(identifier="daily-cio:test"))

    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    executor = Executor()
    store = SQLiteAlertStore(tmp_path / "alerts.db")
    worker = ScheduledCanonicalCIOWorker(
        executor,
        store,
        schedule_timezone="UTC",
        schedule_hour=11,
        clock=lambda: now,
    )

    first = worker.run_due(now=now)
    second = worker.run_due(now=now)

    assert first.status == "completed"
    assert first.snapshot_identifier == "daily-cio:test"
    assert second.status == "completed"
    assert executor.calls == 1


def test_active_scheduler_source_has_no_legacy_decision_pipeline() -> None:
    source = Path("run_scheduler.py").read_text(encoding="utf-8")
    forbidden = (
        "DailyCapitalIntelligenceService",
        "CanonicalDailyCycleExecutor",
        "AnalyticalEngineCycleExecutor",
        "MultiEngineSynthesizer",
        "build_fred_regime_pipeline",
        "build_conviction_trend_from_store",
    )
    assert all(value not in source for value in forbidden)
    assert "ProductionCanonicalCIOExecutor" in source
    assert "CanonicalCIOCycle" in source
