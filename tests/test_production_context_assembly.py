"""Persisted production-context assembly and canonical-cycle integration tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from application import (
    EvidenceCertificationState,
    GovernedEvidenceLineage,
    ProductionCandidateEvidence,
    ProductionCanonicalCIOExecutor,
    ProductionContextError,
    ProductionContextEvidenceSnapshot,
    RepositoryProductionCanonicalCIOContextProvider,
    SQLiteProductionContextStore,
)
from application.cio_cycle import (
    CandidateExposureProfile,
    CanonicalCIOCycle,
)
from cio import (
    CandidateAssetClass,
    CandidateDecisionRecord,
    CandidateInstrument,
    EvidenceQuality,
)
from cio.persistence import (
    CIOJournalEventType,
    SQLiteCIOJournal,
    serialize_candidate_decision,
    serialize_opportunity_queue,
)
from committee.specialists import (
    MacroSpecialistContext,
    MarketSpecialistContext,
)
from opportunity import (
    AlternativeKind,
    AlternativeUse,
    OpportunityEngine,
    OpportunitySetContext,
)
from portfolio.state import (
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)
from screening import (
    FullUniverseScreeningPublication,
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
)

UTC = timezone.utc
AS_OF = datetime(2026, 7, 27, 11, tzinfo=UTC)
KNOWLEDGE_CUTOFF = datetime(2026, 7, 27, 12, tzinfo=UTC)
ANALYSIS_COMPLETED_AT = datetime(2026, 7, 27, 11, 45, tzinfo=UTC)


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
            security_master_record_identifiers=(
                "security-master:record:spy",
            ),
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
        supporting_evidence=(
            "Point-in-time market and fundamental evidence",
        ),
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
        evidence_identifiers=(
            "evidence:spy:market",
            "evidence:spy:fundamental",
        ),
        model_versions=("candidate.v1",),
    )


def _screening_context() -> OpportunitySetContext:
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


def _approved_lineage(
    identifier: str,
    *evidence_identifiers: str,
) -> GovernedEvidenceLineage:
    return GovernedEvidenceLineage(
        certification_identifier=identifier,
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=KNOWLEDGE_CUTOFF + timedelta(days=30),
        fresh_until=KNOWLEDGE_CUTOFF + timedelta(hours=1),
        evidence_identifiers=tuple(evidence_identifiers),
        source_versions=((f"source:{identifier}", "2026.07"),),
        model_versions=((f"model:{identifier}", "v1"),),
    )


def _candidate_evidence(
    candidate: CandidateDecisionRecord,
) -> ProductionCandidateEvidence:
    return ProductionCandidateEvidence(
        identifier="candidate-context:spy:production",
        candidate_identifier=candidate.identifier,
        symbol=candidate.instrument.symbol,
        as_of=AS_OF,
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        analysis_completed_at=ANALYSIS_COMPLETED_AT,
        macro=MacroSpecialistContext(
            as_of=AS_OF,
            regime="moderate growth",
            expected_return_impact=0.02,
            confidence=0.90,
            tailwinds=("Growth remains positive",),
            headwinds=("Policy remains restrictive",),
            systemic_risks=("Inflation reacceleration",),
            scenarios=("Reassess if growth contracts",),
            evidence_identifiers=("evidence:macro:growth",),
        ),
        market=MarketSpecialistContext(
            as_of=AS_OF,
            market_regime="constructive",
            expected_return_impact=0.02,
            confidence=0.90,
            trend=0.80,
            momentum=0.70,
            breadth=0.65,
            liquidity=0.90,
            positioning=0.20,
            evidence=("evidence:market:spy",),
            risks=("Crowded positioning can reverse",),
            entry_conditions=("Broad participation remains intact",),
        ),
        company=None,
        exposure_profile=CandidateExposureProfile(
            candidate_identifier=candidate.identifier,
            sector="Broad Market",
            factor_loadings=(("equity_beta", 1.0),),
            correlation_bucket="US_LARGE_CAP",
        ),
        fundamental_evidence_identifiers=(
            "evidence:fundamental:spy",
        ),
        fundamental_model_version="etf-fundamental.v1",
        lineage=_approved_lineage(
            "certification:spy-context",
            "evidence:macro:growth",
            "evidence:market:spy",
            "evidence:fundamental:spy",
        ),
    )


def _persist_screening(
    store: SQLiteFullUniverseScreeningStore,
    candidate: CandidateDecisionRecord,
) -> FullUniverseScreeningPublication:
    queue = OpportunityEngine().build_queue(
        (candidate,),
        _screening_context(),
    )
    publication = FullUniverseScreeningPublication(
        identifier="publication:screening:production",
        cycle_identifier="screening:production",
        published_at=datetime(2026, 7, 27, 11, 30, tzinfo=UTC),
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
        opportunity_queue_payload=serialize_opportunity_queue(
            queue,
            occurred_at=AS_OF,
        ),
    )
    store.append(
        event_identifier="screening:production:start",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.CYCLE_STARTED,
        occurred_at=AS_OF,
        payload={
            "cycle_identifier": publication.cycle_identifier,
            "scheduled_for": AS_OF.isoformat(),
            "started_at": AS_OF.isoformat(),
            "as_of": AS_OF.isoformat(),
            "knowledge_cutoff": KNOWLEDGE_CUTOFF.isoformat(),
            "metrics_provider": "CERTIFIED_METRICS",
            "candidate_provider": "CERTIFIED_CANDIDATES",
            "catalog_identifier": "catalog:production",
            "security_master_snapshot_identifier": (
                "security-master:snapshot"
            ),
            "universe_snapshot_identifier": "universe:production",
            "policy_version": "recommendation-universe.v1",
            "opportunity_context_identifier": "opportunity:production",
            "eligible_instrument_count": 1,
            "structural_exclusion_count": 0,
            "partition_size": 250,
            "maximum_partition_attempts": 3,
        },
    )
    store.append(
        event_identifier="screening:production:publication",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.PUBLICATION,
        occurred_at=publication.published_at,
        payload=publication.to_dict(),
    )
    return publication


def _persist_portfolio(store: SQLiteCanonicalPortfolioStore) -> None:
    store.append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:compounding:2026-07-27T11:00:00Z",
            portfolio_code="COMPOUNDING",
            display_name="Long-Term Compounding",
            constraint_profile="standard",
            as_of=AS_OF,
            starting_capital=250_000.0,
            cash_amount=1_000_000.0,
            positions=(),
            source_identifiers=("portfolio:opening-state",),
        )
    )


def _context_snapshot(
    candidate: CandidateDecisionRecord,
    *,
    candidate_evidence: tuple[ProductionCandidateEvidence, ...] | None = None,
) -> ProductionContextEvidenceSnapshot:
    return ProductionContextEvidenceSnapshot(
        identifier="production-context:2026-07-27T11:00:00Z",
        screening_cycle_identifier="screening:production",
        portfolio_code="COMPOUNDING",
        as_of=AS_OF,
        knowledge_cutoff=KNOWLEDGE_CUTOFF,
        cash_expected_return=0.04,
        cash_evidence_quality=1.0,
        cash_liquidity_score=1.0,
        cash_lineage=_approved_lineage(
            "certification:cash",
            "evidence:cash:treasury-rate",
        ),
        candidate_evidence=(
            (_candidate_evidence(candidate),)
            if candidate_evidence is None
            else candidate_evidence
        ),
        holding_evidence=(),
    )


def _provider(
    tmp_path: Path,
    *,
    context_snapshot: ProductionContextEvidenceSnapshot | None = None,
):
    candidate = _candidate()
    screening_store = SQLiteFullUniverseScreeningStore(
        tmp_path / "screening.db"
    )
    _persist_screening(screening_store, candidate)
    portfolio_store = SQLiteCanonicalPortfolioStore(
        tmp_path / "portfolio.db"
    )
    _persist_portfolio(portfolio_store)
    context_store = SQLiteProductionContextStore(tmp_path / "context.db")
    context_store.append(context_snapshot or _context_snapshot(candidate))
    provider = RepositoryProductionCanonicalCIOContextProvider(
        screening_store=screening_store,
        portfolio_store=portfolio_store,
        context_store=context_store,
        portfolio_code="COMPOUNDING",
        code_version="commit:integration",
    )
    return candidate, screening_store, context_store, provider


def test_persisted_authorities_complete_a_journaled_cio_cycle(
    tmp_path: Path,
) -> None:
    candidate, screening_store, context_store, provider = _provider(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=provider,
    )

    result = executor.run(as_of=AS_OF)

    assert result.identifier == "canonical-cycle:screening:production"
    assert tuple(
        item.candidate.identifier for item in result.opportunity_queue.ranked
    ) == (candidate.identifier,)
    assert result.decisions
    assert result.briefing.as_of == AS_OF
    assert journal.verify_integrity()
    event_types = {item.event_type for item in journal.events(limit=100)}
    assert {
        CIOJournalEventType.CANDIDATE_DECISION,
        CIOJournalEventType.OPPORTUNITY_QUEUE,
        CIOJournalEventType.SPECIALIST_PACKET,
        CIOJournalEventType.CIO_DECISION,
        CIOJournalEventType.DECISION_EVIDENCE_SNAPSHOT,
        CIOJournalEventType.DAILY_CIO_BRIEFING,
    }.issubset(event_types)

    assembled = provider.load_context(as_of=AS_OF)
    assert assembled.manifest is not None
    assert assembled.manifest.candidate_identifiers == (candidate.identifier,)
    assert assembled.manifest.evidence_identifiers == (
        "evidence:cash:treasury-rate",
        "evidence:macro:growth",
        "evidence:market:spy",
        "evidence:fundamental:spy",
    )
    assert ("fundamental", "etf-fundamental.v1") in (
        assembled.manifest.model_versions
    )
    assert context_store.verify_integrity()


def test_provider_rejects_missing_qualified_candidate_coverage(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    snapshot = _context_snapshot(candidate, candidate_evidence=())
    _, _, _, provider = _provider(
        tmp_path,
        context_snapshot=snapshot,
    )

    with pytest.raises(
        ProductionContextError,
        match="candidate context coverage must exactly match",
    ):
        provider.load_context(as_of=AS_OF)


def test_stale_evidence_is_rejected_before_context_persistence() -> None:
    with pytest.raises(ProductionContextError, match="is stale"):
        ProductionContextEvidenceSnapshot(
            identifier="production-context:stale",
            screening_cycle_identifier="screening:production",
            portfolio_code="COMPOUNDING",
            as_of=AS_OF,
            knowledge_cutoff=KNOWLEDGE_CUTOFF,
            cash_expected_return=0.04,
            cash_evidence_quality=1.0,
            cash_liquidity_score=1.0,
            cash_lineage=GovernedEvidenceLineage(
                certification_identifier="certification:stale-cash",
                certification_state=EvidenceCertificationState.APPROVED,
                certification_expires_at=KNOWLEDGE_CUTOFF + timedelta(days=1),
                fresh_until=KNOWLEDGE_CUTOFF - timedelta(seconds=1),
                evidence_identifiers=("evidence:cash:stale",),
                source_versions=(("source:cash", "v1"),),
                model_versions=(("model:cash", "v1"),),
            ),
            candidate_evidence=(),
            holding_evidence=(),
        )


def test_candidate_is_compared_with_other_alternatives_not_itself() -> None:
    candidate = _candidate()
    context = OpportunitySetContext(
        identifier="opportunity:with-qualified-candidate",
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
            AlternativeUse(
                identifier=candidate.identifier,
                kind=AlternativeKind.QUALIFIED_CANDIDATE,
                expected_return=candidate.probability_weighted_expected_return,
                implementation_cost_return=candidate.implementation_cost_return,
                evidence_quality=candidate.evidence_quality.score,
                liquidity_score=candidate.liquidity_score,
            ),
        ),
    )

    qualification = OpportunityEngine().qualify(candidate, context)

    assert qualification.qualified
    assert qualification.effective_opportunity_cost == 0.04
    assert qualification.opportunity_edge == round(
        candidate.net_expected_return - 0.04,
        8,
    )
