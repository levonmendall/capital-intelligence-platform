"""Contract tests for the Technical and Momentum analytical engine."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from math import exp, sin

from data import (
    BarInterval,
    DataQualityState,
    MarketDataProvenance,
    PriceBar,
)
from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.technical_momentum import (
    JSONTechnicalMomentumProvider,
    TechnicalMomentumComponent,
    TechnicalMomentumDataset,
    TechnicalMomentumEngine,
    TechnicalMomentumLoadState,
    UnavailableTechnicalMomentumProvider,
    build_configured_technical_momentum_engine,
)


AS_OF = datetime(2026, 1, 31, 21, tzinfo=timezone.utc)


def _bars(
    mode: str = "broad",
    *,
    count: int = 320,
    stale: bool = False,
    quality_state: DataQualityState = DataQualityState.FIXTURE,
) -> tuple[PriceBar, ...]:
    latest = AS_OF - timedelta(days=10 if stale else 0)
    first = latest - timedelta(days=count - 1)
    closes: list[float] = []
    for offset in range(count):
        if mode == "broad":
            close = 100.0 * exp(0.0013 * offset + 0.004 * sin(offset / 8))
        elif mode == "stress":
            close = 170.0 * exp(-0.0018 * offset + 0.010 * sin(offset / 5))
        elif mode == "rebound":
            if offset < count - 45:
                close = 160.0 * exp(-0.0019 * offset)
            else:
                trough = 160.0 * exp(-0.0019 * (count - 45))
                close = trough * exp(0.0045 * (offset - (count - 45)))
        elif mode == "mixed":
            close = 100.0 * exp(0.0001 * offset + 0.025 * sin(offset / 11))
        elif mode == "volatile":
            close = 100.0 * exp(
                0.0008 * offset
                + (0.006 if offset < count - 25 else 0.055) * sin(offset * 1.7)
            )
        else:
            close = 100.0
        closes.append(close)
    records: list[PriceBar] = []
    for offset, close in enumerate(closes):
        end_at = first + timedelta(days=offset)
        records.append(
            PriceBar(
                instrument_id="benchmark:US_EQUITY_TEST",
                currency="USD",
                interval=BarInterval.DAY,
                start_at=end_at - timedelta(hours=6),
                end_at=end_at,
                open=close,
                high=close * 1.01,
                low=close * 0.99,
                close=close,
                volume=1_000_000,
                provenance=MarketDataProvenance(
                    provider="FIXTURE",
                    venue="XNYS",
                    observed_at=end_at,
                    retrieved_at=end_at,
                    quality_state=quality_state,
                    provider_record_id=f"bar:{offset}",
                ),
            )
        )
    return tuple(records)


class FakeTechnicalMomentumProvider:
    name = "FIXTURE"

    def __init__(
        self,
        *,
        mode: str = "broad",
        count: int = 320,
        stale: bool = False,
        quality_state: DataQualityState = DataQualityState.FIXTURE,
    ) -> None:
        self.mode = mode
        self.count = count
        self.stale = stale
        self.quality_state = quality_state
        self.calls: list[datetime] = []

    def fetch(self, *, as_of: datetime) -> TechnicalMomentumDataset:
        self.calls.append(as_of)
        bars = _bars(
            self.mode,
            count=self.count,
            stale=self.stale,
            quality_state=self.quality_state,
        )
        return TechnicalMomentumDataset(
            provider=self.name,
            source_identifier="fixture:technical-momentum",
            source_fingerprint=hashlib.sha256(
                f"{self.mode}:{self.count}:{self.stale}".encode()
            ).hexdigest(),
            benchmark="US_EQUITY_TEST",
            instrument_id="benchmark:US_EQUITY_TEST",
            venue="XNYS",
            currency="USD",
            methodology_version="fixture-method.v1",
            retrieved_at=max(bar.provenance.retrieved_at for bar in bars),
            bars=bars,
        )


def test_broad_multi_horizon_support_reports_expanding() -> None:
    run = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 7
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 65
    assert run.result.confidence >= 70
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 7
    assert all(item.released_at <= AS_OF for item in run.result.evidence)


def test_confirmed_breakdown_reports_stressed() -> None:
    result = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(mode="stress"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.STRESSED
    assert result.score <= 25
    assert any("drawdown" in risk.lower() for risk in result.risks)


def test_short_term_rebound_cannot_be_called_healthy_trend() -> None:
    result = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(mode="rebound"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is not EngineDirection.EXPANDING
    assert any("disagree" in risk.lower() for risk in result.risks)


def test_mixed_evidence_remains_neutral() -> None:
    result = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(mode="mixed"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.NEUTRAL


def test_partial_history_reduces_coverage_without_imputation() -> None:
    run = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(count=150),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count >= 4
    assert run.unavailable_count >= 2
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any(
        load.state is TechnicalMomentumLoadState.UNAVAILABLE
        for load in run.loads
    )
    assert any("incomplete" in risk.lower() for risk in run.result.risks)


def test_elevated_realized_volatility_is_disclosed() -> None:
    run = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(mode="volatile"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)
    volatility = next(
        load
        for load in run.loads
        if load.component is TechnicalMomentumComponent.VOLATILITY_PRESSURE
    )

    assert volatility.signal is not None
    assert volatility.signal < 0
    assert any("volatility" in risk.lower() for risk in run.result.risks)


def test_stale_price_history_is_disclosed() -> None:
    result = TechnicalMomentumEngine(
        FakeTechnicalMomentumProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in risk.lower() for risk in result.risks)


def test_unconfigured_provider_returns_explicit_unavailable_result() -> None:
    result = TechnicalMomentumEngine(
        UnavailableTechnicalMomentumProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert result.data_status is EngineDataStatus.UNAVAILABLE
    assert result.coverage == 0
    assert result.confidence == 0
    assert result.evidence == ()


def test_configured_builder_is_unavailable_without_source(monkeypatch) -> None:
    monkeypatch.delenv(
        "CAPITAL_INTELLIGENCE_TECHNICAL_MOMENTUM_FILE",
        raising=False,
    )

    result = build_configured_technical_momentum_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert "not configured" in result.explanation


def test_json_provider_excludes_future_bars_and_fingerprints_source(
    tmp_path,
) -> None:
    records = _bars(count=25)
    payload = {
        "schema_version": "technical-momentum-input.v1",
        "provider": "licensed_fixture",
        "source_identifier": "vendor:technical:2026-01-31",
        "benchmark": "US_EQUITY_TEST",
        "instrument_id": "benchmark:US_EQUITY_TEST",
        "venue": "XNYS",
        "currency": "USD",
        "methodology_version": "vendor-method.v1",
        "retrieved_at": AS_OF.isoformat(),
        "bars": [
            {
                "start_at": bar.start_at.isoformat(),
                "end_at": bar.end_at.isoformat(),
                "observed_at": bar.provenance.observed_at.isoformat(),
                "retrieved_at": bar.provenance.retrieved_at.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "quality_state": "fixture",
            }
            for bar in records
        ]
        + [
            {
                "start_at": (AS_OF + timedelta(hours=1)).isoformat(),
                "end_at": (AS_OF + timedelta(hours=7)).isoformat(),
                "observed_at": (AS_OF + timedelta(hours=7)).isoformat(),
                "retrieved_at": (AS_OF + timedelta(hours=7)).isoformat(),
                "open": 200,
                "high": 202,
                "low": 198,
                "close": 201,
                "volume": 1_000_000,
                "quality_state": "fixture",
            }
        ],
    }
    path = tmp_path / "technical.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = JSONTechnicalMomentumProvider(path).fetch(as_of=AS_OF)

    assert len(dataset.bars) == 25
    assert all(bar.end_at <= AS_OF for bar in dataset.bars)
    assert dataset.source_identifier == "vendor:technical:2026-01-31"
    assert dataset.source_fingerprint == hashlib.sha256(path.read_bytes()).hexdigest()
