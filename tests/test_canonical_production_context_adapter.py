"""Production-style persisted-authority integration for the canonical CIO."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from application import (
    CanonicalProductionContextAdapter,
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    EvidenceCertificationState,
    GovernedEvidenceLineage,
    ProductionCandidateEvidence,
    ProductionCanonicalCIOExecutor,
    ProductionContextError,
    ProductionContextEvidenceSnapshot,
    SQLiteCertifiedEligibleUniverseStore,
    SQLiteProductionContextStore,
)
from application.cio_cycle import CandidateExposureProfile, CanonicalCIOCycle
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
from opportunity import OpportunityEngine
from opportunity.snapshot import (
    PUBLICATION_SNAPSHOT_KIND,
    build_opportunity_snapshot,
)
from operations.free_paper_pilot import (
    FreePaperPilotInstrument,
    load_free_paper_pilot_universe,
    write_active_paper_universe,
)
from portfolio.state import SQLiteCanonicalPortfolioStore
from screening import (
    FullUniverseScreeningPublication,
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
)
from tests.test_production_context_assembly import (
    AS_OF,
    _candidate,
    _persist_portfolio,
    _screening_context,
)

CUTOFF = AS_OF
PROCESS_VERSION = "capital-intelligence-investment-process.v1"


def _lineage(
    identifier: str,
    *evidence_identifiers: str,
) -> GovernedEvidenceLineage:
    return GovernedEvidenceLineage(
        certification_identifier=identifier,
        certification_state=EvidenceCertificationState.APPROVED,
        certification_expires_at=AS_OF + timedelta(days=30),
        fresh_until=AS_OF + timedelta(hours=1),
        evidence_identifiers=tuple(evidence_identifiers),
        source_versions=((f"source:{identifier}", "2026.07"),),
        model_versions=((f"model:{identifier}", "v1"),),
    )


def _candidate_evidence(candidate) -> ProductionCandidateEvidence:
    return ProductionCandidateEvidence(
        identifier="candidate-context:spy:canonical-adapter",
        candidate_identifier=candidate.identifier,
        symbol=candidate.instrument.symbol,
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        analysis_completed_at=AS_OF,
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
        lineage=_lineage(
            "certification:spy-context",
            "evidence:macro:growth",
            "evidence:market:spy",
            "evidence:fundamental:spy",
        ),
    )


def _context_snapshot(
    candidate,
    *,
    include_candidate_evidence: bool = True,
) -> ProductionContextEvidenceSnapshot:
    return ProductionContextEvidenceSnapshot(
        identifier="production-context:canonical-adapter",
        screening_cycle_identifier="screening:canonical-adapter",
        portfolio_code="COMPOUNDING",
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        cash_expected_return=0.04,
        cash_evidence_quality=1.0,
        cash_liquidity_score=1.0,
        cash_lineage=_lineage(
            "certification:cash",
            "evidence:cash:treasury-rate",
        ),
        candidate_evidence=(
            (_candidate_evidence(candidate),)
            if include_candidate_evidence
            else ()
        ),
        holding_evidence=(),
    )


def _persist_universe(
    store: SQLiteCertifiedEligibleUniverseStore,
) -> CertifiedEligibleUniversePublication:
    publication = CertifiedEligibleUniversePublication(
        identifier="universe:canonical-adapter",
        published_at=AS_OF - timedelta(minutes=20),
        as_of=AS_OF,
        knowledge_cutoff=CUTOFF,
        security_master_catalog_identifier="catalog:canonical-adapter",
        security_master_snapshot_identifier="security-master:snapshot",
        policy_version="recommendation-universe.v1",
        certification_identifier="certification:eligible-universe",
        certification_state=EligibleUniverseCertificationState.APPROVED,
        certification_expires_at=AS_OF + timedelta(days=30),
        eligible_instrument_identifiers=("instrument:spy",),
        source_versions=(("security_master", "2026.07"),),
        model_versions=(("eligible_universe_builder", "v1"),),
    )
    store.append(publication)
    return publication


def _persist_screening(
    store: SQLiteFullUniverseScreeningStore,
    candidate,
    *,
    force_rejected: bool = False,
    published_at=None,
) -> FullUniverseScreeningPublication:
    engine = OpportunityEngine()
    context = _screening_context()
    queue = engine.build_queue(
        (candidate,),
        context,
    )
    publication_identifier = "publication:screening:canonical-adapter"
    snapshot_payload = build_opportunity_snapshot(
        snapshot_kind=PUBLICATION_SNAPSHOT_KIND,
        context=context,
        queue=queue,
        engine=engine,
        created_at=AS_OF,
        code_version="commit:canonical-adapter",
        screening_publication_identifier=publication_identifier,
    )
    queue_payload = {
        **serialize_opportunity_queue(
            queue,
            occurred_at=AS_OF,
        ),
        "opportunity_context_snapshot": snapshot_payload,
    }
    if force_rejected:
        queue_payload = {
            "code_version": "test",
            "context_identifier": "opportunity:production",
            "policy_version": queue.policy_version,
            "occurred_at": AS_OF.isoformat(),
            "has_qualified_opportunity": False,
            "ranked": [],
            "rejected": [
                {
                    "candidate_identifier": candidate.identifier,
                    "outcome": "rejected",
                    "universe_disposition": "direct_recommendation",
                    "universe_policy_version": "recommendation-universe.v1",
                    "effective_opportunity_cost": 0.04,
                    "opportunity_edge": candidate.opportunity_edge,
                    "reasons": ["forced persisted rejection for drift test"],
                }
            ],
            "opportunity_context_snapshot": snapshot_payload,
        }
    publication = FullUniverseScreeningPublication(
        identifier=publication_identifier,
        cycle_identifier="screening:canonical-adapter",
        published_at=published_at or AS_OF - timedelta(minutes=5),
        security_master_catalog_identifier="catalog:canonical-adapter",
        security_master_snapshot_identifier="security-master:snapshot",
        universe_snapshot_identifier="universe:canonical-adapter",
        opportunity_context_identifier="opportunity:production",
        eligible_instrument_count=1,
        screened_instrument_count=1,
        candidate_count=1,
        excluded_count=0,
        candidate_payloads=(serialize_candidate_decision(candidate),),
        exclusions=(),
        opportunity_queue_payload=queue_payload,
    )
    store.append(
        event_identifier="screening:canonical-adapter:start",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.CYCLE_STARTED,
        occurred_at=AS_OF - timedelta(minutes=15),
        payload={
            "cycle_identifier": publication.cycle_identifier,
            "scheduled_for": AS_OF.isoformat(),
            "started_at": (AS_OF - timedelta(minutes=15)).isoformat(),
            "as_of": AS_OF.isoformat(),
            "knowledge_cutoff": CUTOFF.isoformat(),
            "metrics_provider": "CERTIFIED_METRICS",
            "candidate_provider": "CERTIFIED_CANDIDATES",
            "catalog_identifier": "catalog:canonical-adapter",
            "security_master_snapshot_identifier": (
                "security-master:snapshot"
            ),
            "universe_snapshot_identifier": "universe:canonical-adapter",
            "policy_version": "recommendation-universe.v1",
            "opportunity_context_identifier": "opportunity:production",
            "eligible_instrument_count": 1,
            "structural_exclusion_count": 0,
            "partition_size": 250,
            "maximum_partition_attempts": 3,
        },
    )
    store.append(
        event_identifier="screening:canonical-adapter:publication",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.PUBLICATION,
        occurred_at=publication.published_at,
        payload=publication.to_dict(),
    )
    return publication


def _adapter(
    tmp_path: Path,
    *,
    force_rejected: bool = False,
    published_at=None,
):
    candidate = _candidate()
    universe_store = SQLiteCertifiedEligibleUniverseStore(
        tmp_path / "eligible_universe.db"
    )
    _persist_universe(universe_store)
    screening_store = SQLiteFullUniverseScreeningStore(
        tmp_path / "screening.db"
    )
    _persist_screening(
        screening_store,
        candidate,
        force_rejected=force_rejected,
        published_at=published_at,
    )
    portfolio_store = SQLiteCanonicalPortfolioStore(
        tmp_path / "portfolio.db"
    )
    _persist_portfolio(portfolio_store)
    base_universe = load_free_paper_pilot_universe()
    spy = FreePaperPilotInstrument(
        symbol=candidate.instrument.symbol,
        instrument_identifier=candidate.instrument.instrument_id,
        name=candidate.instrument.name,
        execution_asset_class=candidate.instrument.asset_class,
        economic_exposure="us_equity",
        venue=candidate.instrument.venue,
        country_code=candidate.instrument.country_code,
        currency="USD",
        instrument_type="fund",
        maximum_weight=candidate.maximum_position_weight,
    )
    write_active_paper_universe(
        replace(
            base_universe,
            identifier="active:canonical-adapter",
            instruments=(*base_universe.instruments, spy),
        ),
        eligible_universe_publication_identifier="universe:canonical-adapter",
        destination=tmp_path / "active-paper-universe.json",
    )
    context_store = SQLiteProductionContextStore(tmp_path / "context.db")
    context_store.append(
        _context_snapshot(
            candidate,
            include_candidate_evidence=not force_rejected,
        )
    )
    adapter = CanonicalProductionContextAdapter(
        universe_store=universe_store,
        screening_store=screening_store,
        portfolio_store=portfolio_store,
        context_store=context_store,
        portfolio_code="COMPOUNDING",
        process_version=PROCESS_VERSION,
        code_version="commit:canonical-adapter",
    )
    return candidate, screening_store, adapter


def test_persisted_certified_authorities_complete_the_full_cio_path(
    tmp_path: Path,
) -> None:
    candidate, screening_store, adapter = _adapter(tmp_path)
    journal = SQLiteCIOJournal(tmp_path / "journal.db")
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(journal=journal),
        screening_store=screening_store,
        context_provider=adapter,
    )

    result = executor.run(as_of=AS_OF)

    context = adapter.load_context(as_of=AS_OF)
    assert context.decision_timestamp == AS_OF
    assert context.knowledge_cutoff == CUTOFF
    assert context.process_version == PROCESS_VERSION
    assert (
        context.eligible_universe_publication_identifier
        == "universe:canonical-adapter"
    )
    assert context.manifest is not None
    assert ("investment_process", PROCESS_VERSION) in (
        context.manifest.model_versions
    )
    assert result.decisions
    assert result.construction is not None
    assert result.theses
    assert result.briefing.as_of == AS_OF
    assert journal.verify_integrity()
    event_types = {item.event_type for item in journal.events(limit=100)}
    assert {
        CIOJournalEventType.CANDIDATE_DECISION,
        CIOJournalEventType.OPPORTUNITY_QUEUE,
        CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT,
        CIOJournalEventType.SPECIALIST_PACKET,
        CIOJournalEventType.CIO_DECISION,
        CIOJournalEventType.PORTFOLIO_CONSTRUCTION,
        CIOJournalEventType.THESIS_SNAPSHOT,
        CIOJournalEventType.DECISION_EVIDENCE_SNAPSHOT,
        CIOJournalEventType.DAILY_CIO_BRIEFING,
    }.issubset(event_types)
    assert tuple(
        item.candidate.identifier for item in result.opportunity_queue.ranked
    ) == (candidate.identifier,)


def test_screening_publication_after_decision_blocks_execution(
    tmp_path: Path,
) -> None:
    _, _, adapter = _adapter(
        tmp_path,
        published_at=AS_OF + timedelta(seconds=1),
    )

    with pytest.raises(
        ProductionContextError,
        match="unavailable at the decision timestamp",
    ):
        adapter.load_context(as_of=AS_OF)


def test_runtime_ranking_drift_blocks_the_cio_cycle(
    tmp_path: Path,
) -> None:
    _, screening_store, adapter = _adapter(
        tmp_path,
        force_rejected=True,
    )
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(),
        screening_store=screening_store,
        context_provider=adapter,
    )

    with pytest.raises(
        ProductionContextError,
        match="opportunity snapshot queue differs",
    ):
        executor.run(as_of=AS_OF)
