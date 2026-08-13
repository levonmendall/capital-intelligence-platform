"""Bounded-concurrency facade for complete certified-universe discovery.

The prior v4 implementation is preserved byte-for-byte in the adjacent serial module.
This facade changes only independent EODHD symbol-directory I/O: configured exchange
reads are prefetched with a small fixed concurrency bound and then replayed through the
unchanged v4/legacy parser in configured order. No catalog, completeness sentinel,
classification, evidence, threshold, CIO, construction, or execution rule changes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from cio import CandidateAssetClass
from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetType
from operations import _comprehensive_market_discovery_v4_serial as _base
from operations._comprehensive_market_discovery_v4_serial import *  # noqa: F401,F403


_MAX_DIRECTORY_IO_WORKERS = 4


def __getattr__(name: str):
    try:
        return getattr(_base, name)
    except AttributeError as error:
        raise AttributeError(
            f"module 'operations._comprehensive_market_discovery_v4' has no attribute {name!r}"
        ) from error


class _PrefetchedDirectoryProvider:
    __slots__ = ("_delegate", "_snapshots")

    def __init__(self, delegate, snapshots: dict[str, object]) -> None:
        self._delegate = delegate
        self._snapshots = snapshots

    def fetch_dataset(self, query: ProviderDatasetQuery):
        if query.dataset_type is ProviderDatasetType.SYMBOL_DIRECTORY:
            key = query.provider_symbol.strip().upper()
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return snapshot
        return self._delegate.fetch_dataset(query)

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)


def _possible_lanes_for_exchange(exchange: str) -> frozenset[CandidateAssetClass]:
    return {
        "CC": frozenset({CandidateAssetClass.CRYPTO}),
        "FOREX": frozenset({CandidateAssetClass.FX}),
        "BOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
        "GBOND": frozenset({CandidateAssetClass.FIXED_INCOME}),
    }.get(
        exchange,
        frozenset(
            {
                CandidateAssetClass.INTERNATIONAL_EQUITY,
                CandidateAssetClass.REAL_ESTATE,
                CandidateAssetClass.ALTERNATIVE,
                CandidateAssetClass.COMMODITY,
            }
        ),
    )


def _catalog_from_eodhd(
    *,
    as_of,
    config,
    provider,
    policy,
    requested_asset_classes: frozenset[CandidateAssetClass] | None = None,
):
    """Prefetch independent requested directories, then use unchanged v4 parsing."""

    _base._reject_evidence_only_eodhd_directories(config)
    directory_lanes = frozenset(
        item for item in CandidateAssetClass if item is not CandidateAssetClass.OTHER
    )
    requested = (
        directory_lanes
        if requested_asset_classes is None
        else frozenset(requested_asset_classes) & directory_lanes
    )
    requested_exchanges = tuple(
        exchange
        for exchange in config.eodhd_exchange_codes
        if _possible_lanes_for_exchange(exchange) & requested
    )

    def fetch_directory(exchange: str):
        snapshot = provider.fetch_dataset(
            ProviderDatasetQuery(
                dataset_type=ProviderDatasetType.SYMBOL_DIRECTORY,
                provider_symbol=exchange,
                as_of=as_of,
                limit=_base._legacy._PROVIDER_DIRECTORY_CERTIFICATION_LIMIT,
            )
        )
        return exchange, snapshot

    snapshots: dict[str, object] = {}
    if requested_exchanges:
        with ThreadPoolExecutor(
            max_workers=min(_MAX_DIRECTORY_IO_WORKERS, len(requested_exchanges))
        ) as executor:
            snapshots.update(executor.map(fetch_directory, requested_exchanges))

    return _base._catalog_from_eodhd(
        as_of=as_of,
        config=config,
        provider=_PrefetchedDirectoryProvider(provider, snapshots),
        policy=policy,
        requested_asset_classes=requested_asset_classes,
    )


def default_catalog_probe(
    as_of,
    *,
    config=None,
    policy=None,
    eodhd_provider=None,
    databento_options_provider=None,
):
    """Collect the unchanged executable catalogs using bounded directory prefetch."""

    timestamp = _base._legacy._aware(as_of, field_name="as_of")
    resolved_config = config or _base.load_comprehensive_market_discovery_config()
    _base._reject_evidence_only_eodhd_directories(resolved_config)
    resolved_policy = policy or ComprehensiveMarketDiscoveryPolicy()
    active_lanes = _base.scheduled_discovery_lanes(timestamp)
    provider = eodhd_provider or _base._legacy.build_eodhd_provider()
    _base.record_manual_cio_diagnostic_progress(
        "catalog_eodhd_directories",
        metrics={"configured_exchanges": len(resolved_config.eodhd_exchange_codes)},
    )
    result = {
        key: list(value)
        for key, value in _catalog_from_eodhd(
            as_of=timestamp,
            config=resolved_config,
            provider=provider,
            policy=resolved_policy,
            requested_asset_classes=active_lanes,
        ).items()
    }
    _base.record_manual_cio_diagnostic_progress(
        "catalog_eodhd_directories_complete",
        metrics={"catalog_records": sum(len(items) for items in result.values())},
    )
    for asset_class in _base._DEFAULT_REQUIRED_DISCOVERY_LANES:
        result.setdefault(asset_class, [])
    if CandidateAssetClass.FUTURE in active_lanes:
        result[CandidateAssetClass.FUTURE] = list(
            _base._legacy._futures_catalog(as_of=timestamp, config=resolved_config)
        )
    if CandidateAssetClass.OPTION in active_lanes:
        _base.record_manual_cio_diagnostic_progress(
            "catalog_databento_options",
            metrics={"configured_underlyings": len(resolved_config.option_underlyings)},
        )
        result[CandidateAssetClass.OPTION] = list(
            _base._legacy._option_catalog(
                as_of=timestamp,
                config=resolved_config,
                policy=resolved_policy,
                databento_options_provider=databento_options_provider,
            )
        )
        _base.record_manual_cio_diagnostic_progress(
            "catalog_databento_options_complete",
            metrics={"catalog_records": len(result[CandidateAssetClass.OPTION])},
        )
    _base.record_manual_cio_diagnostic_progress(
        "comprehensive_catalog_discovery_complete",
        metrics={"catalog_records": sum(len(items) for items in result.values())},
    )
    return result
