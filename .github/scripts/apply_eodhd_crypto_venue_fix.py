from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"expected one match in {path}, found {count}: {old[:100]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


source = ROOT / "operations/comprehensive_market_discovery.py"
replace_once(
    source,
    '''            if "common stock" in raw_type or "preferred stock" in raw_type:\n                if country == "US" or exchange in {"US", "NASDAQ", "NYSE", "AMEX"}:\n                    continue\n                asset_class = CandidateAssetClass.INTERNATIONAL_EQUITY\n                instrument_type = "preferred_stock" if "preferred" in raw_type else "common_stock"\n                economic_exposure = "international_equity"\n            elif "currency" in raw_type or "forex" in raw_type:\n                asset_class = CandidateAssetClass.FX\n                instrument_type = "spot"\n                economic_exposure = "foreign_exchange"\n            elif "crypto" in raw_type:\n                asset_class = CandidateAssetClass.CRYPTO\n                instrument_type = "token"\n                economic_exposure = "crypto"\n            elif "bond" in raw_type:\n''',
    '''            # EODHD's virtual CC exchange is authoritative for crypto. Its\n            # symbol-directory rows are intentionally typed as ``Currency``, so\n            # classifying by the generic row type first incorrectly routes every\n            # crypto pair into the FX parser and rejects it as a non-six-letter\n            # spot pair. Preserve the provider's venue semantics before applying\n            # generic type-based fallbacks.\n            if exchange == "CC":\n                asset_class = CandidateAssetClass.CRYPTO\n                instrument_type = "token"\n                economic_exposure = "crypto"\n            elif "common stock" in raw_type or "preferred stock" in raw_type:\n                if country == "US" or exchange in {"US", "NASDAQ", "NYSE", "AMEX"}:\n                    continue\n                asset_class = CandidateAssetClass.INTERNATIONAL_EQUITY\n                instrument_type = "preferred_stock" if "preferred" in raw_type else "common_stock"\n                economic_exposure = "international_equity"\n            elif "currency" in raw_type or "forex" in raw_type:\n                asset_class = CandidateAssetClass.FX\n                instrument_type = "spot"\n                economic_exposure = "foreign_exchange"\n            elif "crypto" in raw_type:\n                asset_class = CandidateAssetClass.CRYPTO\n                instrument_type = "token"\n                economic_exposure = "crypto"\n            elif "bond" in raw_type:\n''',
)


test_path = ROOT / "tests/test_comprehensive_market_discovery.py"
replace_once(
    test_path,
    "from datetime import datetime, timedelta, timezone\n",
    "from datetime import datetime, timedelta, timezone\nfrom types import SimpleNamespace\n",
)
replace_once(
    test_path,
    '''    ComprehensiveMarketDiscoveryPolicy,\n    DiscoveryCatalogRecord,\n''',
    '''    ComprehensiveMarketDiscoveryConfig,\n    ComprehensiveMarketDiscoveryPolicy,\n    DiscoveryCatalogRecord,\n    _catalog_from_eodhd,\n''',
)
anchor = "\ndef test_discovers_all_six_lanes_and_retains_holdings():\n"
new_test = '''\ndef test_eodhd_cc_currency_rows_are_classified_as_crypto():\n    class Provider:\n        def fetch_dataset(self, query):\n            assert query.provider_symbol == "CC"\n            return SimpleNamespace(\n                payload={\n                    "active": [\n                        {\n                            "Code": "BTC-USD",\n                            "Name": "Bitcoin",\n                            "Type": "Currency",\n                            "Currency": "USD",\n                            "Exchange": "CC",\n                        }\n                    ]\n                },\n                provider_record_id="eodhd-symbol-directory:CC",\n            )\n\n    catalogs = _catalog_from_eodhd(\n        as_of=AS_OF,\n        config=ComprehensiveMarketDiscoveryConfig(\n            eodhd_exchange_codes=("CC",),\n            futures_roots=(),\n            option_underlyings=(),\n            yahoo_exchange_suffixes=(),\n        ),\n        provider=Provider(),\n        policy=ComprehensiveMarketDiscoveryPolicy(),\n        requested_asset_classes=frozenset({CandidateAssetClass.CRYPTO}),\n    )\n\n    assert CandidateAssetClass.FX not in catalogs\n    assert len(catalogs[CandidateAssetClass.CRYPTO]) == 1\n    record = catalogs[CandidateAssetClass.CRYPTO][0]\n    assert record.symbol == "BTCUSD"\n    assert record.provider_symbol == "BTC-USD"\n    assert record.asset_class is CandidateAssetClass.CRYPTO\n    assert record.instrument_type == "token"\n    assert record.provider_kind == "yahoo"\n\n\n'''
replace_once(test_path, anchor, new_test + anchor)
