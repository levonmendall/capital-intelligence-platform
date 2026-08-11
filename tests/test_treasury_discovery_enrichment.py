from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
import operations.comprehensive_market_discovery_legacy as legacy
from providers.treasury_fiscal_data import TreasurySecurityReference


class _EodhdDirectoryProvider:
    def fetch_dataset(self, query):
        assert query.provider_symbol == "BOND"
        return SimpleNamespace(
            provider_record_id="eodhd:symbol-directory:BOND:2026-08-11",
            payload={
                "active": [
                    {
                        "Code": "UST2Y",
                        "Name": "United States Treasury 2 Year Note",
                        "Type": "Government Bond",
                        "Currency": "USD",
                        "CountryISO2": "US",
                        "Exchange": "BOND",
                        "CUSIP": "91282CJL6",
                    },
                    {
                        "Code": "CORP1",
                        "Name": "Example Corporate Bond",
                        "Type": "Bond",
                        "Currency": "USD",
                        "CountryISO2": "US",
                        "Exchange": "BOND",
                    },
                ]
            },
        )


class _TreasuryProvider:
    def fetch_active_securities(self, *, as_of):
        assert as_of == datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc)
        return (
            TreasurySecurityReference(
                cusip="91282CJL6",
                security_type="Note",
                security_term="2-Year",
                record_date=date(2026, 8, 10),
                auction_date=date(2026, 7, 27),
                issue_date=date(2026, 7, 31),
                maturity_date=date(2028, 7, 31),
                high_yield=4.125,
            ),
        )


def test_fixed_income_catalog_uses_treasury_only_on_exact_explicit_cusip(monkeypatch) -> None:
    monkeypatch.setattr(
        legacy,
        "build_treasury_fiscal_data_provider",
        lambda: _TreasuryProvider(),
    )
    config = legacy.ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=("BOND",),
        futures_roots=(),
        option_underlyings=(),
        yahoo_exchange_suffixes=(),
    )

    result = legacy._catalog_from_eodhd(
        as_of=datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc),
        config=config,
        provider=_EodhdDirectoryProvider(),
        policy=legacy.ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
    )

    records = result[CandidateAssetClass.FIXED_INCOME]
    treasury = next(item for item in records if item.symbol == "UST2Y")
    corporate = next(item for item in records if item.symbol == "CORP1")

    assert treasury.instrument_identifier == "cusip:91282CJL6"
    assert "treasury-fiscal-data:auctions_query:91282CJL6:2026-08-10" in treasury.source_identifier
    assert corporate.instrument_identifier is None
    assert "treasury-fiscal-data" not in corporate.source_identifier


def test_fixed_income_catalog_does_not_promote_invalid_cusip(monkeypatch) -> None:
    class _InvalidCusipDirectoryProvider:
        def fetch_dataset(self, query):
            return SimpleNamespace(
                provider_record_id="eodhd:symbol-directory:BOND:2026-08-11",
                payload={
                    "active": [
                        {
                            "Code": "USTBAD",
                            "Name": "United States Treasury Note",
                            "Type": "Government Bond",
                            "Currency": "USD",
                            "CountryISO2": "US",
                            "Exchange": "BOND",
                            "CUSIP": "91282CZZ9",
                        }
                    ]
                },
            )

    monkeypatch.setattr(
        legacy,
        "build_treasury_fiscal_data_provider",
        lambda: _TreasuryProvider(),
    )
    config = legacy.ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=("BOND",),
        futures_roots=(),
        option_underlyings=(),
        yahoo_exchange_suffixes=(),
    )

    result = legacy._catalog_from_eodhd(
        as_of=datetime(2026, 8, 11, 19, 0, tzinfo=timezone.utc),
        config=config,
        provider=_InvalidCusipDirectoryProvider(),
        policy=legacy.ComprehensiveMarketDiscoveryPolicy(),
        requested_asset_classes=frozenset({CandidateAssetClass.FIXED_INCOME}),
    )

    record = result[CandidateAssetClass.FIXED_INCOME][0]
    assert record.instrument_identifier is None
    assert "treasury-fiscal-data" not in record.source_identifier
