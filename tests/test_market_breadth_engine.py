"""Contract tests for the Market Breadth analytical engine."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from data import (
    BarInterval,
    DataQualityState,
    MarketDataBatch,
    MarketDataError,
    MarketDataProvenance,
    MarketDataQuery,
    MarketDataType,
    PriceBar,
)
from intelligence.analytical_engine import EngineDataStatus, EngineDirection
from intelligence.market_breadth import (
    BreadthUniverseMember,
    BreadthUniverseSnapshot,
    JSONMarketBreadthProvider,
    MarketBreadthEngine,
    MarketBreadthLoadState,
    UnavailableMarketBreadthProvider,
    build_configured_market_breadth_engine,
)


AS_OF = datetime(2026, 1, 31, 21, tzinfo=timezone.utc)


def _bars(
    instrument_id: str,
    venue: str,
    mode: str,
    index: int,
    *,
    stale: bool = False,
) -> tuple[PriceBar, ...]:
    records: list[PriceBar] = []
    first_end = AS_OF - timedelta(days=259)
    for offset in range(260):
        end_at = first_end + timedelta(days=offset)
        base = 100.0 + index
        if mode == "broad":
            close = base * (1.0 + 0.0015 * offset)
        elif mode == "narrow":
            if index < 2:
                close = base * (1.0 + 0.0030 * offset)
            elif index < 10:
                close = base * (1.0 + 0.0003 * offset)
            else:
                close = base * (1.0 - 0.0003 * offset)
        elif mode == "stress":
            close = base * (1.0 - 0.0015 * offset)
        else:
            close = base
        quality = (
            DataQualityState.STALE
            if stale
            else DataQualityState.FIXTURE
        )
        records.append(
            PriceBar(
                instrument_id=instrument_id,
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
                    venue=venue,
                    observed_at=end_at,
                    retrieved_at=end_at,
                    quality_state=quality,
                ),
            )
        )
    return tuple(records)


class FakeMarketBreadthProvider:
    name = "FIXTURE"

    def __init__(
        self,
        *,
        mode: str = "broad",
        missing: int = 0,
        stale: bool = False,
    ) -> None:
        self.mode = mode
        self.missing = missing
        self.stale = stale
        self.queries: list[MarketDataQuery] = []

    def fetch_universe(self, *, as_of: datetime) -> BreadthUniverseSnapshot:
        members = tuple(
            BreadthUniverseMember(
                instrument_id=f"equity:{index}",
                venue="XNYS",
                weight=(0.35 if index < 2 else 0.30 / 18),
                sector="Test sector",
            )
            for index in range(20)
        )
        return BreadthUniverseSnapshot(
            identifier="US_EQUITY_20",
            source_identifier="fixture:us-equity-20",
            source_fingerprint=hashlib.sha256(b"us-equity-20").hexdigest(),
            provider=self.name,
            as_of=as_of,
            observed_at=as_of - timedelta(minutes=5),
            retrieved_at=as_of,
            quality_state=DataQualityState.FIXTURE,
            members=members,
        )

    def fetch(self, query: MarketDataQuery) -> MarketDataBatch:
        self.queries.append(query)
        index = int(query.instrument_id.split(":")[-1])
        if index >= 20 - self.missing:
            raise MarketDataError(f"{query.instrument_id} unavailable")
        records = _bars(
            query.instrument_id,
            query.venue or "XNYS",
            self.mode,
            index,
            stale=self.stale,
        )
        return MarketDataBatch(query=query, records=records)


def test_complete_fixture_reports_broadening_market_participation() -> None:
    run = MarketBreadthEngine(
        FakeMarketBreadthProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 20
    assert run.result.direction is EngineDirection.EXPANDING
    assert run.result.score > 60
    assert run.result.confidence >= 80
    assert run.result.coverage == 1.0
    assert run.result.data_status is EngineDataStatus.CURRENT
    assert len(run.result.evidence) == 6
    assert all(item.released_at <= AS_OF for item in run.result.evidence)


def test_narrow_leadership_cannot_be_called_healthy_breadth() -> None:
    result = MarketBreadthEngine(
        FakeMarketBreadthProvider(mode="narrow"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is not EngineDirection.EXPANDING
    assert any("concentration" in risk.lower() for risk in result.risks)
    leadership = next(
        item
        for item in result.evidence
        if item.component == "equal_weight_leadership"
    )
    assert leadership.signal_score < 0


def test_broad_breakdown_reports_stressed_breadth() -> None:
    result = MarketBreadthEngine(
        FakeMarketBreadthProvider(mode="stress"),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.STRESSED
    assert result.score <= 25


def test_partial_constituent_failure_reduces_coverage_without_imputation() -> None:
    run = MarketBreadthEngine(
        FakeMarketBreadthProvider(missing=4),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF)

    assert run.loaded_count == 16
    assert run.unavailable_count == 4
    assert run.result.data_status is EngineDataStatus.INCOMPLETE
    assert 0 < run.result.coverage < 1
    assert any(
        load.state is MarketBreadthLoadState.UNAVAILABLE
        for load in run.loads
    )
    assert any("unavailable" in risk for risk in run.result.risks)


def test_stale_constituent_evidence_is_disclosed() -> None:
    result = MarketBreadthEngine(
        FakeMarketBreadthProvider(stale=True),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.data_status is EngineDataStatus.STALE
    assert any("stale" in risk.lower() for risk in result.risks)


def test_unconfigured_provider_returns_explicit_unavailable_result() -> None:
    result = MarketBreadthEngine(
        UnavailableMarketBreadthProvider(),
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert result.data_status is EngineDataStatus.UNAVAILABLE
    assert result.coverage == 0
    assert result.confidence == 0


def test_configured_builder_is_unavailable_without_a_source(monkeypatch) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_MARKET_BREADTH_FILE", raising=False)

    result = build_configured_market_breadth_engine(
        clock=lambda: AS_OF,
    ).run(as_of=AS_OF).result

    assert result.direction is EngineDirection.UNAVAILABLE
    assert "not configured" in result.explanation


def test_json_provider_filters_future_members_and_fingerprints_source(
    tmp_path,
) -> None:
    payload = {
        "schema_version": "market-breadth-input.v1",
        "provider": "licensed_fixture",
        "source_identifier": "vendor-snapshot:2026-01-31",
        "universe": {
            "identifier": "POINT_IN_TIME_TEST",
            "as_of": AS_OF.isoformat(),
            "observed_at": (AS_OF - timedelta(minutes=5)).isoformat(),
            "retrieved_at": AS_OF.isoformat(),
            "quality_state": "fixture",
            "members": [
                {
                    "instrument_id": f"equity:{index}",
                    "venue": "XNYS",
                    "weight": 0.2,
                }
                for index in range(5)
            ]
            + [
                {
                    "instrument_id": "equity:future",
                    "venue": "XNYS",
                    "weight": 0.2,
                    "effective_from": (AS_OF + timedelta(days=1)).isoformat(),
                }
            ],
        },
        "bars": [],
    }
    path = tmp_path / "breadth.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    snapshot = JSONMarketBreadthProvider(path).fetch_universe(as_of=AS_OF)

    assert len(snapshot.members) == 5
    assert all(member.instrument_id != "equity:future" for member in snapshot.members)
    assert snapshot.source_identifier == "vendor-snapshot:2026-01-31"
    assert snapshot.source_fingerprint == hashlib.sha256(path.read_bytes()).hexdigest()
