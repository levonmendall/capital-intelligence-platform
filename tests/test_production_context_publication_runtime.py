from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.config import ApiSettings
from application import ProductionCanonicalCIOExecutor
from application.cio_cycle import CanonicalCIOCycle
from application.production_context_adapter import build_production_context_provider
from cio.persistence import SQLiteCIOJournal
from operations.free_paper_pilot import load_free_paper_pilot_universe
from portfolio.state import (
    CanonicalPortfolioPosition,
    CanonicalPortfolioSnapshot,
    SQLiteCanonicalPortfolioStore,
)
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


def _series(decision_time: datetime, *, annual_return: float, count: int = 800):
    daily = (1.0 + annual_return) ** (1.0 / 252.0) - 1.0
    rows = []
    price = 100.0
    start = decision_time - timedelta(days=count)
    for index in range(count):
        price *= 1.0 + daily
        observed = start + timedelta(days=index, hours=20)
        if observed >= decision_time:
            observed = decision_time - timedelta(hours=count - index)
        rows.append(
            {
                "t": observed.isoformat(),
                "c": price,
                "v": 5_000_000.0,
            }
        )
    rows.sort(key=lambda item: item["t"])
    return rows


def _evidence(decision_time: datetime):
    universe = load_free_paper_pilot_universe()
    bars = {}
    quotes = {}
    for item in universe.instruments:
        annual_return = 0.32 if item.symbol == "VTI" else 0.01
        rows = _series(decision_time, annual_return=annual_return)
        bars[item.symbol] = rows
        price = float(rows[-1]["c"])
        quotes[item.symbol] = {
            "t": (decision_time - timedelta(seconds=30)).isoformat(),
            "bp": price * 0.9995,
            "ap": price * 1.0005,
        }
    return {
        "bars": bars,
        "quotes": quotes,
        "macro": {
            "DGS10": {"date": "2026-07-28", "value": 4.25},
            "T10Y2Y": {"date": "2026-07-28", "value": 0.35},
            "VIXCLS": {"date": "2026-07-28", "value": 16.0},
            "FEDFUNDS": {"date": "2026-07-28", "value": 4.25},
        },
    }


def _provider(settings: ApiSettings, tmp_path):
    return build_production_context_provider(
        eligible_universe_database=tmp_path / "eligible_universe.db",
        screening_database=settings.full_universe_screening_database,
        portfolio_database=settings.portfolio_database,
        context_database=tmp_path / "production_context.db",
        asset_evidence_database=tmp_path / "asset_specific_evidence.db",
        code_version="test",
    )


def _executor(settings: ApiSettings, tmp_path):
    return ProductionCanonicalCIOExecutor(
        cycle=CanonicalCIOCycle(
            journal=SQLiteCIOJournal(settings.journal_database)
        ),
        screening_store=SQLiteFullUniverseScreeningStore(
            settings.full_universe_screening_database
        ),
        context_provider=_provider(settings, tmp_path),
    )


def test_publisher_creates_candidates_and_executable_cio_construction(tmp_path) -> None:
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
        clock=lambda: decision_time,
    )

    assert result.ready is True
    assert result.decision_as_of == decision_time
    assert result.candidate_count == 15
    assert result.exclusion_count == 0

    cycle = _executor(settings, tmp_path).run(as_of=decision_time)

    assert cycle.opportunity_queue.ranked
    assert any(item.candidate.instrument.symbol == "VTI" for item in cycle.opportunity_queue.ranked)
    assert cycle.decisions
    assert cycle.construction is not None
    assert cycle.construction.trades
    assert any(item.symbol == "VTI" for item in cycle.construction.trades)
    assert cycle.briefing.decision_identifier


def test_next_day_cycle_certifies_every_holding_and_routes_holding_review(tmp_path) -> None:
    settings = _settings(tmp_path)
    first_schedule = datetime(2026, 7, 29, 11, 0, tzinfo=timezone.utc)
    first_time = datetime(2026, 7, 29, 20, 45, tzinfo=timezone.utc)
    _bootstrap_cash_portfolio(
        settings,
        as_of=datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc),
    )
    first = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=first_schedule,
        readiness_probe=lambda _universe: _readiness(first_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-28", value=4.25),
        evidence_probe=lambda _universe, _as_of: _evidence(first_time),
        clock=lambda: first_time,
    )
    first_cycle = _executor(settings, tmp_path).run(as_of=first_time)
    assert first.ready
    assert first_cycle.construction is not None
    target_weights = dict(first_cycle.construction.target_weights)
    vti_weight = target_weights.get("VTI", 0.0)
    assert vti_weight > 0.0

    next_time = datetime(2026, 7, 30, 20, 45, tzinfo=timezone.utc)
    next_payload = _evidence(next_time)
    vti_price = float(next_payload["bars"]["VTI"][-1]["c"])
    market_value = 250_000.0 * vti_weight
    SQLiteCanonicalPortfolioStore(settings.portfolio_database).append(
        CanonicalPortfolioSnapshot(
            identifier="portfolio:compounding:after-first-fill",
            portfolio_code="COMPOUNDING",
            display_name="Compounding Portfolio",
            constraint_profile="compounding.v1",
            as_of=first_time + timedelta(hours=1),
            starting_capital=250_000.0,
            cash_amount=250_000.0 - market_value,
            positions=(
                CanonicalPortfolioPosition(
                    symbol="VTI",
                    quantity=market_value / vti_price,
                    average_cost=vti_price,
                    mark_price=vti_price,
                    updated_at=first_time + timedelta(hours=1),
                    instrument_identifier="instrument:us-etf:vti",
                    venue="NYSEARCA",
                    asset_class="us_etf",
                ),
            ),
            source_identifiers=("test-paper-fill",),
        )
    )

    second = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=datetime(2026, 7, 30, 11, 0, tzinfo=timezone.utc),
        readiness_probe=lambda _universe: _readiness(next_time),
        cash_probe=lambda: SimpleNamespace(date="2026-07-29", value=4.20),
        evidence_probe=lambda _universe, _as_of: next_payload,
        clock=lambda: next_time,
    )
    assert second.ready
    context = _provider(settings, tmp_path).load_context(as_of=next_time)
    assert tuple(item.symbol for item in context.portfolio.positions) == ("VTI",)
    assert context.opportunity_context.best_alternative().identifier
    second_cycle = _executor(settings, tmp_path).run(as_of=next_time)
    assert any(
        item.candidate.instrument.symbol == "VTI"
        for item in second_cycle.opportunity_queue.holding_reviews
    )


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
        evidence_probe=lambda _universe, _as_of: _evidence(decision_time),
        clock=lambda: decision_time,
    )

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("completed publication should be reused")

    second = prepare_production_context_for_cycle(
        settings=settings,
        scheduled_for=scheduled_for,
        readiness_probe=should_not_run,
        cash_probe=should_not_run,
        evidence_probe=should_not_run,
        clock=lambda: decision_time + timedelta(minutes=5),
    )

    assert first.ready is True
    assert second.state == "reused"
    assert second.decision_as_of == first.decision_as_of
    assert second.context_identifier == first.context_identifier
    assert second.candidate_count == first.candidate_count
