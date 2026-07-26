"""Contract tests for the Risk analytical engine."""

from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, datetime, timezone

from data import DataQualityState
from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.risk import (
    JSONRiskProvider,
    RiskDataset,
    RiskEngine,
    RiskLoadState,
    RiskMetric,
    RiskObservation,
    UnavailableRiskProvider,
    build_configured_risk_engine,
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
    mode: str = "calm",
    *,
    missing: set[RiskMetric] | None = None,
    stale: bool = False,
    include_future: bool = False,
) -> RiskDataset:
    missing = missing or set()
    observations: list[RiskObservation] = []
    for index, metric in enumerate(RiskMetric):
        if metric in missing:
            continue
        base = 0.10 + 0.02 * index
        history_year = 2023 if stale else 2024
        history_month = 12 if stale else 6
        for offset in range(18):
            observation_date = _month(history_year, history_month, offset)
            available_at = datetime(
                observation_date.year,
                observation_date.month,
                min(observation_date.day + 1, 28),
                12,
                tzinfo=timezone.utc,
            )
            observations.append(
                RiskObservation(
                    metric=metric,
                    value=base + 0.002 * offset,
                    observation_date=observation_date,
                    available_at=available_at,
                    retrieved_at=available_at,
                    quality_state=DataQualityState.FIXTURE,
                    source_identifier="fixture:risk",
                    scope="US_MULTI_ASSET_TEST",
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
        if mode == "calm":
            latest_value = base - 0.05
        elif mode == "stressed":
            latest_value = base + 0.20
        elif mode == "mixed":
            latest_value = base + (0.20 if index % 2 else -0.05)
        elif mode == "single_shock":
            latest_value = base + (0.20 if index == 0 else 0.017)
        elif mode == "rising":
            latest_value = base + (0.20 if index < 4 else 0.017)
        else:
            raise ValueError(f"unsupported fixture mode: {mode}")
        observations.append(
            RiskObservation(
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
                source_identifier="fixture:risk",
                scope="US_MULTI_ASSET_TEST",
                methodology_version="fixture-method.v1",
            )
        )
        if include_future:
            future_date = date(2026, 2, 15)
            future_available = datetime(2026, 2, 16, 12, tzinfo=timezone.utc)
            observations.append(
                RiskObservation(
                    metric=metric,
                    value=9.0,
                    observation_date=future_date,
                    available_at=future_available,
                    retrieved_at=future_available,
                    quality_state=DataQualityState.FIXTURE,
                    source_identifier="fixture:risk",
                    scope="US_MULTI_ASSET_TEST",
                    methodology_version="fixture-method.v1",
                )
            )
    return RiskDataset(
        provider="FIXTURE",
        source_identifier="fixture:risk",
        source_fingerprint=hashlib.sha256(b"risk-fixture").hexdigest(),
        scope="US_MULTI_ASSET_TEST",
        methodology_version="fixture-method.v1",
        retrieved_at=max(item.retrieved_at for item in observations),
        observations=tuple(observations),
    )


class FakeRiskProvider:
    name = "FIXTURE"

    def __init__(
        self,
        mode: str = "calm",
        *,
        missing: set[RiskMetric] | None = None,
        stale: bool = False,
        include_future: bool = False,
    ) -> None:
        self.dataset = _dataset(
            mode,
            missing=missing,
            stale=stale,
            include_future=include_future,
        )

    def fetch(self, *, as_of: datetime) -> RiskDataset:
        del as_of
        return self.dataset


def test_broad_risk_easing_reports_expanding() -> None:
    run = RiskEngine(
        FakeRiskProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 7
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 70
    assert run.result.confidence >= 70
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 7
    assert all(item.released_at <= AS_OF for item in run.result.evidence)


def test_cross_channel_fragility_reports_stressed() -> None:
    result = RiskEngine(
        FakeRiskProvider(mode="stressed"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.STRESSED
    assert result.score <= 25
    assert any("loss amount" in risk.lower() for risk in result.risks)


def test_single_volatility_shock_cannot_force_stressed_result() -> None:
    result = RiskEngine(
        FakeRiskProvider(mode="single_shock"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is not EngineDirection.STRESSED


def test_rising_pressure_without_structural_confirmation_is_not_stressed() -> None:
    result = RiskEngine(
        FakeRiskProvider(mode="rising"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction in {EngineDirection.CONTRACTING, EngineDirection.NEUTRAL}


def test_mixed_evidence_remains_neutral_and_discloses_disagreement() -> None:
    result = RiskEngine(
        FakeRiskProvider(mode="mixed"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.NEUTRAL
    assert any("disagree" in risk.lower() for risk in result.risks)


def test_partial_component_failure_reduces_coverage_without_imputation() -> None:
    missing = {
        RiskMetric.MARKET_CONCENTRATION,
        RiskMetric.TAIL_LOSS_FREQUENCY,
    }
    run = RiskEngine(
        FakeRiskProvider(missing=missing),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 5
    assert run.unavailable_count == 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any(
        load.state is RiskLoadState.UNAVAILABLE for load in run.loads
    )
    assert any("coverage is incomplete" in risk.lower() for risk in run.result.risks)


def test_stale_risk_history_is_disclosed() -> None:
    result = RiskEngine(
        FakeRiskProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in risk.lower() for risk in result.risks)


def test_future_observations_do_not_change_point_in_time_result() -> None:
    current = RiskEngine(
        FakeRiskProvider(mode="calm"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result
    with_future = RiskEngine(
        FakeRiskProvider(mode="calm", include_future=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert with_future.direction is current.direction
    assert with_future.score == current.score
    assert all(item.released_at <= AS_OF for item in with_future.evidence)


def test_unconfigured_provider_returns_explicit_unavailable_result() -> None:
    result = RiskEngine(
        UnavailableRiskProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert result.data_status is EngineDataStatus.UNAVAILABLE
    assert result.coverage == 0
    assert result.confidence == 0
    assert result.evidence == ()


def test_configured_builder_is_unavailable_without_source(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_RISK_FILE", raising=False)

    result = build_configured_risk_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert "not configured" in result.explanation


def test_json_provider_excludes_future_observations_and_fingerprints_source(
    tmp_path,
) -> None:
    payload = {
        "schema_version": "risk-input.v1",
        "provider": "licensed_fixture",
        "source_identifier": "vendor:risk:2026-01-31",
        "scope": "US_MULTI_ASSET_TEST",
        "methodology_version": "vendor-method.v1",
        "retrieved_at": AS_OF.isoformat(),
        "observations": [
            {
                "metric": "realized_volatility",
                "value": 0.15,
                "observation_date": "2026-01-15",
                "available_at": "2026-01-16T12:00:00+00:00",
                "retrieved_at": "2026-01-16T12:00:00+00:00",
                "quality_state": "fixture",
            },
            {
                "metric": "realized_volatility",
                "value": 9.0,
                "observation_date": "2026-02-15",
                "available_at": "2026-02-16T12:00:00+00:00",
                "retrieved_at": "2026-02-16T12:00:00+00:00",
                "quality_state": "fixture",
            },
        ],
    }
    path = tmp_path / "risk.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = JSONRiskProvider(path).fetch(as_of=AS_OF)

    assert len(dataset.observations) == 1
    assert dataset.observations[0].value == 0.15
    assert dataset.source_identifier == "vendor:risk:2026-01-31"
    assert dataset.source_fingerprint == hashlib.sha256(path.read_bytes()).hexdigest()
