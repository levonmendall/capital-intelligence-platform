from datetime import datetime, timezone
from types import SimpleNamespace

from cio import CandidateAssetClass
from data.observation import DataQualityState
from operations import _comprehensive_market_discovery_v4 as discovery
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryConfig,
)


_MAX_DIRECTORY_IO_WORKERS = discovery._MAX_DIRECTORY_IO_WORKERS


def test_eodhd_directory_worker_bound_is_fixed():
    assert _MAX_DIRECTORY_IO_WORKERS == 4


def test_directory_prefetch_records_exchange_level_completion_and_fallback(
    monkeypatch,
):
    progress: list[tuple[str, dict[str, int]]] = []
    quality = {
        "LSE": DataQualityState.LIVE,
        "TSE": DataQualityState.FALLBACK,
        "HK": DataQualityState.LIVE,
    }

    class Provider:
        def fetch_dataset(self, query):
            return SimpleNamespace(quality_state=quality[query.provider_symbol])

    monkeypatch.setattr(
        discovery._base,
        "record_manual_cio_diagnostic_progress",
        lambda stage, *, metrics: progress.append((stage, dict(metrics))),
    )
    monkeypatch.setattr(
        discovery._base,
        "_catalog_from_eodhd",
        lambda **_kwargs: {},
    )

    result = discovery._catalog_from_eodhd(
        as_of=datetime(2026, 8, 13, tzinfo=timezone.utc),
        config=ComprehensiveMarketDiscoveryConfig(
            eodhd_exchange_codes=("LSE", "TSE", "HK"),
            futures_roots=(),
            option_underlyings=(),
            yahoo_exchange_suffixes=(),
        ),
        provider=Provider(),
        policy=object(),
        requested_asset_classes=frozenset(
            {CandidateAssetClass.INTERNATIONAL_EQUITY}
        ),
    )

    assert result == {}
    assert len(progress) == 4
    assert all(stage == "catalog_eodhd_directory" for stage, _ in progress)
    assert progress[0][1] == {
        "attempted_exchanges": 3,
        "completed_exchanges": 0,
        "fallback_exchanges": 0,
        "failed_exchanges": 0,
    }
    assert progress[-1][1]["completed_exchanges"] == 3
    assert progress[-1][1]["fallback_exchanges"] == 1
    assert progress[-1][1]["failed_exchanges"] == 0
    assert {metrics["exchange_index"] for _, metrics in progress[1:]} == {0, 1, 2}
