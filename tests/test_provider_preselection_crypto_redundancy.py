from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from operations import provider_preselection_market_probe as probe
from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord


NOW = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)


def _record(
    symbol: str,
    asset_class: CandidateAssetClass,
    provider_kind: str,
) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure=asset_class.value,
        venue="TEST",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type=(
            "spot" if asset_class is CandidateAssetClass.CRYPTO else "common_stock"
        ),
        provider_kind=provider_kind,
        source_identifier=f"test:{symbol}",
    )


def _policy():
    return SimpleNamespace(minimum_history_bars=2)


def test_crypto_bypasses_eodhd_legacy_probe_and_uses_redundant_route(monkeypatch):
    equity = _record("EQ", CandidateAssetClass.INTERNATIONAL_EQUITY, "yahoo")
    crypto = _record("BTC-USD", CandidateAssetClass.CRYPTO, "eodhd")
    seen_legacy: list[DiscoveryCatalogRecord] = []
    seen_redundant: list[DiscoveryCatalogRecord] = []
    equity_feature = object()
    crypto_feature = object()

    def fake_legacy(records, *_args, **_kwargs):
        seen_legacy.extend(records)
        return {"EQ": equity_feature}

    def fake_redundant(records, **_kwargs):
        seen_redundant.extend(records)
        return {"BTC-USD": crypto_feature}

    monkeypatch.setattr(probe._legacy, "default_market_probe", fake_legacy)
    monkeypatch.setattr(probe, "_redundant_preselection_features", fake_redundant)
    monkeypatch.setattr(probe, "create_alpaca_paper_client", lambda: None)

    result = probe.default_provider_preselection_market_probe(
        (equity, crypto), NOW, _policy()
    )

    assert result == {"EQ": equity_feature, "BTC-USD": crypto_feature}
    assert [record.symbol for record in seen_legacy] == ["EQ"]
    assert [record.symbol for record in seen_redundant] == ["BTC-USD"]
    assert seen_redundant[0].provider_kind == "eodhd"


def test_crypto_stays_unresolved_without_redundant_evidence(monkeypatch):
    crypto = _record("ETH-USD", CandidateAssetClass.CRYPTO, "eodhd")
    monkeypatch.setattr(probe._legacy, "default_market_probe", lambda *_a, **_k: {})
    monkeypatch.setattr(
        probe,
        "_redundant_preselection_features",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(probe, "create_alpaca_paper_client", lambda: None)

    result = probe.default_provider_preselection_market_probe(
        (crypto,), NOW, _policy()
    )

    assert result == {}


def test_missing_future_still_uses_redundant_route(monkeypatch):
    future = _record("ESZ6", CandidateAssetClass.FUTURE, "unbound")
    seen: list[DiscoveryCatalogRecord] = []
    future_feature = object()
    monkeypatch.setattr(probe._legacy, "default_market_probe", lambda *_a, **_k: {})
    monkeypatch.setattr(probe, "create_alpaca_paper_client", lambda: None)

    def fake_redundant(records, **_kwargs):
        seen.extend(records)
        return {"ESZ6": future_feature}

    monkeypatch.setattr(probe, "_redundant_preselection_features", fake_redundant)

    result = probe.default_provider_preselection_market_probe(
        (future,), NOW, _policy()
    )

    assert result == {"ESZ6": future_feature}
    assert [record.symbol for record in seen] == ["ESZ6"]
