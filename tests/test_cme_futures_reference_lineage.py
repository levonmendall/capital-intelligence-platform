from __future__ import annotations

from datetime import datetime, timezone

from cio import CandidateAssetClass
from operations import cme_futures_reference_runtime as runtime
from operations.comprehensive_market_discovery_legacy import DiscoveryCatalogRecord


def _record(source_identifier: str) -> DiscoveryCatalogRecord:
    return DiscoveryCatalogRecord(
        symbol="ESU6",
        provider_symbol="ESU6",
        name="E-mini S&P 500 ESU6 dated future",
        asset_class=CandidateAssetClass.FUTURE,
        economic_exposure="us_large_cap_equity",
        venue="CME",
        country_code="US",
        currency="USD",
        settlement_currency="USD",
        instrument_type="future",
        provider_kind="massive",
        provider_dataset="futures/v1/contracts",
        provider_stype_in="raw_symbol",
        source_identifier=source_identifier,
        expiration_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )


def test_cme_lineage_is_rewritten_without_touching_massive(monkeypatch) -> None:
    cme = _record("cme-fprf:cme:ES:202609:2026-08-14")
    massive = _record("massive:futures-contract:ESU6:2026-08-14")
    monkeypatch.setattr(runtime, "_ORIGINAL", lambda *args, **kwargs: (cme, massive))

    rewritten = runtime._cme_aware_futures_catalog()

    assert rewritten[0].provider_kind == "cme_fprf"
    assert rewritten[0].provider_dataset == "ftp/fprf/fixml"
    assert rewritten[1].provider_kind == "massive"
    assert rewritten[1].provider_dataset == "futures/v1/contracts"
