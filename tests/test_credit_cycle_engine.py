"""Contract tests for the Credit Cycle analytical engine."""

from __future__ import annotations

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
from intelligence.credit_cycle import (
    CreditCycleEngine,
    CreditCycleLoadState,
    build_fred_credit_cycle_engine,
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
        observation_date.day,
        12,
        tzinfo=timezone.utc,
    ) + timedelta(days=1)
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


class FakeCreditCycleProvider:
    name = "FRED"

    def __init__(
        self,
        *,
        contracting: bool = False,
        stressed: bool = False,
        high_yield_only_stress: bool = False,
        unavailable: set[str] | None = None,
        stale: bool = False,
        include_future: bool = False,
    ) -> None:
        self.contracting = contracting
        self.stressed = stressed
        self.high_yield_only_stress = high_yield_only_stress
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
            "BAMLH0A0HYM2": (5.0, 3.0),
            "BAMLC0A0CM": (1.8, 1.0),
            "DRTSCILM": (15.0, -5.0),
            "BUSLOANS": (100.0, 108.0),
            "DRBLACBS": (2.2, 1.2),
            "BAMLH0A0HYM2EY": (9.0, 6.0),
        }
        prior, latest = expansion[identifier]
        if self.contracting:
            contraction = {
                "BAMLH0A0HYM2": (3.0, 6.5),
                "BAMLC0A0CM": (1.0, 2.2),
                "DRTSCILM": (-5.0, 35.0),
                "BUSLOANS": (108.0, 100.0),
                "DRBLACBS": (1.2, 2.8),
                "BAMLH0A0HYM2EY": (6.0, 9.5),
            }
            prior, latest = contraction[identifier]
        if self.stressed:
            stress = {
                "BAMLH0A0HYM2": (4.0, 9.0),
                "BAMLC0A0CM": (1.2, 3.2),
                "DRTSCILM": (10.0, 65.0),
                "BUSLOANS": (108.0, 92.0),
                "DRBLACBS": (1.5, 4.0),
                "BAMLH0A0HYM2EY": (7.0, 13.0),
            }
            prior, latest = stress[identifier]
        if self.high_yield_only_stress:
            if identifier == "BAMLH0A0HYM2":
                prior, latest = 4.0, 9.0
            else:
                prior, latest = expansion[identifier]
        quality = (
            DataQualityState.STALE
            if self.stale
            else DataQualityState.FIXTURE
        )
        daily_identifiers = {
            "BAMLH0A0HYM2",
            "BAMLC0A0CM",
            "BAMLH0A0HYM2EY",
        }
        latest_date = (
            date(2026, 1, 15)
            if self.stale
            else (
                date(2026, 1, 29)
                if identifier in daily_identifiers
                else date(2026, 1, 15)
            )
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
                latest_date,
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


def test_complete_fixture_reports_expanding_credit_cycle() -> None:
    run = CreditCycleEngine(
        FakeCreditCycleProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 6
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 60
    assert run.result.confidence >= 80
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 6
    assert all(item.released_at <= AS_OF for item in run.result.evidence)


def test_tightening_and_stressed_fixtures_are_distinct() -> None:
    tightening = CreditCycleEngine(
        FakeCreditCycleProvider(contracting=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    stressed = CreditCycleEngine(
        FakeCreditCycleProvider(stressed=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert tightening.direction in {
        EngineDirection.CONTRACTING,
        EngineDirection.STRESSED,
    }
    assert stressed.direction is EngineDirection.STRESSED
    assert stressed.score <= tightening.score


def test_single_spread_shock_requires_confirmation_for_stress() -> None:
    result = CreditCycleEngine(
        FakeCreditCycleProvider(high_yield_only_stress=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is not EngineDirection.STRESSED
    assert any(
        item.component == "high_yield_spread"
        and item.signal_score <= -0.75
        for item in result.evidence
    )


def test_partial_failure_reduces_coverage_without_synthetic_fallback() -> None:
    run = CreditCycleEngine(
        FakeCreditCycleProvider(
            unavailable={"DRTSCILM", "DRBLACBS"},
        ),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 4
    assert run.unavailable_count == 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any("DRTSCILM unavailable" in item for item in run.result.risks)
    assert any(
        load.state is CreditCycleLoadState.UNAVAILABLE
        for load in run.loads
    )


def test_stale_evidence_is_disclosed() -> None:
    result = CreditCycleEngine(
        FakeCreditCycleProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in item.lower() for item in result.risks)


def test_future_releases_are_excluded_from_point_in_time_result() -> None:
    result = CreditCycleEngine(
        FakeCreditCycleProvider(include_future=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert all(item.released_at <= AS_OF for item in result.evidence)
    assert all(
        item.observation_date <= AS_OF.date()
        for item in result.evidence
    )


def test_missing_fred_credentials_produce_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    run = build_fred_credit_cycle_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 0
    assert run.result.direction is EngineDirection.UNAVAILABLE
    assert run.result.data_status is EngineDataStatus.UNAVAILABLE
    assert run.result.coverage == 0
    assert run.result.confidence == 0
