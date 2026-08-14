"""Bounded-concurrency facade for complete certified-universe discovery.

The prior v4 implementation is preserved byte-for-byte in the adjacent serial module.
This facade changes only independent EODHD symbol-directory I/O: configured exchange
reads are prefetched with a small fixed concurrency bound and then replayed through the
unchanged v4/legacy parser in configured order. A release diagnostic may additionally
consume an explicitly bound, integrity-checked pre-CIO reference manifest so slow-changing
exchange and futures catalog acquisition does not consume the bounded CIO analysis budget.
No catalog, completeness sentinel, classification, evidence, threshold, CIO,
construction, or execution rule changes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from cio import CandidateAssetClass
from data.observation import DataQualityState
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
    """Prefetch requested directories with bounded serial recovery, then parse.

    The normal path remains bounded parallel I/O. If one or more exchange reads fail,
    successful exchange snapshots are retained and only the failed exchanges receive one
    serial recovery attempt. This removes burst/rate-limit sensitivity without changing
    completeness: any exchange that remains unresolved after that bounded recovery still
    aborts the catalog fail-closed.
    """

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
        attempted = len(requested_exchanges)
        completed = 0
        fallback_count = 0
        failures: dict[int, tuple[str, Exception]] = {}
        _base.record_manual_cio_diagnostic_progress(
            "catalog_eodhd_directory",
            metrics={
                "attempted_exchanges": attempted,
                "completed_exchanges": completed,
                "fallback_exchanges": fallback_count,
                "failed_exchanges": 0,
            },
        )
        with ThreadPoolExecutor(
            max_workers=min(_MAX_DIRECTORY_IO_WORKERS, len(requested_exchanges))
        ) as executor:
            pending = {
                executor.submit(fetch_directory, exchange): index
                for index, exchange in enumerate(requested_exchanges)
            }
            for future in as_completed(pending):
                exchange_index = pending[future]
                try:
                    exchange, snapshot = future.result()
                except Exception as error:
                    failures[exchange_index] = (
                        requested_exchanges[exchange_index],
                        error,
                    )
                    _base.record_manual_cio_diagnostic_progress(
                        "catalog_eodhd_directory",
                        metrics={
                            "exchange_index": exchange_index,
                            "attempted_exchanges": attempted,
                            "completed_exchanges": completed,
                            "fallback_exchanges": fallback_count,
                            "failed_exchanges": len(failures),
                            "recovery_exchanges": len(failures),
                            "recovered_exchanges": 0,
                        },
                    )
                    continue
                snapshots[exchange] = snapshot
                completed += 1
                if getattr(snapshot, "quality_state", None) is DataQualityState.FALLBACK:
                    fallback_count += 1
                _base.record_manual_cio_diagnostic_progress(
                    "catalog_eodhd_directory",
                    metrics={
                        "exchange_index": exchange_index,
                        "attempted_exchanges": attempted,
                        "completed_exchanges": completed,
                        "fallback_exchanges": fallback_count,
                        "failed_exchanges": len(failures),
                    },
                )

        if failures:
            recovery_total = len(failures)
            recovered = 0
            unresolved: list[tuple[int, str, Exception]] = []
            for exchange_index in sorted(failures):
                exchange, _initial_error = failures[exchange_index]
                try:
                    recovered_exchange, snapshot = fetch_directory(exchange)
                except Exception as recovery_error:
                    unresolved.append((exchange_index, exchange, recovery_error))
                    _base.record_manual_cio_diagnostic_progress(
                        "catalog_eodhd_directory",
                        metrics={
                            "exchange_index": exchange_index,
                            "attempted_exchanges": attempted,
                            "completed_exchanges": completed,
                            "fallback_exchanges": fallback_count,
                            "failed_exchanges": len(unresolved),
                            "recovery_exchanges": recovery_total,
                            "recovered_exchanges": recovered,
                        },
                    )
                    continue
                snapshots[recovered_exchange] = snapshot
                completed += 1
                recovered += 1
                if getattr(snapshot, "quality_state", None) is DataQualityState.FALLBACK:
                    fallback_count += 1
                _base.record_manual_cio_diagnostic_progress(
                    "catalog_eodhd_directory",
                    metrics={
                        "exchange_index": exchange_index,
                        "attempted_exchanges": attempted,
                        "completed_exchanges": completed,
                        "fallback_exchanges": fallback_count,
                        "failed_exchanges": len(unresolved),
                        "recovery_exchanges": recovery_total,
                        "recovered_exchanges": recovered,
                    },
                )

            if unresolved:
                exchange_index, _exchange, error = unresolved[0]
                _base.record_manual_cio_diagnostic_progress(
                    "catalog_eodhd_directory",
                    metrics={
                        "exchange_index": exchange_index,
                        "attempted_exchanges": attempted,
                        "completed_exchanges": completed,
                        "fallback_exchanges": fallback_count,
                        "failed_exchanges": len(unresolved),
                        "recovery_exchanges": recovery_total,
                        "recovered_exchanges": recovered,
                    },
                )
                raise error

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
    """Collect executable catalogs, preferring an explicitly bound reference manifest."""

    from operations.reference_readiness import (
        ReferenceReadinessError,
        load_reference_catalogs,
    )

    timestamp = _base._legacy._aware(as_of, field_name="as_of")
    resolved_config = config or _base.load_comprehensive_market_discovery_config()
    _base._reject_evidence_only_eodhd_directories(resolved_config)
    resolved_policy = policy or ComprehensiveMarketDiscoveryPolicy()
    active_lanes = _base.scheduled_discovery_lanes(timestamp)

    try:
        reference_catalogs = load_reference_catalogs(
            as_of=timestamp,
            config=resolved_config,
            record_type=_base._legacy.DiscoveryCatalogRecord,
        )
    except ReferenceReadinessError as error:
        raise _base._legacy.ComprehensiveMarketDiscoveryError(
            f"governed reference readiness is unavailable: {error}"
        ) from error

    if reference_catalogs is None:
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
    else:
        result = {
            key: list(value)
            for key, value in reference_catalogs.items()
            if key in active_lanes
        }

    for asset_class in _base._DEFAULT_REQUIRED_DISCOVERY_LANES:
        result.setdefault(asset_class, [])

    if CandidateAssetClass.FUTURE in active_lanes:
        if reference_catalogs is None:
            _base.record_manual_cio_diagnostic_progress(
                "comprehensive_catalog_discovery",
                metrics={"catalog_records": sum(len(items) for items in result.values())},
            )
            result[CandidateAssetClass.FUTURE] = list(
                _base._legacy._futures_catalog(as_of=timestamp, config=resolved_config)
            )
        elif not result.get(CandidateAssetClass.FUTURE):
            raise _base._legacy.ComprehensiveMarketDiscoveryError(
                "bound reference manifest does not contain the scheduled futures catalog"
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
