from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from providers.cme_futures_reference_executable import (
    CmeExecutableFuturesReferenceProvider,
)
from providers.massive_futures_reference_rate_resilient import (
    MassiveFuturesReferenceProvider,
    _BoundedMassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


AS_OF = datetime(2026, 8, 18, 0, 15, tzinfo=timezone.utc)


def _contract(root: str) -> MassiveFuturesContract:
    return MassiveFuturesContract(
        ticker=f"{root}U6",
        product_code=root,
        trading_venue="CME",
        first_trade_date=(AS_OF.date() - timedelta(days=30)).isoformat(),
        last_trade_date=(AS_OF.date() + timedelta(days=30)).isoformat(),
        settlement_date=None,
        active=True,
        source_identifier=f"test:{root}",
    )


def test_cme_executable_timeout_reserves_fallback_budget() -> None:
    provider = CmeExecutableFuturesReferenceProvider()
    assert provider.timeout == 15
    assert len(provider.file_urls) == 4
    assert provider.timeout * len(provider.file_urls) < 120


def test_massive_root_cache_reuses_successful_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    calls: list[str] = []

    def fake_root_fetch(self, *, as_of, product_codes=(), maximum_pages=20):
        assert as_of == AS_OF
        assert maximum_pages == 3
        root = tuple(product_codes)[0]
        calls.append(root)
        return (_contract(root),)

    monkeypatch.setattr(
        _BoundedMassiveFuturesReferenceProvider,
        "futures_contracts",
        fake_root_fetch,
    )

    first = MassiveFuturesReferenceProvider(
        api_key="test",
        minimum_call_interval_seconds=0.0,
    )
    rows = first.futures_contracts(
        as_of=AS_OF,
        product_codes=("ES", "NQ"),
        maximum_pages=3,
    )
    assert {item.product_code for item in rows} == {"ES", "NQ"}
    assert calls == ["ES", "NQ"]

    second = MassiveFuturesReferenceProvider(
        api_key="test",
        minimum_call_interval_seconds=0.0,
    )
    rows = second.futures_contracts(
        as_of=AS_OF,
        product_codes=("ES", "NQ"),
        maximum_pages=3,
    )
    assert {item.product_code for item in rows} == {"ES", "NQ"}
    assert calls == ["ES", "NQ"]
    assert all(
        row.get("query_mode") == "persistent_root_cache"
        for row in second.reference_telemetry
    )


def test_massive_later_root_survives_earlier_root_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("CAPITAL_INTELLIGENCE_DATA_DIR", str(tmp_path))
    calls: list[str] = []
    fail_es = {"enabled": True}

    def fake_root_fetch(self, *, as_of, product_codes=(), maximum_pages=20):
        root = tuple(product_codes)[0]
        calls.append(root)
        if root == "ES" and fail_es["enabled"]:
            raise MassiveMultiAssetError("temporary ES failure", retryable=True)
        return (_contract(root),)

    monkeypatch.setattr(
        _BoundedMassiveFuturesReferenceProvider,
        "futures_contracts",
        fake_root_fetch,
    )

    provider = MassiveFuturesReferenceProvider(
        api_key="test",
        minimum_call_interval_seconds=0.0,
    )
    with pytest.raises(MassiveMultiAssetError, match="remains incomplete: ES"):
        provider.futures_contracts(
            as_of=AS_OF,
            product_codes=("ES", "NQ"),
            maximum_pages=3,
        )
    assert calls == ["ES", "NQ"]

    fail_es["enabled"] = False
    resumed = MassiveFuturesReferenceProvider(
        api_key="test",
        minimum_call_interval_seconds=0.0,
    )
    rows = resumed.futures_contracts(
        as_of=AS_OF,
        product_codes=("ES", "NQ"),
        maximum_pages=3,
    )
    assert {item.product_code for item in rows} == {"ES", "NQ"}
    assert calls == ["ES", "NQ", "ES"]
