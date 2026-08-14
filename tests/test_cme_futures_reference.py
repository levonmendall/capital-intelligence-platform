from __future__ import annotations

import io
from datetime import datetime, timezone

import pytest

from providers.cme_futures_reference import CmeFuturesReferenceProvider
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


class _FakeResponse:
    def __init__(self, xml: str, status_code: int = 200) -> None:
        self.status_code = status_code
        self.raw = io.BytesIO(xml.encode("utf-8"))
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _MappedGet:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def __call__(self, url: str, **_kwargs):
        self.calls.append(url)
        if url not in self.payloads:
            raise AssertionError(f"unexpected CME request {url}")
        return _FakeResponse(self.payloads[url])


class _Fallback:
    configured = True

    def __init__(self, contracts: tuple[MassiveFuturesContract, ...]) -> None:
        self.contracts = contracts
        self.calls = 0

    def futures_contracts(self, **_kwargs):
        self.calls += 1
        return self.contracts


def _fprf(*rows: tuple[str, str, str, str]) -> str:
    secdefs = []
    for root, exchange, maturity, last_trade in rows:
        secdefs.append(
            f'''<SecDef BizDt="2026-08-14">
  <Instrmt ID="{root}" Src="H" MMY="{maturity}" SecTyp="FUT" Exch="{exchange}" Status="1" MatDt="{last_trade}">
    <Evnt EventTyp="5" Dt="2025-01-01" />
    <Evnt EventTyp="7" Dt="{last_trade}" />
  </Instrmt>
</SecDef>'''
        )
    return "<FIXML><Batch>" + "".join(secdefs) + "</Batch></FIXML>"


def _massive_contract(root: str, ticker: str, venue: str) -> MassiveFuturesContract:
    return MassiveFuturesContract(
        ticker=ticker,
        product_code=root,
        trading_venue=venue,
        first_trade_date="2025-01-01",
        last_trade_date="2026-09-18",
        settlement_date="2026-09-18",
        active=True,
        source_identifier=f"massive:futures-contract:{ticker}:2026-08-14",
    )


def test_cme_is_primary_and_daily_snapshot_is_reused(tmp_path) -> None:
    urls = (("CME", "https://example/cme.xml"), ("NYMEX", "https://example/nymex.xml"))
    getter = _MappedGet(
        {
            "https://example/cme.xml": _fprf(("ES", "CME", "202609", "2026-09-18")),
            "https://example/nymex.xml": _fprf(("CL", "NYMEX", "202609", "2026-09-18")),
        }
    )
    fallback = _Fallback((_massive_contract("ES", "ESU26", "CME"),))
    as_of = datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc)
    provider = CmeFuturesReferenceProvider(
        fallback_provider=fallback,
        http_get=getter,
        file_urls=urls,
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
        now=lambda: as_of,
    )

    first = provider.futures_contracts(as_of=as_of, product_codes=("ES", "CL"))
    second = provider.futures_contracts(as_of=as_of, product_codes=("ES", "CL"))

    assert [(item.product_code, item.ticker) for item in first] == [("CL", "CLU26"), ("ES", "ESU26")]
    assert second == first
    assert fallback.calls == 0
    assert getter.calls == ["https://example/cme.xml", "https://example/nymex.xml"]
    assert all(item.source_identifier.startswith("cme-fprf:") for item in first)
    assert provider.reference_metadata["provider"] == "cme_fprf_cache"
    cache_files = list((tmp_path / "reference_readiness").glob("cme-futures-daily-*.json"))
    assert len(cache_files) == 1


def test_incomplete_cme_uses_complete_massive_fallback(tmp_path) -> None:
    getter = _MappedGet(
        {"https://example/cme.xml": _fprf(("ES", "CME", "202609", "2026-09-18"))}
    )
    fallback = _Fallback(
        (
            _massive_contract("ES", "ESU26", "CME"),
            _massive_contract("CL", "CLU26", "NYMEX"),
        )
    )
    provider = CmeFuturesReferenceProvider(
        fallback_provider=fallback,
        http_get=getter,
        file_urls=(("CME", "https://example/cme.xml"),),
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    contracts = provider.futures_contracts(
        as_of=datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc),
        product_codes=("ES", "CL"),
    )

    assert {item.product_code for item in contracts} == {"ES", "CL"}
    assert fallback.calls == 1
    assert provider.reference_metadata["provider"] == "massive_fallback"


def test_incomplete_cme_without_fallback_remains_fail_closed(tmp_path) -> None:
    provider = CmeFuturesReferenceProvider(
        http_get=_MappedGet(
            {"https://example/cme.xml": _fprf(("ES", "CME", "202609", "2026-09-18"))}
        ),
        file_urls=(("CME", "https://example/cme.xml"),),
        values={"CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path)},
    )

    with pytest.raises(MassiveMultiAssetError, match="fallback is not configured"):
        provider.futures_contracts(
            as_of=datetime(2026, 8, 14, 18, 0, tzinfo=timezone.utc),
            product_codes=("ES", "CL"),
        )
