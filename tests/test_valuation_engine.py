"""Contract tests for the Valuation analytical engine."""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, datetime, timezone

from data import DataQualityState
from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.valuation import (
    JSONValuationProvider,
    UnavailableValuationProvider,
    ValuationDataset,
    ValuationEngine,
    ValuationLoadState,
    ValuationMetric,
    ValuationObservation,
    build_configured_valuation_engine,
)


AS_OF = datetime(2026, 1, 31, 21, tzinfo=timezone.utc)


def _month(year: int, month: int, offset: int) -> date:
    total = year * 12 + (month - 1) + offset
    resolved_year, resolved_month_zero = divmod(total, 12)
    resolved_month = resolved_month_zero + 1
    return date(
        resolved_year,
        resolved_month,
        min(15, monthrange(resolved_year, resolved_month)[1]),
    )


def _dataset(
    mode: str = "attractive",
    *,
    missing: set[ValuationMetric] | None = None,
    stale: bool = False,
    negative: ValuationMetric | None = None,
    include_future: bool = False,
) -> ValuationDataset:
    missing = missing or set()
    observations: list[ValuationObservation] = []
    for index, metric in enumerate(ValuationMetric):
        if metric in missing:
            continue
        base = 0.025 + 0.003 * index
        for offset in range(18):
            observation_date = _month(
                2023 if stale else 2024,
                12 if stale else 6,
                offset,
            )
            available_at = datetime(
                observation_date.year,
                observation_date.month,
                min(observation_date.day + 1, 28),
                12,
                tzinfo=timezone.utc,
            )
            observations.append(
                ValuationObservation(
                    metric=metric,
                    value=base + 0.0002 * offset,
                    observation_date=observation_date,
                    available_at=available_at,
                    retrieved_at=available_at,
                    quality_state=DataQualityState.FIXTURE,
                    source_identifier="fixture:valuation",
                    benchmark="US_EQUITY_TEST",
                    methodology_version="fixture-method.v1",
                )
            )
        latest_date = date(2025, 6, 15) if stale else date(2026, 1, 15)
        available_at = datetime(
            latest_date.year,
            latest_date.month,
            min(latest_date.day + 1, 28),
            12,
            tzinfo=timezone.utc,
        )
        if mode == "attractive":
            latest_value = base + 0.020
        elif mode == "stretched":
            latest_value = max(0.0001, base - 0.020)
        elif mode == "mixed":
            latest_value = base + (0.020 if index % 2 == 0 else -0.020)
        elif mode == "median":
            latest_value = base + 0.0017
        elif mode == "one_cheap":
            latest_value = base + (0.020 if index == 0 else -0.005)
        else:
            raise ValueError(f"unsupported fixture mode: {mode}")
        if negative is metric:
            latest_value = -0.01
        observations.append(
            ValuationObservation(
                metric=metric,
                value=latest_value,
                observation_date=latest_date,
                available_at=available_at,
                retrieved_at=available_at,
                quality_state=(
                    DataQualityState.STALE
                    if stale
                    else DataQualityState.FIXTURE
                ),
                source_identifier="fixture:valuation",
                benchmark="US_EQUITY_TEST",
                methodology_version="fixture-method.v1",
            )
        )
        if include_future:
            future_date = date(2026, 2, 15)
            future_available = datetime(
                2026, 2, 16, 12, tzinfo=timezone.utc
            )
            observations.append(
                ValuationObservation(
                    metric=metric,
                    value=0.50,
                    observation_date=future_date,
                    available_at=future_available,
                    retrieved_at=future_available,
                    quality_state=DataQualityState.FIXTURE,
                    source_identifier="fixture:valuation",
                    benchmark="US_EQUITY_TEST",
                    methodology_version="fixture-method.v1",
                )
            )
    return ValuationDataset(
        provider="FIXTURE",
        source_identifier="fixture:valuation",
        source_fingerprint=hashlib.sha256(b"valuation-fixture").hexdigest(),
        benchmark="US_EQUITY_TEST",
        currency="USD",
        methodology_version="fixture-method.v1",
        retrieved_at=max(item.retrieved_at for item in observations),
        observations=tuple(observations),
    )


class FakeValuationProvider:
    name = "FIXTURE"

    def __init__(
        self,
        mode: str = "attractive",
        *,
        missing: set[ValuationMetric] | None = None,
        stale: bool = False,
        negative: ValuationMetric | None = None,
        include_future: bool = False,
    ) -> None:
        self.dataset = _dataset(
            mode,
            missing=missing,
            stale=stale,
            negative=negative,
            include_future=include_future,
        )

    def fetch(self, *, as_of: datetime) -> ValuationDataset:
        del as_of
        return self.dataset


def test_complete_fixture_reports_broad_valuation_support() -> None:
    run = ValuationEngine(
        FakeValuationProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 6
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 70
    assert run.result.confidence >= 80
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 6


def test_broadly_compressed_yields_report_stretched_valuation() -> None:
    result = ValuationEngine(
        FakeValuationProvider("stretched"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.STRESSED
    assert result.score <= 25
    assert any(
        "drawdown" in item.lower()
        for item in result.transmission_channels
    )


def test_mixed_valuation_evidence_remains_neutral() -> None:
    result = ValuationEngine(
        FakeValuationProvider("mixed"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.NEUTRAL
    assert any("mixed" in risk.lower() for risk in result.risks)


def test_one_attractive_multiple_cannot_define_the_market() -> None:
    result = ValuationEngine(
        FakeValuationProvider("one_cheap"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is not EngineDirection.EXPANDING


def test_nonpositive_earnings_yield_is_excluded_not_called_cheap() -> None:
    run = ValuationEngine(
        FakeValuationProvider(
            "median",
            negative=ValuationMetric.EARNINGS_YIELD,
        ),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    earnings = next(
        load
        for load in run.loads
        if load.metric is ValuationMetric.EARNINGS_YIELD
    )
    assert earnings.state is ValuationLoadState.UNAVAILABLE
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert run.result.coverage < 1
    assert "non-positive" in (earnings.error or "")


def test_missing_metrics_reduce_coverage_without_imputation() -> None:
    run = ValuationEngine(
        FakeValuationProvider(
            missing={
                ValuationMetric.BOOK_YIELD,
                ValuationMetric.DIVIDEND_YIELD,
            }
        ),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 4
    assert run.unavailable_count == 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any(
        "reduced coverage" in risk.lower()
        for risk in run.result.risks
    )


def test_stale_valuation_evidence_is_disclosed() -> None:
    result = ValuationEngine(
        FakeValuationProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in risk.lower() for risk in result.risks)


def test_future_observations_are_excluded() -> None:
    result = ValuationEngine(
        FakeValuationProvider(include_future=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert all(item.released_at <= AS_OF for item in result.evidence)
    assert all(
        item.observation_date <= AS_OF.date()
        for item in result.evidence
    )


def test_unconfigured_provider_returns_explicit_unavailable_result() -> None:
    result = ValuationEngine(
        UnavailableValuationProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert result.data_status is EngineDataStatus.UNAVAILABLE
    assert result.coverage == 0
    assert result.confidence == 0


def test_configured_builder_is_unavailable_without_source(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_VALUATION_FILE", raising=False)

    result = build_configured_valuation_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert "not configured" in result.explanation


def test_json_provider_filters_future_data_and_fingerprints_source(
    tmp_path,
) -> None:
    observations = []
    for metric in ValuationMetric:
        for offset in range(13):
            observation_date = _month(2024, 12, offset)
            available_at = datetime(
                observation_date.year,
                observation_date.month,
                min(observation_date.day + 1, 28),
                12,
                tzinfo=timezone.utc,
            )
            observations.append(
                {
                    "metric": metric.value,
                    "value": 0.03 + 0.001 * offset,
                    "observation_date": observation_date.isoformat(),
                    "available_at": available_at.isoformat(),
                    "retrieved_at": available_at.isoformat(),
                    "quality_state": "fixture",
                }
            )
        observations.append(
            {
                "metric": metric.value,
                "value": 0.90,
                "observation_date": "2026-02-15",
                "available_at": "2026-02-16T12:00:00+00:00",
                "retrieved_at": "2026-02-16T12:00:00+00:00",
                "quality_state": "fixture",
            }
        )
    payload = {
        "schema_version": "valuation-input.v1",
        "provider": "licensed_fixture",
        "source_identifier": "vendor-valuation:2026-01-31",
        "benchmark": "US_EQUITY_TEST",
        "currency": "USD",
        "methodology_version": "vendor-method.v1",
        "observations": observations,
    }
    path = tmp_path / "valuation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = JSONValuationProvider(path).fetch(as_of=AS_OF)

    assert all(item.available_at <= AS_OF for item in dataset.observations)
    assert dataset.source_identifier == "vendor-valuation:2026-01-31"
    assert dataset.source_fingerprint == hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
