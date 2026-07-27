"""Publication completion time must not rewrite the evidence cutoff."""

from datetime import timedelta
from pathlib import Path

from application import (
    RepositoryProductionCanonicalCIOContextProvider,
    SQLiteProductionContextStore,
)
from cio.persistence import serialize_candidate_decision, serialize_opportunity_queue
from opportunity import OpportunityEngine
from portfolio.state import SQLiteCanonicalPortfolioStore
from screening import (
    FullUniverseScreeningPublication,
    ScreeningEventType,
    SQLiteFullUniverseScreeningStore,
)
from tests.test_production_context_assembly import (
    AS_OF,
    KNOWLEDGE_CUTOFF,
    _candidate,
    _context_snapshot,
    _persist_portfolio,
    _screening_context,
)


def test_publication_may_complete_after_point_in_time_cutoff(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    queue = OpportunityEngine().build_queue(
        (candidate,),
        _screening_context(),
    )
    publication = FullUniverseScreeningPublication(
        identifier="publication:after-cutoff",
        cycle_identifier="screening:production",
        published_at=KNOWLEDGE_CUTOFF + timedelta(minutes=5),
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
    screening_store = SQLiteFullUniverseScreeningStore(
        tmp_path / "screening.db"
    )
    screening_store.append(
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
    screening_store.append(
        event_identifier="screening:production:publication",
        cycle_identifier=publication.cycle_identifier,
        event_type=ScreeningEventType.PUBLICATION,
        occurred_at=publication.published_at,
        payload=publication.to_dict(),
    )
    portfolio_store = SQLiteCanonicalPortfolioStore(
        tmp_path / "portfolio.db"
    )
    _persist_portfolio(portfolio_store)
    context_store = SQLiteProductionContextStore(tmp_path / "context.db")
    context_store.append(_context_snapshot(candidate))
    provider = RepositoryProductionCanonicalCIOContextProvider(
        screening_store=screening_store,
        portfolio_store=portfolio_store,
        context_store=context_store,
        portfolio_code="COMPOUNDING",
        code_version="commit:timing",
    )

    context = provider.load_context(as_of=AS_OF)

    assert context.manifest is not None
    assert context.manifest.knowledge_cutoff == KNOWLEDGE_CUTOFF
    assert (
        context.manifest.screening_publication_identifier
        == publication.identifier
    )
