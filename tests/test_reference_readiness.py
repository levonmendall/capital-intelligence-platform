from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations import _comprehensive_market_discovery_v4 as discovery
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryConfig,
    DiscoveryCatalogRecord,
)
from operations.reference_readiness import (
    ReferenceReadinessError,
    load_reference_catalogs,
    prepare_reference_readiness,
)
from providers.massive_multi_asset import MassiveMultiAssetProvider


AS_OF = datetime(2026, 8, 13, 20, 30, tzinfo=timezone.utc)


def _config() -> ComprehensiveMarketDiscoveryConfig:
    return ComprehensiveMarketDiscoveryConfig(
        eodhd_exchange_codes=("LSE",),
        futures_roots=(
            {
                "root": "ES",
                "name": "E-mini S&P 500",
                "economic_exposure": "us_equity",
                "contract_multiplier": 50.0,
                "month_codes": ["H", "M", "U", "Z"],
                "years_forward": 2,
                "quote_spread_bps": 1.0,
            },
        ),
        option_underlyings=(),
        yahoo_exchange_suffixes=(("LSE", ".L"),),
    )


def _equity() -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol="VOD.L",
        provider_symbol="VOD.LSE",
        name="Vodafone",
        asset_class=CandidateAssetClass.INTERNATIONAL_EQUITY,
        economic_exposure="communications",
        venue="LSE",
        country_code="GB",
        currency="GBP",
        settlement_currency="GBP",
        instrument_type="equity",
        provider_kind="eodhd",
        source_identifier="eodhd:LSE:VOD",
    )


def _future() -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol="ESZ26",
        provider_symbol="ESZ26",
        name="E-mini S&P 500 ESZ26 dated future",
        asset_class=CandidateAssetClass.FUTURE,
        economic_exposure="us_equity",
        venue="XCME",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="future",
        provider_kind="massive",
        source_identifier="massive:futures-contract:ESZ26:2026-08-13",
        contract_multiplier=50.0,
        quote_spread_bps=1.0,
        expiration_at=datetime(2026, 12, 18, tzinfo=timezone.utc),
        provider_dataset="futures/v1/contracts",
        provider_stype_in="raw_symbol",
    )


def _prepare(monkeypatch, tmp_path):
    config = _config()
    monkeypatch.setattr(
        discovery._base,
        "scheduled_discovery_lanes",
        lambda _timestamp: frozenset(
            {
                CandidateAssetClass.INTERNATIONAL_EQUITY,
                CandidateAssetClass.FUTURE,
            }
        ),
    )
    monkeypatch.setattr(
        discovery,
        "_catalog_from_eodhd",
        lambda **_kwargs: {
            CandidateAssetClass.INTERNATIONAL_EQUITY: (_equity(),),
        },
    )
    monkeypatch.setattr(
        discovery._base._legacy,
        "_futures_catalog",
        lambda **_kwargs: (_future(),),
    )
    values = {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": "release-test",
    }
    manifest = prepare_reference_readiness(
        values,
        now=AS_OF,
        config=config,
        policy=object(),
        eodhd_provider=object(),
        massive_futures_provider=object(),
    )
    return config, values, manifest


def test_reference_manifest_round_trips_exact_catalogs(monkeypatch, tmp_path) -> None:
    config, values, manifest = _prepare(monkeypatch, tmp_path)

    catalogs = load_reference_catalogs(
        as_of=AS_OF + timedelta(minutes=1),
        config=config,
        values=values,
        record_type=DiscoveryCatalogRecord,
    )

    assert catalogs is not None
    assert [item.symbol for item in catalogs[CandidateAssetClass.INTERNATIONAL_EQUITY]] == [
        "VOD.L"
    ]
    assert [item.symbol for item in catalogs[CandidateAssetClass.FUTURE]] == ["ESZ26"]
    assert values["CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"] == manifest.manifest_id
    assert manifest.path.exists()


def test_reference_manifest_integrity_is_fail_closed(monkeypatch, tmp_path) -> None:
    config, values, manifest = _prepare(monkeypatch, tmp_path)
    payload = json.loads(manifest.path.read_text(encoding="utf-8"))
    payload["catalogs"]["future"][0]["symbol"] = "ESM27"
    manifest.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ReferenceReadinessError, match="integrity"):
        load_reference_catalogs(
            as_of=AS_OF + timedelta(minutes=1),
            config=config,
            values=values,
        )


def test_reference_manifest_staleness_is_fail_closed(monkeypatch, tmp_path) -> None:
    config, values, _manifest = _prepare(monkeypatch, tmp_path)

    with pytest.raises(ReferenceReadinessError, match="stale"):
        load_reference_catalogs(
            as_of=AS_OF + timedelta(hours=3),
            config=config,
            values=values,
        )


def test_bound_manifest_skips_eodhd_and_massive_reference_calls(monkeypatch, tmp_path) -> None:
    config, values, manifest = _prepare(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH",
        str(manifest.path),
    )
    monkeypatch.setenv(
        "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID",
        manifest.manifest_id,
    )
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_RELEASE", values["CAPITAL_INTELLIGENCE_RELEASE"])
    monkeypatch.setattr(
        discovery._base,
        "scheduled_discovery_lanes",
        lambda _timestamp: frozenset(
            {
                CandidateAssetClass.INTERNATIONAL_EQUITY,
                CandidateAssetClass.FUTURE,
            }
        ),
    )
    monkeypatch.setattr(
        discovery,
        "_catalog_from_eodhd",
        lambda **_kwargs: pytest.fail("EODHD reference collection ran inside CIO"),
    )
    monkeypatch.setattr(
        discovery._base._legacy,
        "_futures_catalog",
        lambda **_kwargs: pytest.fail("Massive futures reference collection ran inside CIO"),
    )

    result = discovery.default_catalog_probe(
        AS_OF + timedelta(minutes=1),
        config=config,
        policy=SimpleNamespace(),
    )

    assert [item.symbol for item in result[CandidateAssetClass.INTERNATIONAL_EQUITY]] == [
        "VOD.L"
    ]
    assert [item.symbol for item in result[CandidateAssetClass.FUTURE]] == ["ESZ26"]


def test_massive_rate_limit_retries_before_reference_failure() -> None:
    class Response:
        def __init__(self, payload, status_code):
            self.payload = payload
            self.status_code = status_code
            self.headers = {"Retry-After": "0"}

        def json(self):
            return self.payload

    responses = iter(
        (
            Response({}, 429),
            Response({"status": "OK", "results": []}, 200),
        )
    )
    calls = []

    def get(*_args, **_kwargs):
        calls.append(1)
        return next(responses)

    provider = MassiveMultiAssetProvider(
        "test-key",
        max_attempts=2,
        backoff_seconds=0,
        http_get=get,
        sleeper=lambda _seconds: None,
    )

    assert provider.futures_contracts(as_of=AS_OF) == ()
    assert len(calls) == 2
