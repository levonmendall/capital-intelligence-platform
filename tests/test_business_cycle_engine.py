"""Contract tests for the Business Cycle analytical engine."""

from __future__ import annotations

from datetime import date, datetime, timezone

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
from intelligence.business_cycle import (
    BusinessCycleEngine,
    BusinessCycleLoadState,
    build_fred_business_cycle_engine,
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


class FakeBusinessCycleProvider:
    name = "FRED"

    def __init__(
        self,
        *,
        contracting: bool = False,
        stressed: bool = False,
        unavailable: set[str] | None = None,
        stale: bool = False,
        include_future: bool = False,
    ) -> None:
        self.contracting = contracting
        self.stressed = stressed
        self.unavailable = unavailable or set()
        self.stale = stale
        self.include_future = include_future
        self.queries: list[ObservationQuery] = []

    def fetch(
        self,
        query: ObservationQuery,
    ) -> tuple[NormalizedObservation, ...]:
        self.queries.append(query)
        identifier = query.series.provider_series_identifier
        if identifier in self.unavailable:
            raise ProviderError(f"{identifier} unavailable")
        expansion = {
            "GDPC1": (100.0, 104.0),
            "INDPRO": (100.0, 103.0),
            "PCEC96": (100.0, 104.0),
            "PAYEMS": (100.0, 102.5),
            "UNRATE": (4.5, 4.0),
            "ICSA": (250.0, 210.0),
            "PERMIT": (100.0, 115.0),
        }
        prior, latest = expansion[identifier]
        if self.contracting:
            prior, latest = latest, prior
        if self.stressed:
            if identifier == "UNRATE":
                prior, latest = 4.0, 6.0
            elif identifier == "ICSA":
                prior, latest = 210.0, 330.0
        quality = (
            DataQualityState.STALE
            if self.stale
            else DataQualityState.FIXTURE
        )
        values = [
            _observation(
                query,
                prior,
                date(2025, 1, 1),
                quality=quality,
            ),
            _observation(
                query,
                latest,
                date(2026, 1, 15),
                quality=quality,
            ),
        ]
        if self.include_future:
            values.append(
                _observation(
                    query,
                    latest * 1.5,
                    date(2026, 2, 15),
                    retrieved_at=datetime(
                        2026,
                        2,
                        20,
                        20,
                        tzinfo=timezone.utc,
                    ),
                    quality=quality,
                )
            )
        return tuple(values)


def test_complete_fixture_reports_expanding_business_cycle() -> None:
    run = BusinessCycleEngine(
        FakeBusinessCycleProvider(),
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
    contracting = BusinessCycleEngine(
        FakeBusinessCycleProvider(contracting=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    stressed = BusinessCycleEngine(
        FakeBusinessCycleProvider(contracting=True, stressed=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert contracting.direction in {
        EngineDirection.CONTRACTING,
        EngineDirection.STRESSED,
    }
    assert stressed.direction is EngineDirection.STRESSED
    assert stressed.score <= contracting.score


def test_partial_failure_reduces_coverage_without_synthetic_fallback() -> None:
    run = BusinessCycleEngine(
        FakeBusinessCycleProvider(unavailable={"PAYEMS", "PERMIT"}),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 5
    assert run.unavailable_count == 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any("PAYEMS unavailable" in item for item in run.result.risks)
    assert any(
        load.state is BusinessCycleLoadState.UNAVAILABLE
        for load in run.loads
    )


def test_stale_evidence_is_disclosed() -> None:
    result = BusinessCycleEngine(
        FakeBusinessCycleProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in item.lower() for item in result.risks)


def test_future_releases_are_excluded_from_point_in_time_result() -> None:
    result = BusinessCycleEngine(
        FakeBusinessCycleProvider(include_future=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert all(item.released_at <= AS_OF for item in result.evidence)
    assert all(item.observation_date <= AS_OF.date() for item in result.evidence)


def test_missing_fred_credentials_produce_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    run = build_fred_business_cycle_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 0
    assert run.result.direction is EngineDirection.UNAVAILABLE
    assert run.result.data_status is EngineDataStatus.UNAVAILABLE
    assert run.result.coverage == 0
    assert run.result.confidence == 0
