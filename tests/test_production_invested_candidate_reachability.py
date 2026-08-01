"""Production regression for post-investment candidate reachability."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cio.persistence import CIOJournalEventType, SQLiteCIOJournal
from cio.robustness import RobustCandidateAssessor
from portfolio.state import (
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)
from production_context_publication_runtime import prepare_production_context_for_cycle
from tests.test_production_context_publication_runtime import (
    _equity_discovery_probe,
    _evidence,
    _executor,
    _readiness,
    _series,
    _settings,
)


def test_valid_candidate_reaches_six_specialists_after_portfolio_is_invested(
    tmp_path,
) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    payload = _evidence(decision_time)

    # VTI is an attractive existing holding, while GOVT is an even stronger new
    # candidate. The candidate builder still begins with the observable cash hurdle;
    # publication must align it to the stronger point-in-time holding baseline.
    govt_rows = _series(decision_time, annual_return=0.80)
    payload["bars"]["GOVT"] = govt_rows
    govt_price = float(govt_rows[-1]["c"])
    payload["quotes"]["GOVT"] = {
        "t": (decision_time - timedelta(seconds=30)).isoformat(),
        "bp": govt_price * 0.9995,
        "ap": govt_price * 1.0005,
    }
    vti_price = float(payload["bars"]["VTI"][-1]["c"])
    invested_value = 100_000.0
    SQLiteCanonicalPortfolioStore(settings.portfolio_database).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:compounding:invested-baseline",
            portfolio_code="COMPOUNDING",
            display_name="Compounding Portfolio",
            constraint_profile="compounding.v1",
            as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
            starting_capital=250_000.0,
            cash_amount=150_000.0,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="VTI",
                    quantity=invested_value / vti_price,
                    average_cost=vti_price,
                    mark_price=vti_price,
                    updated_at=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
                    instrument_identifier="instrument:us-etf:vti",
                    venue="NYSEARCA",
                    asset_class="us_etf",
                ),
            ),
            source_identifiers=("test-invested-baseline",),
        )
    )

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
    govt = next(
        item
        for item in result.opportunity_queue.ranked
        if item.candidate.instrument.symbol == "GOVT"
    )
    candidate = govt.candidate
    assert candidate.opportunity_cost_return > 0.0425
    assert govt.qualification.baseline_alternative_identifier == "holding:VTI"
    horizon_effective = RobustCandidateAssessor.horizon_return(
        govt.qualification.effective_opportunity_cost,
        horizon_days=candidate.decision_horizon_days,
    )
    scenario_success = round(
        sum(
            item.probability
            for item in candidate.scenario_distribution
            if item.total_return - candidate.implementation_cost_return
            > horizon_effective
        ),
        8,
    )
    assert candidate.probability_of_success == scenario_success
    assert any(
        item.candidate_identifier == candidate.identifier
        for item in result.decisions
    )

    journal = SQLiteCIOJournal(settings.journal_database)
    packet = journal.latest(
        aggregate_identifier=candidate.identifier,
        event_type=CIOJournalEventType.SPECIALIST_PACKET,
    )
    decision = journal.latest(
        aggregate_identifier=candidate.identifier,
        event_type=CIOJournalEventType.CIO_DECISION,
    )
    diagnostic = journal.latest(
        aggregate_identifier=result.identifier,
        event_type=CIOJournalEventType.PERSISTENT_CASH_DIAGNOSTIC,
    )
    assert packet is not None
    assert len(packet.payload["analyses"]) == 6
    assert decision is not None
    assert diagnostic is not None
    observation = next(
        item
        for item in diagnostic.payload["observations"]
        if item["candidate_identifier"] == candidate.identifier
    )
    assert "six_specialist_analysis" in observation["reached_stages"]
    assert "cio_consideration" in observation["reached_stages"]
    assert journal.verify_integrity()
