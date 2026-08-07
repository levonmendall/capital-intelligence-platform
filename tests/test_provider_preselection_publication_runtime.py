from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import pytest

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    CatalogScreeningSignal,
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    discover_comprehensive_markets,
)
from operations import provider_preselection_publication_runtime as publication_runtime
from operations.provider_preselection_publication_runtime import (
    ProviderPreselectionPublicationError,
    ensure_provider_preselection_publication,
)


AS_OF = datetime(2026, 8, 6, 15, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _record(
    *,
    asset_class: CandidateAssetClass = CandidateAssetClass.INTERNATIONAL_EQUITY,
    symbol: str = "ABC_LSE",
    provider_symbol: str = "ABC.L",
    source_identifier: str = (
        "eodhd:symbol_directory:LSE:2026-08-06T15:00:00+00:00:ABC"
    ),
) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=provider_symbol,
        name="ABC Holdings",
        asset_class=asset_class,
        economic_exposure="international_equity",
        venue="LSE",
        country_code="GB",
        currency="GBP",
        settlement_currency="GBP",
        instrument_type="common_stock",
        provider_kind="yahoo",
        source_identifier=source_identifier,
        quote_spread_bps=8.0,
    )


def test_builds_provider_factor_publication_from_bulk_exchange_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    path = tmp_path / "provider-preselection.json"
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )
    calls: list[tuple[str, object]] = []

    def http_get(url: str, **kwargs):
        calls.append((url, kwargs.get("params")))
        return _Response(
            [
                {
                    "code": "ABC",
                    "close": 100.0,
                    "ema_50d": 105.0,
                    "ema_200d": 90.0,
                    "earnings_share": 6.0,
                    "dividend_yield": 2.5,
                    "avgvol_200d": 1_500_000,
                }
            ]
        )

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.INTERNATIONAL_EQUITY: [_record()]},
        as_of=AS_OF,
        policy=policy,
        http_get=http_get,
    )

    assert result.reused is False
    assert result.catalog_count == 1
    assert result.signal_count == 1
    assert result.coverage_ratio == 1.0
    assert calls and "eod-bulk-last-day/LSE" in calls[0][0]

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "capital-intelligence-provider-preselection.v1"
    assert payload["catalog_count"] == 1
    assert payload["signal_count"] == 1
    signal = payload["signals"]["ABC_LSE"]
    assert signal["factors"]["value"]["applicability"] == "scored"
    assert signal["factors"]["momentum"]["applicability"] == "scored"
    assert signal["factors"]["carry"]["applicability"] == "scored"
    assert signal["factors"]["improving_conditions"]["applicability"] == "scored"
    assert signal["indicative_price"] == 100.0
    assert any(
        item.startswith("eodhd-bulk-eod:LSE:")
        for item in payload["source_identifiers"]
    )


def test_reuses_matching_fresh_publication_without_provider_call(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    path = tmp_path / "provider-preselection.json"
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )
    record = _record()

    ensure_provider_preselection_publication(
        {CandidateAssetClass.INTERNATIONAL_EQUITY: [record]},
        as_of=AS_OF,
        policy=policy,
        http_get=lambda *_args, **_kwargs: _Response(
            [
                {
                    "code": "ABC",
                    "close": 100.0,
                    "ema_50d": 105.0,
                    "ema_200d": 90.0,
                }
            ]
        ),
    )

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("fresh matching publication should be reused")

    reused = ensure_provider_preselection_publication(
        {CandidateAssetClass.INTERNATIONAL_EQUITY: [record]},
        as_of=AS_OF,
        policy=policy,
        http_get=unexpected_call,
    )

    assert reused.reused is True
    assert reused.signal_count == 1


def test_publication_fails_closed_when_no_substantive_signal_is_available(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    path = tmp_path / "provider-preselection.json"
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )
    record = _record(
        asset_class=CandidateAssetClass.CRYPTO,
        symbol="BTCUSD",
        provider_symbol="BTC-USD",
        source_identifier="certified-catalog:crypto:BTCUSD",
    )

    with pytest.raises(
        ProviderPreselectionPublicationError,
        match="no substantive provider factor signal",
    ):
        ensure_provider_preselection_publication(
            {CandidateAssetClass.CRYPTO: [record]},
            as_of=AS_OF,
            policy=policy,
            market_probe=lambda _records, _as_of, _policy: {},
        )

    assert not path.exists()


def test_systemic_lane_publication_failure_cannot_certify_all_excluded_lane() -> None:
    record = _record()

    def invalid_preselection(records, _as_of, _policy):
        return {
            item.symbol: CatalogScreeningSignal(
                symbol=item.symbol,
                observed_at=AS_OF,
                eligible=False,
                liquidity_score=0.9,
                quality_score=0.8,
                evidence_identifiers=(item.source_identifier,),
                exclusion_reasons=(
                    "provider_enriched_preselection_publication_invalid:"
                    "ProviderEnrichedPreselectionError",
                ),
            )
            for item in records
        }

    with pytest.raises(
        ComprehensiveMarketDiscoveryError,
        match="international_equity provider factor authority is unavailable",
    ):
        discover_comprehensive_markets(
            as_of=AS_OF,
            catalog_probe=lambda _as_of: {
                CandidateAssetClass.INTERNATIONAL_EQUITY: [record],
                CandidateAssetClass.FX: [],
                CandidateAssetClass.CRYPTO: [],
                CandidateAssetClass.FUTURE: [],
                CandidateAssetClass.OPTION: [],
            },
            preselection_probe=invalid_preselection,
            market_probe=lambda _records, _as_of, _policy: {},
        )


def test_bulk_exchange_snapshots_are_bounded_concurrent_and_publish_in_order(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    path = tmp_path / "provider-preselection.json"
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )
    records = (
        _record(
            symbol="ZZZ_LSE",
            provider_symbol="ZZZ.L",
            source_identifier=(
                "eodhd:symbol_directory:LSE:2026-08-06T15:00:00+00:00:ZZZ"
            ),
        ),
        _record(
            symbol="AAA_XETRA",
            provider_symbol="AAA.DE",
            source_identifier=(
                "eodhd:symbol_directory:XETRA:2026-08-06T15:00:00+00:00:AAA"
            ),
        ),
    )
    lock = threading.Lock()
    released = threading.Event()
    active = 0
    peak = 0
    stages: list[str] = []

    def http_get(url: str, **_kwargs):
        nonlocal active, peak
        exchange = url.rsplit("/", 1)[-1]
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                released.set()
        try:
            assert released.wait(timeout=2.0), "exchange snapshots ran serially"
            code = "ZZZ" if exchange == "LSE" else "AAA"
            return _Response(
                [{"code": code, "close": 100.0, "change_p": 1.0}]
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(
        publication_runtime,
        "record_manual_cio_diagnostic_progress",
        lambda stage, **_kwargs: stages.append(stage),
    )

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.INTERNATIONAL_EQUITY: records},
        as_of=AS_OF,
        policy=policy,
        http_get=http_get,
    )

    assert result.signal_count == 2
    assert peak == 2
    assert stages == [
        "provider_preselection_bulk_snapshots",
        "provider_preselection_bulk_snapshots_complete",
    ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    bulk_sources = [
        item
        for item in payload["source_identifiers"]
        if item.startswith("eodhd-bulk-eod:")
    ]
    assert bulk_sources[0].startswith("eodhd-bulk-eod:LSE:")
    assert bulk_sources[1].startswith("eodhd-bulk-eod:XETRA:")


def test_default_fallback_probe_is_bounded_concurrent_and_restores_record_order(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    path = tmp_path / "provider-preselection.json"
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(path)
    )
    records = tuple(
        _record(
            asset_class=CandidateAssetClass.FUTURE,
            symbol=f"FUTURE_{index}",
            provider_symbol=f"FUTURE{index}=F",
            source_identifier=f"certified-catalog:future:FUTURE_{index}",
        )
        for index in range(4)
    )
    lock = threading.Lock()
    released = threading.Event()
    active = 0
    peak = 0
    stages: list[str] = []
    requested_worker_counts: list[int] = []

    def feature(record: DiscoveryCatalogRecord) -> DiscoveryMarketFeatures:
        return DiscoveryMarketFeatures(
            price=100.0,
            observed_at=AS_OF,
            one_month_return=0.01,
            three_month_return=0.02,
            six_month_return=0.03,
            twelve_month_return=0.04,
            annualized_volatility=0.2,
            maximum_drawdown=-0.1,
            average_daily_dollar_volume=10_000_000.0,
            history_bars=504,
            evidence_identifiers=(record.source_identifier,),
        )

    def default_probe(batch, _as_of, _policy, *, maximum_workers):
        nonlocal active, peak
        requested_worker_counts.append(maximum_workers)
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 4:
                released.set()
        try:
            assert released.wait(timeout=2.0), "fallback probes ran serially"
            return {record.symbol: feature(record) for record in batch}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(publication_runtime, "default_market_probe", default_probe)
    monkeypatch.setattr(
        publication_runtime,
        "record_manual_cio_diagnostic_progress",
        lambda stage, **_kwargs: stages.append(stage),
    )

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.FUTURE: records},
        as_of=AS_OF,
        policy=policy,
    )

    assert result.signal_count == 4
    assert peak == 4
    assert requested_worker_counts == [1, 1, 1, 1]
    assert stages == [
        "provider_preselection_fallback_probe",
        "provider_preselection_fallback_probe_complete",
    ]
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_sources = [record.source_identifier for record in records]
    assert payload["source_identifiers"][1:] == expected_sources


def test_injected_fallback_probe_remains_one_complete_catalog_call(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    records = tuple(
        _record(
            asset_class=CandidateAssetClass.CRYPTO,
            symbol=f"CRYPTO_{index}",
            provider_symbol=f"CRYPTO-{index}",
            source_identifier=f"certified-catalog:crypto:CRYPTO_{index}",
        )
        for index in range(4)
    )
    received: list[tuple[str, ...]] = []

    def injected_probe(probe_records, _as_of, _policy):
        received.append(tuple(record.symbol for record in probe_records))
        return {
            record.symbol: DiscoveryMarketFeatures(
                price=100.0,
                observed_at=AS_OF,
                one_month_return=0.01,
                three_month_return=0.02,
                six_month_return=0.03,
                twelve_month_return=0.04,
                annualized_volatility=0.2,
                maximum_drawdown=-0.1,
                average_daily_dollar_volume=10_000_000.0,
                history_bars=504,
                evidence_identifiers=(record.source_identifier,),
            )
            for record in probe_records
        }

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.CRYPTO: records},
        as_of=AS_OF,
        policy=ComprehensiveMarketDiscoveryPolicy(
            provider_preselection_path=str(tmp_path / "provider-preselection.json")
        ),
        market_probe=injected_probe,
    )

    assert result.signal_count == 4
    assert received == [tuple(record.symbol for record in records)]
