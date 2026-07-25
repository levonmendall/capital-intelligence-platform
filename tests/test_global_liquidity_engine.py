"""Contract tests for the Global Liquidity analytical engine."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from data import (
    AvailabilityBasis,
    DataQualityState,
    NormalizedObservation,
    ObservationProvenance,
    ObservationQuery,
    ProviderError,
)
from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.engine_store import SQLiteAnalyticalEngineStore
from intelligence.global_liquidity import (
    GlobalLiquidityEngine,
    LiquidityLoadState,
    build_fred_global_liquidity_engine,
)


AS_OF = datetime(2026, 1, 31, 20, tzinfo=timezone.utc)


def _observation(
    query: ObservationQuery,
    value: float,
    observation_date: date,
    *,
    retrieved_at: datetime = AS_OF,
    quality: DataQualityState = DataQualityState.FIXTURE,
) -> NormalizedObservation:
    series = query.series
    released_at = datetime(
        observation_date.year,
        observation_date.month,
        min(observation_date.day + 1, 28),
        12,
        tzinfo=timezone.utc,
    )
    return NormalizedObservation(
        indicator=series.indicator,
        category=series.category,
        value=value,
        unit=series.unit,
        frequency=series.frequency,
        observation_date=observation_date,
        provenance=ObservationProvenance(
            provider="FRED",
            series_identifier=series.provider_series_identifier,
            released_at=released_at,
            retrieved_at=retrieved_at,
            quality_state=quality,
            availability_basis=AvailabilityBasis.FIXTURE,
            vintage_date=observation_date,
        ),
        transformation=series.transformation,
        importance=series.importance,
        stale_after=series.stale_after,
    )


class FakeLiquidityProvider:
    name = "FRED"

    def __init__(
        self,
        *,
        contracting: bool = False,
        stressed: bool = False,
        unavailable: set[str] | None = None,
        stale: bool = False,
    ) -> None:
        self.contracting = contracting
        self.stressed = stressed
        self.unavailable = unavailable or set()
        self.stale = stale
        self.queries: list[ObservationQuery] = []

    def fetch(
        self,
        query: ObservationQuery,
    ) -> tuple[NormalizedObservation, ...]:
        self.queries.append(query)
        identifier = query.series.provider_series_identifier
        if identifier in self.unavailable:
            raise ProviderError(f"{identifier} unavailable")
        expanding = {
            "WALCL": (8_000.0, 8_400.0),
            "WRESBAL": (3_000.0, 3_300.0),
            "WTREGEN": (800.0, 560.0),
            "RRPONTSYD": (500.0, 250.0),
            "M2SL": (21_000.0, 21_840.0),
            "DTWEXBGS": (120.0, 115.2),
            "NFCI": (-0.20, -0.50),
        }
        prior, latest = expanding[identifier]
        if self.contracting:
            prior, latest = latest, prior
        if self.stressed and identifier == "NFCI":
            latest = 1.20
        quality = (
            DataQualityState.STALE
            if self.stale
            else DataQualityState.FIXTURE
        )
        return (
            _observation(
                query,
                prior,
                date(2025, 10, 1),
                quality=quality,
            ),
            _observation(
                query,
                latest,
                date(2026, 1, 15),
                quality=quality,
            ),
        )


def test_complete_fixture_reports_expanding_liquidity() -> None:
    run = GlobalLiquidityEngine(
        FakeLiquidityProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 7
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 60
    assert run.result.confidence >= 80
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 7
    assert all(item.released_at <= AS_OF for item in run.result.evidence)


def test_contracting_and_stressed_fixtures_are_distinct() -> None:
    contracting = GlobalLiquidityEngine(
        FakeLiquidityProvider(contracting=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    stressed = GlobalLiquidityEngine(
        FakeLiquidityProvider(contracting=True, stressed=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert contracting.direction in {
        EngineDirection.CONTRACTING,
        EngineDirection.STRESSED,
    }
    assert stressed.direction is EngineDirection.STRESSED
    assert stressed.score <= contracting.score


def test_partial_failure_reduces_coverage_without_synthetic_fallback() -> None:
    run = GlobalLiquidityEngine(
        FakeLiquidityProvider(unavailable={"WRESBAL", "M2SL"}),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 5
    assert run.unavailable_count == 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any("WRESBAL unavailable" in item for item in run.result.risks)
    assert any(
        load.state is LiquidityLoadState.UNAVAILABLE
        for load in run.loads
    )


def test_stale_evidence_is_disclosed() -> None:
    result = GlobalLiquidityEngine(
        FakeLiquidityProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in item.lower() for item in result.risks)


def test_missing_fred_credentials_produce_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    run = build_fred_global_liquidity_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 0
    assert run.result.direction is EngineDirection.UNAVAILABLE
    assert run.result.data_status is EngineDataStatus.UNAVAILABLE
    assert run.result.coverage == 0
    assert run.result.confidence == 0


def test_store_is_append_only_idempotent_and_point_in_time(tmp_path) -> None:
    store = SQLiteAnalyticalEngineStore(tmp_path / "engines.db")
    first = GlobalLiquidityEngine(
        FakeLiquidityProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    second_as_of = AS_OF + timedelta(days=1)
    second = GlobalLiquidityEngine(
        FakeLiquidityProvider(contracting=True),
        clock=lambda: second_as_of,
    ).run(as_of=second_as_of).result

    store.append(first)
    store.append(first)
    store.append(second)

    assert store.latest("global_liquidity").identifier == second.identifier
    assert (
        store.latest(
            "global_liquidity",
            at_or_before=AS_OF,
        ).identifier
        == first.identifier
    )
    assert [item.identifier for item in store.history("global_liquidity")] == [
        second.identifier,
        first.identifier,
    ]
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE analytical_engine_results SET policy_version = 'changed'"
            )
