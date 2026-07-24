"""Tests for point-in-time economic-regime evidence construction."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from data import (
    AvailabilityBasis,
    DataQualityState,
    NormalizedObservation,
    ObservationProvenance,
)
from economic_regime import (
    Regime,
    RegimeEvidenceBuilder,
    RegimeScoringRules,
    RegimeSignalName,
)
from providers.fred_series import FRED_SERIES


AS_OF = datetime(
    2026,
    1,
    31,
    23,
    59,
    tzinfo=timezone.utc,
)
CURRENT_DATE = date(2025, 12, 1)
PRIOR_DATE = date(2024, 12, 1)
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "regime_scenarios.json"
)


def _observation(
    series_name: str,
    value: float,
    observation_date: date,
    *,
    released_at: datetime | None = None,
    retrieved_at: datetime | None = None,
    provider: str = "FRED",
    quality_state: DataQualityState = DataQualityState.FIXTURE,
) -> NormalizedObservation:
    series = FRED_SERIES[series_name]
    release_date = observation_date + timedelta(days=20)
    release = released_at or datetime(
        release_date.year,
        release_date.month,
        release_date.day,
        12,
        tzinfo=timezone.utc,
    )
    retrieved = retrieved_at or max(
        release,
        datetime(2026, 1, 31, 22, tzinfo=timezone.utc),
    )
    return NormalizedObservation(
        indicator=series.indicator,
        category=series.category,
        value=value,
        unit=series.unit,
        frequency=series.frequency,
        observation_date=observation_date,
        provenance=ObservationProvenance(
            provider=provider,
            series_identifier=(
                series.provider_series_identifier
            ),
            released_at=release,
            retrieved_at=retrieved,
            quality_state=quality_state,
            availability_basis=AvailabilityBasis.FIXTURE,
        ),
        transformation=series.transformation,
        importance=series.importance,
        stale_after=series.stale_after,
    )


def _scenario_observations(
    scenario: dict,
    *,
    quality_state: DataQualityState = DataQualityState.FIXTURE,
) -> list[NormalizedObservation]:
    observations: list[NormalizedObservation] = []
    for series_name in (
        "industrial_production",
        "consumer_price_index",
        "federal_reserve_total_assets",
    ):
        prior, current = scenario[series_name]
        observations.extend(
            [
                _observation(
                    series_name,
                    prior,
                    PRIOR_DATE,
                    quality_state=quality_state,
                ),
                _observation(
                    series_name,
                    current,
                    CURRENT_DATE,
                    quality_state=quality_state,
                ),
            ]
        )
    observations.extend(
        [
            _observation(
                "federal_funds_rate",
                scenario["federal_funds_rate"],
                CURRENT_DATE,
                quality_state=quality_state,
            ),
            _observation(
                "financial_stress_index",
                scenario["financial_stress_index"],
                CURRENT_DATE,
                quality_state=quality_state,
            ),
        ]
    )
    return observations


def _scenarios() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "scenario",
    _scenarios(),
    ids=lambda item: item["name"],
)
def test_representative_fixture_classifies_each_regime(
    scenario: dict,
) -> None:
    assessment = RegimeEvidenceBuilder().evaluate(
        _scenario_observations(scenario),
        as_of=AS_OF,
    )

    assert assessment.result.regime.value == (
        scenario["expected_regime"]
    )
    assert assessment.evidence.data_coverage == 1.0
    assert assessment.evidence.quality_score == 0.85
    assert assessment.confidence == round(
        assessment.result.confidence * 0.85,
        4,
    )


def test_snapshot_carries_versioned_lineage_for_every_score() -> None:
    scenario = _scenarios()[0]
    snapshot = RegimeEvidenceBuilder(
        RegimeScoringRules(version="fred-us-v1.1")
    ).build(
        _scenario_observations(scenario),
        as_of=AS_OF,
    )

    assert snapshot.rules_version == "fred-us-v1.1"
    assert set(signal.name for signal in snapshot.signals) == set(
        RegimeSignalName
    )
    assert all(signal.lineage for signal in snapshot.signals)
    assert {
        item.series_identifier
        for signal in snapshot.signals
        for item in signal.lineage
    } == {
        "INDPRO",
        "CPIAUCSL",
        "FEDFUNDS",
        "WALCL",
        "STLFSI4",
    }


def test_future_release_cannot_enter_decision_snapshot() -> None:
    scenario = _scenarios()[0]
    observations = _scenario_observations(scenario)
    observations.append(
        _observation(
            "industrial_production",
            150.0,
            date(2026, 1, 1),
            released_at=datetime(
                2026,
                2,
                15,
                12,
                tzinfo=timezone.utc,
            ),
        )
    )

    snapshot = RegimeEvidenceBuilder().build(
        observations,
        as_of=AS_OF,
    )
    growth = next(
        signal
        for signal in snapshot.signals
        if signal.name is RegimeSignalName.GROWTH
    )

    assert growth.score == 0.4
    assert all(
        item.observation_date != date(2026, 1, 1)
        for item in growth.lineage
    )


def test_missing_evidence_reduces_coverage_and_confidence() -> None:
    scenario = _scenarios()[0]
    observations = [
        item
        for item in _scenario_observations(scenario)
        if item.provenance.series_identifier == "STLFSI4"
    ]

    assessment = RegimeEvidenceBuilder().evaluate(
        observations,
        as_of=AS_OF,
    )

    assert assessment.result.regime is Regime.TRANSITION
    assert assessment.evidence.data_coverage == 0.2
    assert assessment.evidence.quality_score == 0.17
    assert assessment.confidence < assessment.result.confidence


def test_stale_dependency_is_disclosed_in_quality_score() -> None:
    scenario = _scenarios()[0]
    live = _scenario_observations(
        scenario,
        quality_state=DataQualityState.LIVE,
    )
    stale = [
        (
            _observation(
                "financial_stress_index",
                item.value,
                item.observation_date,
                quality_state=DataQualityState.STALE,
            )
            if item.provenance.series_identifier == "STLFSI4"
            else item
        )
        for item in live
    ]

    live_snapshot = RegimeEvidenceBuilder().build(
        live,
        as_of=AS_OF,
    )
    stale_snapshot = RegimeEvidenceBuilder().build(
        stale,
        as_of=AS_OF,
    )

    assert live_snapshot.quality_score == 1.0
    assert stale_snapshot.quality_score == 0.9


def test_temporally_expired_live_evidence_is_treated_as_stale() -> None:
    scenario = _scenarios()[0]
    observations = _scenario_observations(
        scenario,
        quality_state=DataQualityState.LIVE,
    )
    observations = [
        (
            _observation(
                "financial_stress_index",
                item.value,
                item.observation_date,
                retrieved_at=datetime(
                    2026,
                    1,
                    1,
                    12,
                    tzinfo=timezone.utc,
                ),
                quality_state=DataQualityState.LIVE,
            )
            if item.provenance.series_identifier == "STLFSI4"
            else item
        )
        for item in observations
    ]

    snapshot = RegimeEvidenceBuilder().build(
        observations,
        as_of=AS_OF,
    )
    stress = next(
        signal
        for signal in snapshot.signals
        if signal.name is RegimeSignalName.FINANCIAL_STRESS
    )

    assert stress.lineage[0].quality_state is DataQualityState.STALE
    assert snapshot.quality_score == 0.9


def test_weekly_year_over_year_uses_nearest_anniversary() -> None:
    scenario = _scenarios()[0]
    observations = _scenario_observations(scenario)
    observations = [
        item
        for item in observations
        if item.provenance.series_identifier != "WALCL"
    ]
    observations.extend(
        [
            _observation(
                "federal_reserve_total_assets",
                100.0,
                date(2024, 12, 4),
            ),
            _observation(
                "federal_reserve_total_assets",
                80.0,
                date(2024, 12, 25),
            ),
            _observation(
                "federal_reserve_total_assets",
                104.0,
                date(2025, 12, 3),
            ),
        ]
    )

    snapshot = RegimeEvidenceBuilder().build(
        observations,
        as_of=AS_OF,
    )
    liquidity = next(
        signal
        for signal in snapshot.signals
        if signal.name is RegimeSignalName.LIQUIDITY
    )

    assert liquidity.score == 0.2
    assert liquidity.lineage[1].observation_date == date(
        2024,
        12,
        4,
    )


def test_provider_collision_cannot_supply_fred_signal() -> None:
    scenario = _scenarios()[0]
    observations = [
        item
        for item in _scenario_observations(scenario)
        if item.provenance.series_identifier != "INDPRO"
    ]
    observations.extend(
        [
            _observation(
                "industrial_production",
                100.0,
                PRIOR_DATE,
                provider="OTHER",
            ),
            _observation(
                "industrial_production",
                110.0,
                CURRENT_DATE,
                provider="OTHER",
            ),
        ]
    )

    snapshot = RegimeEvidenceBuilder().build(
        observations,
        as_of=AS_OF,
    )
    growth = next(
        signal
        for signal in snapshot.signals
        if signal.name is RegimeSignalName.GROWTH
    )

    assert growth.score is None
    assert growth.lineage == ()


def test_year_over_year_pair_respects_tolerance() -> None:
    scenario = _scenarios()[0]
    observations = [
        item
        for item in _scenario_observations(scenario)
        if item.provenance.series_identifier != "INDPRO"
    ]
    observations.extend(
        [
            _observation(
                "industrial_production",
                100.0,
                date(2024, 9, 1),
            ),
            _observation(
                "industrial_production",
                102.0,
                CURRENT_DATE,
            ),
        ]
    )

    snapshot = RegimeEvidenceBuilder(
        RegimeScoringRules(
            year_over_year_tolerance_days=45
        )
    ).build(
        observations,
        as_of=AS_OF,
    )
    growth = next(
        signal
        for signal in snapshot.signals
        if signal.name is RegimeSignalName.GROWTH
    )

    assert growth.score is None
