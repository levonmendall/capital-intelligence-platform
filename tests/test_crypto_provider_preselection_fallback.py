from __future__ import annotations

import json
from datetime import datetime, timezone

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
)
from operations.provider_preselection_publication_runtime import (
    ensure_provider_preselection_publication,
)


AS_OF = datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc)


class _Response:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


def _record(
    *,
    asset_class: CandidateAssetClass,
    symbol: str,
    provider_symbol: str,
    exchange: str,
    code: str,
) -> DiscoveryCatalogRecord:
    is_crypto = asset_class is CandidateAssetClass.CRYPTO
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=provider_symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure="crypto" if is_crypto else "international_equity",
        venue=exchange,
        country_code="US" if is_crypto else "GB",
        currency="USD" if is_crypto else "GBP",
        settlement_currency="USD" if is_crypto else "GBP",
        instrument_type="cryptocurrency" if is_crypto else "common_stock",
        provider_kind="yahoo",
        source_identifier=(
            f"eodhd:symbol_directory:{exchange}:"
            f"2026-08-12T15:00:00+00:00:{code}"
        ),
        quote_spread_bps=8.0,
    )


def _features(record: DiscoveryCatalogRecord) -> DiscoveryMarketFeatures:
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
        evidence_identifiers=(
            f"provider-factor:yahoo:{record.symbol}:certified-history",
        ),
    )


def test_grouped_crypto_bulk_miss_uses_history_without_falling_back_equities(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    policy = ComprehensiveMarketDiscoveryPolicy(
        provider_preselection_path=str(tmp_path / "provider-preselection.json")
    )
    equity = _record(
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        symbol="ABC_LSE",
        provider_symbol="ABC.L",
        exchange="LSE",
        code="ABC",
    )
    unresolved_equity = _record(
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        symbol="MISS_LSE",
        provider_symbol="MISS.L",
        exchange="LSE",
        code="MISS",
    )
    crypto = _record(
        asset_class=CandidateAssetClass.CRYPTO,
        symbol="BTCUSD",
        provider_symbol="BTC-USD",
        exchange="CC",
        code="BTCUSD",
    )
    received: list[tuple[str, ...]] = []

    def http_get(url: str, **_kwargs):
        exchange = url.rsplit("/", 1)[-1]
        if exchange == "LSE":
            return _Response([{"code": "ABC", "close": 100.0, "change_p": 1.0}])
        return _Response([{"code": "ETHUSD", "close": 100.0, "change_p": 1.0}])

    def market_probe(records, _as_of, _policy):
        received.append(tuple(record.symbol for record in records))
        return {record.symbol: _features(record) for record in records}

    result = ensure_provider_preselection_publication(
        {
            CandidateAssetClass.INTERNATIONAL_EQUITY: [equity, unresolved_equity],
            CandidateAssetClass.CRYPTO: [crypto],
        },
        as_of=AS_OF,
        policy=policy,
        http_get=http_get,
        market_probe=market_probe,
    )

    assert received == [("BTCUSD",)]
    assert result.signal_count == 2
    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert set(payload["signals"]) == {"ABC_LSE", "BTCUSD"}
    assert "MISS_LSE" not in payload["signals"]
    crypto_evidence = payload["signals"]["BTCUSD"]["factors"]["momentum"][
        "evidence_identifiers"
    ]
    assert any(item.startswith("provider-factor:") for item in crypto_evidence)
    assert any(
        item.startswith("provider-factor:yahoo:BTCUSD:")
        for item in payload["source_identifiers"]
    )


def test_grouped_crypto_bulk_signal_remains_preferred(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    crypto = _record(
        asset_class=CandidateAssetClass.CRYPTO,
        symbol="BTCUSD",
        provider_symbol="BTC-USD",
        exchange="CC",
        code="BTCUSD",
    )

    def unexpected_probe(*_args, **_kwargs):
        raise AssertionError("successful crypto bulk evidence must remain preferred")

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.CRYPTO: [crypto]},
        as_of=AS_OF,
        policy=ComprehensiveMarketDiscoveryPolicy(
            provider_preselection_path=str(tmp_path / "provider-preselection.json")
        ),
        http_get=lambda *_args, **_kwargs: _Response(
            [{"code": "BTCUSD", "close": 100.0, "change_p": 1.0}]
        ),
        market_probe=unexpected_probe,
    )

    assert result.signal_count == 1
    payload = json.loads(result.path.read_text(encoding="utf-8"))
    evidence = payload["signals"]["BTCUSD"]["factors"]["momentum"][
        "evidence_identifiers"
    ]
    assert any(item.startswith("eodhd-bulk-eod:CC:") for item in evidence)


def test_crypto_only_bulk_miss_can_build_from_provider_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN", "test-token")
    crypto = _record(
        asset_class=CandidateAssetClass.CRYPTO,
        symbol="BTCUSD",
        provider_symbol="BTC-USD",
        exchange="CC",
        code="BTCUSD",
    )
    received: list[tuple[str, ...]] = []

    def market_probe(records, _as_of, _policy):
        received.append(tuple(record.symbol for record in records))
        return {record.symbol: _features(record) for record in records}

    result = ensure_provider_preselection_publication(
        {CandidateAssetClass.CRYPTO: [crypto]},
        as_of=AS_OF,
        policy=ComprehensiveMarketDiscoveryPolicy(
            provider_preselection_path=str(tmp_path / "provider-preselection.json")
        ),
        http_get=lambda *_args, **_kwargs: _Response(
            [{"code": "ETHUSD", "close": 100.0, "change_p": 1.0}]
        ),
        market_probe=market_probe,
    )

    assert received == [("BTCUSD",)]
    assert result.signal_count == 1
    payload = json.loads(result.path.read_text(encoding="utf-8"))
    assert payload["paper_only"] is True
    assert payload["real_money_authorized"] is False
    evidence = payload["signals"]["BTCUSD"]["factors"]["momentum"][
        "evidence_identifiers"
    ]
    assert any(item.startswith("provider-factor:") for item in evidence)
