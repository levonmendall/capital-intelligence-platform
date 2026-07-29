from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.config import ApiSettings
from application import ProductionCanonicalCIOExecutor
from application.cio_cycle import CanonicalCIOCycle
from application.production_context_adapter import build_production_context_provider
from cio.persistence import SQLiteCIOJournal
from operations.free_paper_pilot import load_free_paper_pilot_universe
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore
from production_context_publication_runtime import prepare_production_context_for_cycle
from screening import SQLiteFullUniverseScreeningStore


def _settings(tmp_path) -> ApiSettings:
    return ApiSettings(
        portfolio_database=tmp_path / "canonical_portfolio.db",
        journal_database=tmp_path / "institutional_journal.db",
        full_universe_screening_database=tmp_path / "full_universe_screening.db",
    )


def _bootstrap_cash_portfolio(settings: ApiSettings, *, as_of: datetime) -> None:
    SQLiteCanonicalPortfolioStore(settings.portfolio_database).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:compounding:bootstrap",
            portfolio_code="COMPOUNDING",
            display_name="Compounding Portfolio",
            constraint_profile="compounding.v1",
            as_of=as_of,
            starting_capital=250_000.0,
            cash_amount=250_000.0,
            positions=(),
            source_identifiers=("paper-bootstrap",),
        )
    )


def _readiness(decision_time: datetime):
    universe = load_free_paper_pilot_universe()
    observed = (decision_time - timedelta(seconds=30)).isoformat()
    return SimpleNamespace(
        configuration_ready=True,
        account_status="ACTIVE",
        validated_symbols=tuple(item.symbol for item in universe.instruments),
        quote_timestamps=tuple(
            (item.symbol, observed) for item in universe.instruments
        ),
        blockers=(),
        warnings=(),
    )


def test_publisher_creates_complete_no_candidate_context_and_cio_briefing(
    tmp_path,
) -> None:
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
        clock=lambda: decision_time,
    )

    assert result.ready is True
    assert result.decision_as_of == decision_time
    assert result.candidate_count == 0
    assert result.exclusion_count == result.instrument_count == 15

    provider = build_production_context_provider(
        eligible_universe_database=tmp_path / "eligible_universe.db",
        screening_database=settings.full_universe_screening_database,
        portfolio_database=settings.portfolio_database,
        context_database=tmp_path / "production_context.db",
        asset_evidence_database=tmp_path / "asset_specific_evidence.db",
        code_version="test",
    )
    screening_store = SQLiteFullUniverseScreeningStore(
        settings.full_universe_screening_database
    )
    executor = ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(
            journal=SQLiteCIOJournal(settings.journal_database)
        ),
        screening_store=screening_store,
        context_provider=provider,
    )

    cycle = executor.run(as_of=decision_time)

    assert cycle.decisions == ()
    assert cycle.construction is None
    assert cycle.opportunity_queue.ranked == ()
    assert cycle.briefing.identifier
    publication = screening_store.publication(
        result.screening_publication_identifier.replace(
            "publication:paper-pilot:",
            "screening:paper-pilot:",
        )
    )
    assert publication is not None
    assert publication.screened_instrument_count == 15
    assert publication.candidate_count == 0
    assert publication.excluded_count == 15


def test_completed_publication_is_reused_without_new_provider_calls(tmp_path) -> None:
    settings = _settings(tmp_path)
    scheduled_for = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    decision_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
    )
    first = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=lambda _universe: _readiness(decision_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),
        clock=lambda: decision_time,
    )

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("completed publication should be reused")

    second = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=should_not_run,
        cash_probe=should_not_run,
        clock=lambda: decision_time + timedelta(minutes=5),
    )

    assert first.ready is True
    assert second.state == "reused"
    assert second.decision_as_of == first.decision_as_of
    assert second.context_identifier == first.context_identifier
