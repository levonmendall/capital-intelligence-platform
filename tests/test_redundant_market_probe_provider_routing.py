from __future__ import annotations

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord
from operations.redundant_market_probe import _eodhd_provider_record, _primary_probe_record


def _record(*, symbol: str, provider_symbol: str, asset_class: CandidateAssetClass, venue: str, source_identifier: str) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol=symbol,
        provider_symbol=provider_symbol,
        name=symbol,
        asset_class=asset_class,
        economic_exposure=(
            "international_equity"
            if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY
            else "foreign_exchange"
            if asset_class is CandidateAssetClass.FX
            else "crypto"
        ),
        venue=venue,
        country_code="GB" if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY else "GLOBAL",
        currency="USD",
        settlement_currency="USD",
        instrument_type="common_stock" if asset_class is CandidateAssetClass.INTERNATIONAL_EQUITY else "spot" if asset_class is CandidateAssetClass.FX else "token",
        provider_kind="yahoo",
        source_identifier=source_identifier,
    )


def test_international_primary_reconstructs_exact_eodhd_symbol() -> None:
    record = _record(
        symbol="VOD_LSE",
        provider_symbol="VOD.L",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        venue="LSE",
        source_identifier="eodhd:symbol-directory:LSE:VOD",
    )

    routed = _primary_probe_record(record)

    assert routed.provider_kind == "eodhd"
    assert routed.provider_symbol == "VOD.LSE"
    assert record.provider_symbol == "VOD.L"


def test_fx_skips_legacy_yahoo_but_preserves_exact_eodhd_fallback_identity() -> None:
    record = _record(
        symbol="EURUSD",
        provider_symbol="EURUSD=X",
        asset_class=CandidateAssetClass.FX,
        venue="FOREX",
        source_identifier="eodhd:symbol-directory:FOREX:EURUSD",
    )

    primary = _primary_probe_record(record)
    eodhd = _eodhd_provider_record(record)

    assert primary.provider_kind == "unbound"
    assert primary.provider_symbol == "EURUSD=X"
    assert eodhd.provider_kind == "eodhd"
    assert eodhd.provider_symbol == "EURUSD.FOREX"


def test_crypto_skips_legacy_yahoo_for_batched_alpaca_path() -> None:
    record = _record(
        symbol="BTC-USD",
        provider_symbol="BTC-USD",
        asset_class=CandidateAssetClass.CRYPTO,
        venue="CC",
        source_identifier="eodhd:symbol-directory:CC:BTC-USD",
    )

    routed = _primary_probe_record(record)

    assert routed.provider_kind == "unbound"
    assert routed.provider_symbol == "BTC-USD"
