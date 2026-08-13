"""EODHD provider facade with cache-first symbol-directory continuity.

The implementation remains in :mod:`providers.eodhd_base`. This facade makes a valid
recent EODHD directory cache the normal hot path so all-market certification does not
re-download every exchange directory on every CIO cycle. When a cache is absent/stale,
live EODHD retrieval remains authoritative; bounded continuity rules then apply exactly
as before.

Physical exchange codes are reconciled once per provider instance against EODHD's
exchange directory before spending a symbol-directory request. A configured market that
is not advertised by EODHD is preserved and routed to the independent reference
provider; provider aliases are never guessed and market scope is never silently reduced.

A current active directory is not discarded solely because the historical delisted-
symbol directory is temporarily unavailable. Missing or incomplete fallback evidence,
authentication failures, provider errors other than the explicitly governed continuity
conditions, virtual markets without a certified reference selector, and every
non-directory provider failure remain fail-closed.
"""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers import eodhd_base as _base
from providers.catalog_reference_continuity import (
    build_catalog_reference_continuity_provider,
)
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


_DIRECTORY_CONTINUITY_STATUS_CODES = frozenset({402, 404})
_PHYSICAL_EXCHANGE_DIRECTORY_QUERY_SYMBOL = "ALL"
_EXCHANGE_DIRECTORY_LIMIT = 10_000


def __getattr__(name: str):
    """Preserve compatibility for non-exported constants and helpers."""
    try:
        return getattr(_base, name)
    except AttributeError as error:
        raise AttributeError(
            f"module 'providers.eodhd' has no attribute {name!r}"
        ) from error


def _exchange_directory_codes(payload: object) -> frozenset[str] | None:
    """Return advertised exchange codes, or None when the payload is not certifiable."""

    rows: object = payload
    if isinstance(payload, Mapping):
        for key in ("data", "exchanges", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, Sequence) and not isinstance(
                candidate, (str, bytes)
            ):
                rows = candidate
                break
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return None

    codes: set[str] = set()
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        value = None
        for key in ("Code", "code", "ExchangeCode", "exchange_code"):
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.strip():
                value = candidate
                break
        if value is not None:
            codes.add(value.strip().upper())
    return frozenset(codes) if codes else None


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
        self._exchange_directory_checked = False
        self._advertised_physical_exchange_codes: frozenset[str] | None = None

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        if query.dataset_type is not ProviderDatasetType.SYMBOL_DIRECTORY:
            return super().fetch_dataset(query)

        retrieved_at = self._now()
        provider_symbol = query.provider_symbol.strip().upper()

        # A recent integrity-checked symbol cache is already governed continuity
        # evidence. Do not spend an exchange-directory request merely to rediscover
        # that a cached market existed.
        cached = self._load_directory_cache(
            provider_symbol,
            evaluated_at=retrieved_at,
        )
        if (
            cached is None
            and provider_symbol not in _base._ACTIVE_ONLY_SYMBOL_DIRECTORIES
        ):
            advertised = self._physical_exchange_codes(
                as_of=query.as_of,
            )
            if advertised is not None and provider_symbol not in advertised:
                return self._reference_fallback(
                    query,
                    reason=(
                        f"configured physical market {provider_symbol} is not "
                        "advertised by the current EODHD exchange directory"
                    ),
                )

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
                provider_symbol,
                retrieved_at=retrieved_at,
            )
        except EODHDRetrievalFailure as error:
            if error.status_code not in _DIRECTORY_CONTINUITY_STATUS_CODES:
                raise
            return self._reference_fallback(
                query,
                status_code=error.status_code,
            )

        delisted_directory: list[Any] = []
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

    def _physical_exchange_codes(
        self,
        *,
        as_of: datetime,
    ) -> frozenset[str] | None:
        """Fetch the EODHD exchange directory once without creating a new hard gate."""

        if self._exchange_directory_checked:
            return self._advertised_physical_exchange_codes
        self._exchange_directory_checked = True
        try:
            snapshot = super().fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.EXCHANGE_DIRECTORY,
                    provider_symbol=_PHYSICAL_EXCHANGE_DIRECTORY_QUERY_SYMBOL,
                    as_of=as_of,
                    limit=_EXCHANGE_DIRECTORY_LIMIT,
                )
            )
        except (EODHDProviderError, EODHDRetrievalFailure):
            # Exchange-directory preflight is an efficiency/reconciliation aid.
            # If it is unavailable, preserve the prior direct symbol-directory path,
            # whose own continuity and fail-closed controls remain authoritative.
            self._advertised_physical_exchange_codes = None
            return None

        self._advertised_physical_exchange_codes = _exchange_directory_codes(
            snapshot.payload
        )
        return self._advertised_physical_exchange_codes

    def _reference_fallback(
        self,
        query: ProviderDatasetQuery,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> ProviderDatasetSnapshot:
        fallback = self._reference_provider
        if fallback is None:
            fallback = build_catalog_reference_continuity_provider()
            self._reference_provider = fallback
        try:
            snapshot = fallback.fetch_dataset(query)
        except TwelveDataReferenceError as fallback_error:
            if status_code is not None:
                origin = (
                    f"EODHD symbol directory {query.provider_symbol} returned "
                    f"HTTP {status_code}"
                )
            else:
                origin = reason or (
                    f"EODHD symbol directory {query.provider_symbol} is unavailable"
                )
            raise EODHDProviderError(
                f"{origin} and the independent Twelve Data reference fallback is "
                f"unavailable: {fallback_error}"
            ) from fallback_error

        if reason is None:
            return snapshot
        return replace(
            snapshot,
            limitations=tuple(snapshot.limitations)
            + (
                reason + "; the configured market was preserved through an "
                "independent reference catalog rather than removed or remapped",
                "exchange-directory reconciliation and reference fallback have "
                "discovery identity authority only and cannot authorize selection, "
                "sizing, construction, execution, or a no-superior-opportunity "
                "conclusion",
            ),
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
