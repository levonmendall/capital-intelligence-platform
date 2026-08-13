from __future__ import annotations

from datetime import datetime, timedelta, timezone

from cio import CandidateAssetClass
from operations import provider_preselection_market_probe as probe
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
)


AS_OF = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)


def _future(symbol: str = "ESU26") -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=f"{symbol}.CME",
        name=symbol,
        asset_class=CandidateAssetClass.FUTURE,
        economic_exposure="us_equity",
        venue="CME",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="future",
        provider_kind="unbound",
        source_identifier=f"configured-futures-root:ES:{symbol}",
        contract_multiplier=50.0,
        quote_spread_bps=1.0,
        expiration_at=AS_OF + timedelta(days=90),
    )


def _equity() -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol="ABC_LSE",
        provider_symbol="ABC.L",
        name="ABC",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        economic_exposure="international_equity",
        venue="LSE",
        country_code="GB",
        currency="GBP",
        settlement_currency="GBP",
        instrument_type="common_stock",
        provider_kind="eodhd",
        source_identifier="eodhd:symbol_directory:LSE:2026-08-12T21:00:00+00:00:ABC",
    )


def _features(record: DiscoveryCatalogRecord, *, provider: str) -> DiscoveryMarketFeatures:
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
        evidence_identifiers=(f"{provider}:history:{record.symbol}:certified",),
    )


def test_preselection_routes_only_unresolved_futures_to_redundant_authority(
    monkeypatch,
) -> None:
    future = _future()
    equity = _equity()
    legacy_calls: list[tuple[str, ...]] = []
    futures_calls: list[tuple[str, ...]] = []

    def legacy_market_probe(records, *_args, **_kwargs):
        legacy_calls.append(tuple(record.symbol for record in records))
        return {equity.symbol: _features(equity, provider="eodhd")}

    def futures_features(records, **_kwargs):
        futures_calls.append(tuple(record.symbol for record in records))
        return {future.symbol: _features(future, provider="massive")}

    monkeypatch.setattr(probe._legacy, "default_market_probe", legacy_market_probe)
    monkeypatch.setattr(probe, "_redundant_futures_features", futures_features)

    result = probe.default_provider_preselection_market_probe(
        (equity, future),
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        alpaca_client=object(),
    )

    assert legacy_calls == [(equity.symbol, future.symbol)]
    assert futures_calls == [(future.symbol,)]
    assert tuple(result) == (equity.symbol, future.symbol)
    assert any("massive:" in item for item in result[future.symbol].evidence_identifiers)


def test_resolved_future_does_not_trigger_redundant_provider(monkeypatch) -> None:
    future = _future()

    monkeypatch.setattr(
        probe._legacy,
        "default_market_probe",
        lambda *_args, **_kwargs: {
            future.symbol: _features(future, provider="certified-primary")
        },
    )

    def unexpected_fallback(*_args, **_kwargs):
        raise AssertionError("resolved futures must not trigger redundant provider I/O")

    monkeypatch.setattr(probe, "_redundant_futures_features", unexpected_fallback)

    result = probe.default_provider_preselection_market_probe(
        (future,),
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        alpaca_client=object(),
    )

    assert tuple(result) == (future.symbol,)


def test_missing_massive_future_evidence_remains_fail_closed(monkeypatch) -> None:
    future = _future()
    monkeypatch.setattr(
        probe._legacy,
        "default_market_probe",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        probe,
        "_redundant_futures_features",
        lambda *_args, **_kwargs: {},
    )

    result = probe.default_provider_preselection_market_probe(
        (future,),
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        alpaca_client=object(),
    )

    assert result == {}


def test_futures_router_uses_bounded_massive_cap_without_deep_stage(monkeypatch) -> None:
    future = _future()
    sentinels = {
        "eodhd": object(),
        "tradier": object(),
        "massive": object(),
        "twelve": object(),
        "coinbase": object(),
        "kraken": object(),
    }
    monkeypatch.setattr(probe._legacy, "build_eodhd_provider", lambda: sentinels["eodhd"])
    monkeypatch.setattr(
        probe._redundant._core,
        "TradierMarketDataProvider",
        lambda: sentinels["tradier"],
    )
    monkeypatch.setattr(
        probe._redundant._core,
        "MassiveMultiAssetProvider",
        lambda: sentinels["massive"],
    )
    monkeypatch.setattr(
        probe._redundant._core,
        "TwelveDataHistoryProvider",
        lambda: sentinels["twelve"],
    )
    monkeypatch.setattr(
        probe._redundant._core,
        "CoinbaseHistoryProvider",
        lambda: sentinels["coinbase"],
    )
    monkeypatch.setattr(
        probe._redundant._core,
        "KrakenHistoryProvider",
        lambda: sentinels["kraken"],
    )
    captured: dict[str, object] = {}

    def fetch_missing(records, **kwargs):
        captured["records"] = tuple(record.symbol for record in records)
        captured.update(kwargs)
        # The callback intentionally suppresses the deep-evidence stage because this
        # I/O occurs while the provider-factor publication is still being built.
        kwargs["progress_callback"](
            "deep_market_evidence:future",
            metrics={"processed_records": 1},
        )
        return {future.symbol: _features(future, provider="massive")}

    monkeypatch.setattr(probe._redundant, "_fetch_missing_concurrently", fetch_missing)

    result = probe._redundant_futures_features(
        (future,),
        as_of=AS_OF,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        http_get=lambda *_args, **_kwargs: None,
        maximum_workers=99,
    )

    assert tuple(result) == (future.symbol,)
    assert captured["records"] == (future.symbol,)
    assert captured["massive"] is sentinels["massive"]
    assert captured["maximum_workers"] == 4
    assert captured["decision_eligible_records"] == 1
    assert captured["alpaca_crypto_rows"] == {}


def test_redundant_candidate_set_delegates_unbound_future_to_massive() -> None:
    future = _future()

    class _Configured:
        configured = True

    candidates = probe._redundant._core._candidate_set(
        future,
        as_of=AS_OF,
        policy=ComprehensiveMarketDiscoveryPolicy(),
        http_get=lambda *_args, **_kwargs: None,
        eodhd_provider=_Configured(),
        tradier=_Configured(),
        massive=_Configured(),
        twelve=_Configured(),
        coinbase=_Configured(),
        kraken=_Configured(),
        alpaca_crypto_rows={},
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.provider == "massive"
    assert candidate.capability == "futures_history"
    assert candidate.dataset == "futures-aggs"
    assert candidate.configured is True
