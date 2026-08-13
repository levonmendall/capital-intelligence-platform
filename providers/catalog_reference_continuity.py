"""Governed continuity for slow-moving independent reference catalogs.

Normal Twelve Data reference snapshots retain their existing short hot-cache window.
When and only when the live provider exhausts bounded HTTP 429 retries, an older
integrity-checked snapshot may be reused inside a separate explicit continuity window.
All existing payload, source-version, market-identity, query-limit, timestamp, and hash
validation remains authoritative. This module changes reference availability only; it
has no selection, sizing, construction, execution, or no-superior-opportunity authority.
"""

from __future__ import annotations

import os
from dataclasses import replace
from threading import Lock
from typing import Any, Mapping

from data.observation import DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers import twelve_data_reference_rate_limited as _base
from providers.twelve_data_reference import TwelveDataReferenceError


_DEFAULT_CONTINUITY_MAX_AGE_SECONDS = 2_592_000.0  # 30 days
_CONTINUITY_MAX_AGE_ENV = (
    "CAPITAL_INTELLIGENCE_TWELVE_DATA_REFERENCE_CONTINUITY_MAX_AGE_SECONDS"
)


def _status_code(response: Any) -> int | None:
    try:
        return int(getattr(response, "status_code", 0))
    except (TypeError, ValueError):
        return None


class TwelveDataCatalogContinuityProvider(
    _base.TwelveDataRateLimitedReferenceProvider
):
    """Permit validated stale reference reuse only after bounded live throttling."""

    def __init__(
        self,
        *args: Any,
        continuity_max_age_seconds: float = _DEFAULT_CONTINUITY_MAX_AGE_SECONDS,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        continuity_age = float(continuity_max_age_seconds)
        if continuity_age < self.cache_max_age_seconds:
            raise ValueError(
                "continuity_max_age_seconds cannot be shorter than cache_max_age_seconds"
            )
        if continuity_age > _DEFAULT_CONTINUITY_MAX_AGE_SECONDS:
            raise ValueError(
                "continuity_max_age_seconds cannot exceed the governed 30-day maximum"
            )
        self.continuity_max_age_seconds = continuity_age
        self._live_rate_limit_exhausted = False
        self._continuity_state_lock = Lock()

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        """Keep the normal cache path, then use stale continuity only on final 429."""

        if query.dataset_type is not ProviderDatasetType.SYMBOL_DIRECTORY:
            return super().fetch_dataset(query)

        with self._continuity_state_lock:
            self._live_rate_limit_exhausted = False
            try:
                return super().fetch_dataset(query)
            except TwelveDataReferenceError as live_error:
                if not self._live_rate_limit_exhausted:
                    raise

                try:
                    snapshot = self._load_continuity_cached_snapshot(query)
                except TwelveDataReferenceError as continuity_error:
                    raise TwelveDataReferenceError(
                        f"{live_error}; governed stale-on-429 reference continuity "
                        f"unavailable: {continuity_error}"
                    ) from live_error
                return replace(
                    snapshot,
                    quality_state=DataQualityState.CACHED,
                    limitations=tuple(snapshot.limitations)
                    + (
                        "live Twelve Data reference access exhausted bounded HTTP 429 "
                        "retries; an integrity-checked catalog outside the normal freshness "
                        "window was reused inside the governed 30-day continuity window",
                        "stale-on-429 reference continuity preserves discovery identity "
                        "only and cannot authorize selection, sizing, construction, "
                        "execution, or a no-superior-opportunity conclusion",
                    ),
                )

    def _load_continuity_cached_snapshot(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        """Reuse the parent's full cache validation with only a wider age boundary."""

        with self._catalog_lock:
            normal_age = self.cache_max_age_seconds
            self.cache_max_age_seconds = self.continuity_max_age_seconds
            try:
                return super()._load_cached_snapshot(query)
            finally:
                self.cache_max_age_seconds = normal_age

    def _rate_limited_get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        timeout: int,
    ) -> Any:
        response = super()._rate_limited_get(
            url,
            params=params,
            timeout=timeout,
        )
        if _status_code(response) == 429:
            self._live_rate_limit_exhausted = True
        return response


def build_catalog_reference_continuity_provider(
) -> TwelveDataCatalogContinuityProvider:
    """Build production reference continuity without changing the normal hot TTL."""

    raw_interval = os.getenv(
        _base._PRODUCTION_INTERVAL_ENV,
        str(_base._DEFAULT_PRODUCTION_REQUEST_INTERVAL_SECONDS),
    )
    raw_cache_age = os.getenv(
        _base._CACHE_MAX_AGE_ENV,
        str(_base._DEFAULT_CACHE_MAX_AGE_SECONDS),
    )
    raw_continuity_age = os.getenv(
        _CONTINUITY_MAX_AGE_ENV,
        str(_DEFAULT_CONTINUITY_MAX_AGE_SECONDS),
    )
    try:
        minimum_interval = float(raw_interval)
    except ValueError as error:
        raise ValueError(
            f"{_base._PRODUCTION_INTERVAL_ENV} must be numeric"
        ) from error
    try:
        cache_max_age = float(raw_cache_age)
    except ValueError as error:
        raise ValueError(
            f"{_base._CACHE_MAX_AGE_ENV} must be numeric"
        ) from error
    try:
        continuity_max_age = float(raw_continuity_age)
    except ValueError as error:
        raise ValueError(
            f"{_CONTINUITY_MAX_AGE_ENV} must be numeric"
        ) from error

    return TwelveDataCatalogContinuityProvider(
        minimum_request_interval_seconds=minimum_interval,
        cache_directory=os.getenv(_base._CACHE_DIRECTORY_ENV),
        cache_max_age_seconds=cache_max_age,
        continuity_max_age_seconds=continuity_max_age,
    )


__all__ = [
    "TwelveDataCatalogContinuityProvider",
    "build_catalog_reference_continuity_provider",
]
