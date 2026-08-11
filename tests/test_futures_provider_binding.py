from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    default_market_probe,
)


AS_OF = datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc)


def test_generated_dated_futures_are_not_mislabeled_as_yahoo_provider_records() -> None:
    payload = json.loads(
        Path("config/comprehensive_market_discovery.json").read_text(encoding="utf-8")
    )
    roots = payload["futures_roots"]

    assert roots
    assert {item["provider_kind"] for item in roots} == {"unbound"}


def test_unbound_dated_future_fails_closed_without_provider_history_request() -> None:
    calls: list[str] = []

    def unexpected_http_get(url: str, **_kwargs):
        calls.append(url)
        raise AssertionError("unbound dated future must not issue a Yahoo history request")

    record = DiscoveryCatalogRecord(
        symbol="ESZ26",
        provider_symbol="ESZ26.CME",
        name="E-mini S&P 500 Z26 dated future",
        asset_class=CandidateAssetClass.FUTURE,
        economic_exposure="us_equity",
        venue="CME",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="future",
        provider_kind="unbound",
        source_identifier="configured-futures-root:ES:ESZ26",
        contract_multiplier=50.0,
        quote_spread_bps=1.0,
        expiration_at=datetime(2026, 12, 20, 21, 0, tzinfo=timezone.utc),
    )

    result = default_market_probe(
        (record,),
        AS_OF,
        ComprehensiveMarketDiscoveryPolicy(),
        http_get=unexpected_http_get,
        maximum_workers=1,
    )

    assert result == {}
    assert calls == []
