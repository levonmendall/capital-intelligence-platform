"""Production-path certification for immutable opportunity snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from opportunity.snapshot import (
    DECISION_SNAPSHOT_KIND,
    PUBLICATION_SNAPSHOT_KIND,
    load_opportunity_snapshot,
)
from production_context_publication_runtime import prepare_production_context_for_cycle
from screening import SQLiteFullUniverseScreeningStore, candidate_from_payload
from tests.test_production_context_publication_runtime import (
    _bootstrap_cash_portfolio,
    _evidence,
    _equity_discovery_probe,
    _executor,
    _provider,
    _readiness,
    _settings,
)


def test_production_publication_and_cio_consume_hash_guarded_snapshots(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
    )

    result = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),
        evidence_probe=lambda _universe, _as_of: _evidence(decision_time),
        equity_discovery_probe=_equity_discovery_probe,
        clock=lambda: decision_time,
    )
    assert result.ready

    screening = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    publication = screening.publication(result.screening_cycle_identifier)
    assert publication is not None
    candidates = tuple(
        candidate_from_payload(payload) for payload in publication.candidate_payloads
    )
    candidate_map = {item.identifier: item for item in candidates}
    raw_publication_snapshot = publication.opportunity_queue_payload[
        "opportunity_context_snapshot"
    ]
    publication_snapshot = load_opportunity_snapshot(
        raw_publication_snapshot,
        candidates=candidate_map,
    )
    assert publication_snapshot.snapshot_kind == PUBLICATION_SNAPSHOT_KIND
    assert publication_snapshot.context.identifier == publication.opportunity_context_identifier

    context = _provider(settings, tmp_path).load_context(as_of=decision_time)
    assert context.opportunity_snapshot_hash == publication_snapshot.content_hash
    assert context.opportunity_context == publication_snapshot.context

    cycle_result = _executor(settings, tmp_path).run(as_of=decision_time)
    journal = SQLiteCIOJournal(settings.journal_database)
    event = journal.latest(
        aggregate_identifier=result.screening_cycle_identifier,
        event_type=CIOJournalEventType.OPPORTUNITY_DECISION_SNAPSHOT,
    )
    assert event is not None
    decision_snapshot = load_opportunity_snapshot(
        event.payload,
        candidates=candidate_map,
    )
    assert decision_snapshot.snapshot_kind == DECISION_SNAPSHOT_KIND
    assert decision_snapshot.parent_snapshot_hash == publication_snapshot.content_hash
    assert decision_snapshot.screening_publication_identifier == publication.identifier
    assert decision_snapshot.queue == cycle_result.opportunity_queue
    assert decision_snapshot.context.ranking_inputs
    assert journal.verify_integrity()
