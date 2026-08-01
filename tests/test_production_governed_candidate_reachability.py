from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from production_context_publication_runtime import prepare_production_context_for_cycle
from tests.test_production_context_publication_runtime import (
    _bootstrap_cash_portfolio,
    _equity_discovery_probe,
    _evidence,
    _executor,
    _readiness,
    _series,
    _settings,
)


def test_governed_wrapper_reaches_all_six_specialists_and_cio(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
    )
    payload = _evidence(decision_time)
    for symbol, annual_return in (("VTI", 0.01), ("GOVT", 0.38)):
        rows = _series(decision_time, annual_return=annual_return)
        payload["bars"][symbol] = rows
        price = float(rows[-1]["c"])
        payload["quotes"][symbol] = {
            "t": (decision_time - timedelta(seconds=30)).isoformat(),
            "bp": price * 0.9995,
            "ap": price * 1.0005,
        }

    publication = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),
        evidence_probe=lambda _universe, _as_of: payload,
        equity_discovery_probe=_equity_discovery_probe,
        clock=lambda: decision_time,
    )
    assert publication.ready

    result = _executor(settings, tmp_path).run(as_of=decision_time)
    ranked = {
        item.candidate.instrument.symbol: item.candidate.identifier
        for item in result.opportunity_queue.ranked
    }
    assert "GOVT" in ranked
    assert any(
        item.candidate_identifier == ranked["GOVT"] for item in result.decisions
    )

    journal = SQLiteCIOJournal(settings.journal_database)
    packet = journal.latest(
        aggregate_identifier=ranked["GOVT"],
        event_type=CIOJournalEventType.SPECIALIST_PACKET,
    )
    decision = journal.latest(
        aggregate_identifier=ranked["GOVT"],
        event_type=CIOJournalEventType.CIO_DECISION,
    )
    traces = journal.events(
        event_type=CIOJournalEventType.COMMITTEE_CIO_INFORMATION_TRACE,
        limit=max(1, journal.count()),
    )
    trace = next(
        (
            item
            for item in traces
            if item.payload.get("candidate_identifier") == ranked["GOVT"]
            or item.payload.get("normalized_point_in_time_record", {}).get(
                "candidate_identifier"
            )
            == ranked["GOVT"]
            or item.payload.get("cio_decision", {}).get("candidate_identifier")
            == ranked["GOVT"]
        ),
        None,
    )
    diagnostic = journal.latest(
        aggregate_identifier=result.identifier,
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
    )

    assert packet is not None
    assert len(packet.payload["analyses"]) == 6
    assert decision is not None
    assert trace is not None
    assert trace.payload["committee_synthesis"]["exact_role_count"] == 6
    assert diagnostic is not None
    observation = next(
        item
        for item in diagnostic.payload["observations"]
        if item["candidate_identifier"] == ranked["GOVT"]
    )
    assert "six_specialist_analysis" in observation["reached_stages"]
    assert "cio_consideration" in observation["reached_stages"]
    assert journal.verify_integrity()
