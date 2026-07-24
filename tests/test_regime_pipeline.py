"""Tests for the canonical institutional regime pipeline."""

from __future__ import annotations

import argparse
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
from economic_regime import Regime
from intelligence.regime_pipeline import (
    InstitutionalRegimePipeline,
    REGIME_FRED_REQUESTS_BY_SIGNAL,
    SeriesLoadState,
    build_fred_regime_pipeline,
)
from run_regime import _parse_as_of, format_run


AS_OF = datetime(
    2026,
    1,
    31,
    23,
    59,
    tzinfo=timezone.utc,
)
RETRIEVED_AT = datetime(
    2026,
    1,
    31,
    22,
    tzinfo=timezone.utc,
)


def _observation(
    query: ObservationQuery,
    value: float,
    observation_date: date,
) -> NormalizedObservation:
    series = query.series
    return NormalizedObservation(
        indicator=series.indicator,
        category=series.category,
        value=value,
        unit=series.unit,
        frequency=series.frequency,
        observation_date=observation_date,
        provenance=ObservationProvenance(
            provider="FRED",
            series_identifier=(
                series.provider_series_identifier
            ),
            released_at=datetime(
                observation_date.year,
                observation_date.month,
                min(observation_date.day + 15, 28),
                12,
                tzinfo=timezone.utc,
            ),
            retrieved_at=RETRIEVED_AT,
            quality_state=DataQualityState.LIVE,
            availability_basis=(
                AvailabilityBasis.PROVIDER_TIMESTAMP
            ),
        ),
        transformation=series.transformation,
        importance=series.importance,
        stale_after=series.stale_after,
    )


class FakeRegimeProvider:
    """Offline provider returning a complete Goldilocks fixture."""

    name = "FRED"

    def __init__(
        self,
        *,
        unavailable: set[str] | None = None,
    ) -> None:
        self.unavailable = unavailable or set()
        self.queries: list[ObservationQuery] = []

    def fetch(
        self,
        query: ObservationQuery,
    ) -> tuple[NormalizedObservation, ...]:
        self.queries.append(query)
        series_id = query.series.provider_series_identifier
        if series_id in self.unavailable:
            raise ProviderError(f"{series_id} unavailable")

        prior = date(2024, 12, 1)
        current = date(2025, 12, 1)
        values = {
            "INDPRO": (
                _observation(query, 100.0, prior),
                _observation(query, 102.0, current),
            ),
            "CPIAUCSL": (
                _observation(query, 300.0, prior),
                _observation(query, 307.5, current),
            ),
            "FEDFUNDS": (
                _observation(query, 3.0, current),
            ),
            "WALCL": (
                _observation(query, 100.0, prior),
                _observation(query, 104.0, current),
            ),
            "STLFSI4": (
                _observation(query, 0.2, current),
            ),
        }
        return values[series_id]


def test_pipeline_runs_complete_point_in_time_workflow() -> None:
    provider = FakeRegimeProvider()

    run = InstitutionalRegimePipeline(provider).run(
        as_of=AS_OF
    )

    assert run.provider == "FRED"
    assert run.loaded_count == 5
    assert run.unavailable_count == 0
    assert not run.degraded
    assert run.assessment.result.regime is Regime.GOLDILOCKS
    assert run.assessment.evidence.data_coverage == 1.0
    assert run.assessment.evidence.quality_score == 1.0
    assert all(query.as_of == AS_OF for query in provider.queries)


def test_pipeline_uses_frequency_appropriate_lookbacks() -> None:
    provider = FakeRegimeProvider()

    InstitutionalRegimePipeline(provider).run(as_of=AS_OF)

    limits = {
        query.series.provider_series_identifier: query.limit
        for query in provider.queries
    }
    assert limits == {
        "INDPRO": 18,
        "CPIAUCSL": 18,
        "FEDFUNDS": 18,
        "WALCL": 60,
        "STLFSI4": 8,
    }
    assert (
        REGIME_FRED_REQUESTS_BY_SIGNAL["liquidity"].limit
        == 60
    )


def test_partial_provider_failure_is_disclosed_without_fallback() -> None:
    provider = FakeRegimeProvider(
        unavailable={"STLFSI4"}
    )

    run = InstitutionalRegimePipeline(provider).run(
        as_of=AS_OF
    )

    assert run.loaded_count == 4
    assert run.unavailable_count == 1
    assert run.degraded
    failure = next(
        load
        for load in run.loads
        if load.state is SeriesLoadState.UNAVAILABLE
    )
    assert failure.request.signal == "financial_stress"
    assert failure.error == "STLFSI4 unavailable"
    assert run.assessment.evidence.data_coverage == 0.8
    assert run.assessment.evidence.quality_score == 0.8


def test_missing_credentials_produce_explicit_zero_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    run = build_fred_regime_pipeline().run(as_of=AS_OF)

    assert run.loaded_count == 0
    assert run.unavailable_count == 5
    assert run.assessment.result.regime is Regime.TRANSITION
    assert run.assessment.evidence.data_coverage == 0.0
    assert run.assessment.evidence.quality_score == 0.0
    assert run.assessment.confidence == 0.0
    assert all(
        "FRED_API_KEY is not configured" in load.error
        for load in run.loads
    )


def test_run_current_uses_injected_timezone_aware_clock() -> None:
    provider = FakeRegimeProvider()
    pipeline = InstitutionalRegimePipeline(
        provider,
        clock=lambda: AS_OF,
    )

    run = pipeline.run_current()

    assert run.as_of == AS_OF


def test_pipeline_rejects_naive_decision_time() -> None:
    with pytest.raises(
        ValueError,
        match="as_of must be timezone-aware",
    ):
        InstitutionalRegimePipeline(
            FakeRegimeProvider()
        ).run(
            as_of=datetime(2026, 1, 31)
        )


def test_cli_format_discloses_unavailable_series() -> None:
    run = InstitutionalRegimePipeline(
        FakeRegimeProvider(unavailable={"WALCL"})
    ).run(as_of=AS_OF)

    rendered = format_run(run)

    assert "Series loaded: 4/5" in rendered
    assert "Evidence coverage: 80%" in rendered
    assert "- liquidity: WALCL unavailable" in rendered


def test_cli_as_of_requires_timezone() -> None:
    assert _parse_as_of("2026-01-31T12:00:00Z") == datetime(
        2026,
        1,
        31,
        12,
        tzinfo=timezone.utc,
    )

    with pytest.raises(
        argparse.ArgumentTypeError,
        match="timezone",
    ):
        _parse_as_of("2026-01-31T12:00:00")
