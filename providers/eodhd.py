"""EODHD provider facade with cache-first symbol-directory continuity.

The implementation remains in :mod:`providers.eodhd_base`. This facade makes a valid
recent EODHD directory cache the normal hot path so all-market certification does not
re-download every exchange directory on every CIO cycle. When a cache is absent/stale,
live EODHD retrieval remains authoritative; bounded continuity rules then apply exactly
as before.

A current active directory is not discarded solely because the historical delisted-
symbol directory is temporarily unavailable. Missing or incomplete fallback evidence,
authentication failures, persistent provider throttling, virtual markets without a
certified reference selector, and every non-directory provider failure remain fail-
closed.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers import eodhd_base as _base
from providers.eodhd_base import (
    EODHDBindingRegistry,
    EODHDInstrumentBinding,
    EODHDProviderError,
    EODHDRetrievalFailure,
    EODHDRetrievalPolicy,
    load_eodhd_bindings,
)
from providers.twelve_data_reference import (
    TwelveDataReferenceError,
    TwelveDataReferenceProvider,
)
from providers.twelve_data_reference_rate_limited import (
    build_twelve_data_rate_limited_reference_provider,
)


_DIRECTORY_CONTINUITY_STATUS_CODES = frozenset({402, 404})


def __getattr__(name: str):
    """Preserve compatibility for non-exported constants and helpers."""
    try:
        return getattr(_base, name)
    except AttributeError as error:
        raise AttributeError(
            f"module 'providers.eodhd' has no attribute {name!r}"
        ) from error


class EODHDProvider(_base.EODHDProvider):
    """Apply cache-first and bounded continuity to EODHD symbol directories."""

    def __init__(
        self,
        *args,
        reference_provider: TwelveDataReferenceProvider | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._reference_provider = reference_provider

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        if query.dataset_type is not ProviderDatasetType.SYMBOL_DIRECTORY:
            return super().fetch_dataset(query)

        retrieved_at = self._now()
        snapshot_query = query
        live_retrieval_limitations: tuple[str, ...] = ()
        if retrieved_at > query.as_of:
            retrieval_delay = retrieved_at - query.as_of
            if retrieval_delay <= _base._LIVE_DATASET_QUERY_GRACE:
                snapshot_query = replace(query, as_of=retrieved_at)
                live_retrieval_limitations = (
                    "live retrieval availability is recorded at collection time; "
                    f"the requested cutoff was {query.as_of.isoformat()}",
                )

        try:
            (
                active_directory,
                quality_state,
                cached_at,
                directory_limitations,
            ) = self._active_symbol_directory(
                query.provider_symbol,
                retrieved_at=retrieved_at,
            )
        except EODHDRetrievalFailure as error:
            if error.status_code not in _DIRECTORY_CONTINUITY_STATUS_CODES:
                raise
            fallback = self._reference_provider
            if fallback is None:
                fallback = build_twelve_data_rate_limited_reference_provider()
                self._reference_provider = fallback
            try:
                return fallback.fetch_dataset(query)
            except TwelveDataReferenceError as fallback_error:
                raise EODHDProviderError(
                    "EODHD symbol directory "
                    f"{query.provider_symbol} returned HTTP {error.status_code} and the "
                    "independent Twelve Data reference fallback is unavailable: "
                    f"{fallback_error}"
                ) from fallback_error

        delisted_directory: list[Any] = []
        provider_symbol = query.provider_symbol.strip().upper()
        if provider_symbol not in _base._ACTIVE_ONLY_SYMBOL_DIRECTORIES:
            try:
                raw_delisted = self._request(
                    f"/exchange-symbol-list/{provider_symbol}",
                    params={"delisted": 1},
                    resource=f"delisted symbol directory {provider_symbol}",
                    timeout=max(
                        self.timeout,
                        _base._DIRECTORY_REQUEST_TIMEOUT_SECONDS,
                    ),
                )
                if not isinstance(raw_delisted, list):
                    raise EODHDRetrievalFailure(
                        resource=f"delisted symbol directory {provider_symbol}",
                        category="invalid_payload_shape",
                        retryable=True,
                    )
            except EODHDRetrievalFailure as error:
                if not (
                    error.retryable
                    or error.status_code in _DIRECTORY_CONTINUITY_STATUS_CODES
                ):
                    raise
                directory_limitations = (
                    *directory_limitations,
                    "The active symbol directory remains available, but the live "
                    "delisted-symbol directory was unavailable.",
                    str(error),
                    "Historical delisting and identifier lineage remain fail-closed "
                    "until separately certified evidence is available.",
                )
            else:
                delisted_directory = raw_delisted
        else:
            directory_limitations = (
                *directory_limitations,
                "provider virtual-market directory is active-only; a delisted "
                "request is not applicable",
            )

        payload = self._bounded_payload(
            {
                "active": active_directory,
                "delisted": delisted_directory,
            },
            query.limit,
        )
        available_at = cached_at or retrieved_at
        observed_at = cached_at or self._payload_observed_at(
            payload,
            fallback=available_at,
        )
        if observed_at > available_at:
            observed_at = available_at

        limitations = (
            "current and delisted symbol lists do not establish complete historical "
            "identifier lineage",
            "venue and symbol changes require a separately certified security-master "
            "history",
            *directory_limitations,
        )
        return ProviderDatasetSnapshot(
            query=snapshot_query,
            provider=self.name,
            source_version=_base.EODHD_SOURCE_VERSION,
            observed_at=observed_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            quality_state=quality_state,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload=payload,
            provider_record_id=(
                f"eodhd:{ProviderDatasetType.SYMBOL_DIRECTORY.value}:"
                f"{provider_symbol}:{retrieved_at.isoformat()}"
            ),
            limitations=tuple((*live_retrieval_limitations, *limitations)),
        )

    def _active_symbol_directory(
        self,
        provider_symbol: str,
        *,
        retrieved_at: datetime,
    ) -> tuple[list[Any], DataQualityState, datetime | None, tuple[str, ...]]:
        # Hot path: a recent integrity-checked cache is authoritative for discovery
        # continuity until its configured TTL expires. This prevents 19+ directory
        # downloads from being repeated during every exact-release CIO diagnostic.
        cached = self._load_directory_cache(
            provider_symbol,
            evaluated_at=retrieved_at,
        )
        if cached is not None:
            cached_at, payload = cached
            age_hours = (retrieved_at - cached_at).total_seconds() / 3600.0
            return (
                payload,
                DataQualityState.CACHED,
                cached_at,
                (
                    "using recent EODHD symbol-directory cache before live refresh; "
                    f"cache age={age_hours:.1f} hours",
                    "cache-first reference evidence cannot independently authorize "
                    "a no-superior-opportunity conclusion",
                ),
            )

        try:
            return super()._active_symbol_directory(
                provider_symbol,
                retrieved_at=retrieved_at,
            )
        except EODHDRetrievalFailure as error:
            if error.status_code not in _DIRECTORY_CONTINUITY_STATUS_CODES:
                raise
            cached = self._load_directory_cache(
                provider_symbol,
                evaluated_at=retrieved_at,
            )
            if cached is None:
                raise
            cached_at, payload = cached
            age_hours = (retrieved_at - cached_at).total_seconds() / 3600.0
            resource = f"active symbol directory {provider_symbol.strip().upper()}"
            return (
                payload,
                DataQualityState.CACHED,
                cached_at,
                (
                    f"live {resource} returned HTTP {error.status_code}; using the last "
                    f"successful directory cached {age_hours:.1f} hours earlier",
                    str(error),
                    "cached directory evidence cannot independently authorize a "
                    "no-superior-opportunity conclusion",
                ),
            )


def build_eodhd_provider() -> EODHDProvider:
    """Deployment factory for the continuity-aware EODHD provider."""
    binding_path = os.getenv("CAPITAL_INTELLIGENCE_EODHD_BINDINGS")
    registry = (
        EODHDBindingRegistry(())
        if not binding_path
        else load_eodhd_bindings(Path(binding_path))
    )
    return EODHDProvider(bindings=registry)


__all__ = [
    "EODHDBindingRegistry",
    "EODHDInstrumentBinding",
    "EODHDProvider",
    "EODHDProviderError",
    "EODHDRetrievalFailure",
    "EODHDRetrievalPolicy",
    "build_eodhd_provider",
    "load_eodhd_bindings",
]
