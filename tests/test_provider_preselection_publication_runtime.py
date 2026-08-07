from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery import (
    CatalogScreeningSignal,
    ComprehensiveMarketDiscoveryError,
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    discover_comprehensive_markets,
)
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
