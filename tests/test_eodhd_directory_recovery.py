from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from data.observation import DataQualityState
from operations import _comprehensive_market_discovery_v4 as discovery
from operations.generalized_reference_readiness import _EODHD_REFERENCE_LANES


NOW = datetime(2026, 8, 14, 13, 26, tzinfo=timezone.utc)


class _RecoveringDirectoryProvider:
    def __init__(self, *, permanently_failed: frozenset[str] = frozenset()) -> None:
        self.calls: Counter[str] = Counter()
        self.permanently_failed = permanently_failed

    def fetch_dataset(self, query):
        exchange = query.provider_symbol.strip().upper()
        self.calls[exchange] += 1
        if exchange in self.permanently_failed:
            raise RuntimeError(f"{exchange} unavailable")
        if exchange == "LSE" and self.calls[exchange] == 1:
            raise RuntimeError("LSE transient burst failure")
        return SimpleNamespace(quality_state=DataQualityState.LIVE)


def _config():
    return SimpleNamespace(eodhd_exchange_codes=("LSE", "XETRA"))


def _disable_parser_and_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        discovery._base,
        "record_manual_cio_diagnostic_progress",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        discovery._base,
        "_catalog_from_eodhd",
        lambda **kwargs: {},
    )


def test_parallel_directory_failure_gets_one_serial_recovery(monkeypatch) -> None:
    _disable_parser_and_progress(monkeypatch)
    provider = _RecoveringDirectoryProvider()

    discovery._catalog_from_eodhd(
        as_of=NOW,
        config=_config(),
        provider=provider,
        policy=object(),
        requested_asset_classes=frozenset(
            {CandidateAssetClass.INTERNATIONAL_EQUITY}
        ),
    )

    assert provider.calls["LSE"] == 2
    assert provider.calls["XETRA"] == 1


def test_directory_recovery_remains_fail_closed(monkeypatch) -> None:
    _disable_parser_and_progress(monkeypatch)
    provider = _RecoveringDirectoryProvider(permanently_failed=frozenset({"LSE"}))

    with pytest.raises(RuntimeError, match="LSE unavailable"):
        discovery._catalog_from_eodhd(
            as_of=NOW,
            config=_config(),
            provider=provider,
            policy=object(),
            requested_asset_classes=frozenset(
                {CandidateAssetClass.INTERNATIONAL_EQUITY}
            ),
        )

    assert provider.calls["LSE"] == 2
    assert provider.calls["XETRA"] == 1


def test_generalized_reference_includes_all_executable_eodhd_asset_lanes() -> None:
    assert {
        CandidateAssetClass.INTERNATIONAL_EQUITY,
        CandidateAssetClass.REAL_ESTATE,
        CandidateAssetClass.ALTERNATIVE,
        CandidateAssetClass.COMMODITY,
        CandidateAssetClass.FX,
        CandidateAssetClass.CRYPTO,
    } <= _EODHD_REFERENCE_LANES
    assert CandidateAssetClass.FIXED_INCOME not in _EODHD_REFERENCE_LANES
