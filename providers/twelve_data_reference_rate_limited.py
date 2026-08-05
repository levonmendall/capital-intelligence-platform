"""Bounded Twelve Data continuity for production discovery.

The production reference provider serializes and paces live requests, boundedly retries
HTTP 429 responses, and persists only fully validated provider snapshots. A recent cache
is checked before any live request so repeated all-market discovery runs do not consume
the same reference-catalog credits again. Cache reuse remains discovery-only and
fail-closed: malformed, stale, mismatched, oversized, source-version-incompatible, or
integrity-invalid records are rejected.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
from typing import Any

import requests

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.twelve_data_reference import TwelveDataReferenceError
from providers.twelve_data_reference_runtime import (
    TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION,
    TwelveDataRuntimeReferenceProvider,
)


_DEFAULT_RATE_LIMIT_RETRIES = 2
_DEFAULT_MAX_RATE_LIMIT_WAIT_SECONDS = 65.0
_DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS = 0.0
_DEFAULT_PRODUCTION_REQUEST_INTERVAL_SECONDS = 8.0
_DEFAULT_CACHE_MAX_AGE_SECONDS = 259_200.0
_LIVE_QUERY_GRACE = timedelta(minutes=5)
_PRODUCTION_INTERVAL_ENV = (
    "CAPITAL_INTELLIGENCE_TWELVE_DATA_MINIMUM_REQUEST_INTERVAL_SECONDS"
)
_CACHE_DIRECTORY_ENV = "CAPITAL_INTELLIGENCE_TWELVE_DATA_REFERENCE_CACHE_DIRECTORY"
_CACHE_MAX_AGE_ENV = "CAPITAL_INTELLIGENCE_TWELVE_DATA_REFERENCE_CACHE_MAX_AGE_SECONDS"
_CACHE_SCHEMA_VERSION = "twelve-data-reference-cache.v2"


def _response_status_code(response: Any) -> int | None:
    try:
        return int(getattr(response, "status_code", 0))
    except (TypeError, ValueError):
        return None


def _response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            text = str(value).strip()
            return text or None
    return None


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TwelveDataReferenceError(f"cached {field_name} is missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise TwelveDataReferenceError(
            f"cached {field_name} is invalid"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TwelveDataReferenceError(
            f"cached {field_name} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def _payload_hash(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise TwelveDataReferenceError(
            "cached Twelve Data payload is not finite JSON"
        ) from error
    return hashlib.sha256(encoded).hexdigest()


def _default_cache_directory() -> Path:
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database"))
    return data_dir / "provider_cache" / "twelve_data_reference"


class TwelveDataRateLimitedReferenceProvider(TwelveDataRuntimeReferenceProvider):
    """Serialize, pace, cache, and boundedly retry reference requests."""

    def __init__(
        self,
        *args: Any,
        http_get: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        max_rate_limit_retries: int = _DEFAULT_RATE_LIMIT_RETRIES,
        max_rate_limit_wait_seconds: float = _DEFAULT_MAX_RATE_LIMIT_WAIT_SECONDS,
        minimum_request_interval_seconds: float = (
            _DEFAULT_MINIMUM_REQUEST_INTERVAL_SECONDS
        ),
        cache_directory: str | Path | None = None,
        cache_max_age_seconds: float = _DEFAULT_CACHE_MAX_AGE_SECONDS,
        **kwargs: Any,
    ) -> None:
        retries = int(max_rate_limit_retries)
        maximum_wait = float(max_rate_limit_wait_seconds)
        minimum_interval = float(minimum_request_interval_seconds)
        maximum_cache_age = float(cache_max_age_seconds)
        if retries < 0:
            raise ValueError("max_rate_limit_retries must be non-negative")
        if not 1.0 <= maximum_wait <= 300.0:
            raise ValueError(
                "max_rate_limit_wait_seconds must be between 1 and 300"
            )
        if not 0.0 <= minimum_interval <= 60.0:
            raise ValueError(
                "minimum_request_interval_seconds must be between 0 and 60"
            )
        if not 60.0 <= maximum_cache_age <= 2_592_000.0:
            raise ValueError(
                "cache_max_age_seconds must be between 60 and 2592000"
            )

        configured_cache_directory = (
            cache_directory
            or os.getenv(_CACHE_DIRECTORY_ENV)
            or _default_cache_directory()
        )
        self._raw_http_get = http_get or requests.get
        self._sleeper = sleeper or time.sleep
        self._monotonic = monotonic or time.monotonic
        self.max_rate_limit_retries = retries
        self.max_rate_limit_wait_seconds = maximum_wait
        self.minimum_request_interval_seconds = minimum_interval
        self.cache_directory = Path(configured_cache_directory).expanduser()
        self.cache_max_age_seconds = maximum_cache_age
        self._request_lock = Lock()
        self._cache_lock = Lock()
        self._catalog_lock = Lock()
        self._pause_before_next_request = False
        self._last_request_started_at: float | None = None
        super().__init__(*args, http_get=self._rate_limited_get, **kwargs)

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        """Reuse a valid snapshot before spending provider credits."""

        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        if query.dataset_type is not ProviderDatasetType.SYMBOL_DIRECTORY:
            return super().fetch_dataset(query)

        with self._catalog_lock:
            cache_error: TwelveDataReferenceError | None = None
            try:
                return self._load_cached_snapshot(query)
            except TwelveDataReferenceError as error:
                cache_error = error

            try:
                snapshot = super().fetch_dataset(query)
            except TwelveDataReferenceError as live_error:
                raise TwelveDataReferenceError(
                    f"{live_error}; validated reference cache unavailable: "
                    f"{cache_error}"
                ) from live_error

            self._store_cached_snapshot(snapshot)
            return snapshot

    def _cache_path(self, query: ProviderDatasetQuery) -> Path:
        identity = (
            f"{query.dataset_type.value}:{query.provider_symbol}:{query.limit}"
        ).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()
        return self.cache_directory / f"{digest}.json"

    def _store_cached_snapshot(self, snapshot: ProviderDatasetSnapshot) -> None:
        snapshot_record = snapshot.to_dict()
        envelope = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "cached_at": self._now().isoformat(),
            "query_limit": snapshot.query.limit,
            "snapshot": snapshot_record,
            "snapshot_hash": _payload_hash(snapshot_record),
        }
        path = self._cache_path(snapshot.query)
        temporary = path.with_suffix(".tmp")
        with self._cache_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_text(
                    json.dumps(
                        envelope,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                    encoding="utf-8",
                )
                temporary.replace(path)
            except OSError:
                # Cache persistence cannot invalidate a certified live response.
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_cached_snapshot(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        path = self._cache_path(query)
        with self._cache_lock:
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as error:
                raise TwelveDataReferenceError("no cached catalog exists") from error
            except (OSError, json.JSONDecodeError) as error:
                raise TwelveDataReferenceError(
                    "cached catalog cannot be read"
                ) from error

        if not isinstance(envelope, Mapping):
            raise TwelveDataReferenceError("cached catalog envelope must be an object")
        if envelope.get("schema_version") != _CACHE_SCHEMA_VERSION:
            raise TwelveDataReferenceError("cached catalog schema is unsupported")

        cached_at = _aware_datetime(
            envelope.get("cached_at"),
            field_name="cached_at",
        )
        age = self._now() - cached_at
        if age < timedelta(0):
            raise TwelveDataReferenceError("cached catalog timestamp is in the future")
        if age > timedelta(seconds=self.cache_max_age_seconds):
            raise TwelveDataReferenceError("cached catalog is expired")

        snapshot_data = envelope.get("snapshot")
        if not isinstance(snapshot_data, Mapping):
            raise TwelveDataReferenceError("cached snapshot must be an object")
        expected_snapshot_hash = envelope.get("snapshot_hash")
        if (
            not isinstance(expected_snapshot_hash, str)
            or _payload_hash(snapshot_data) != expected_snapshot_hash
        ):
            raise TwelveDataReferenceError(
                "cached snapshot integrity check failed"
            )

        if snapshot_data.get("dataset_type") != query.dataset_type.value:
            raise TwelveDataReferenceError("cached dataset type does not match")
        if (
            str(snapshot_data.get("provider_symbol", "")).upper()
            != query.provider_symbol
        ):
            raise TwelveDataReferenceError("cached provider symbol does not match")
        if snapshot_data.get("provider") != self.name:
            raise TwelveDataReferenceError("cached provider identity does not match")
        if (
            snapshot_data.get("source_version")
            != TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION
        ):
            raise TwelveDataReferenceError(
                "cached source version does not match the active adapter"
            )

        cached_limit = envelope.get("query_limit")
        if isinstance(cached_limit, bool) or not isinstance(cached_limit, int):
            raise TwelveDataReferenceError("cached query limit is invalid")
        if cached_limit != query.limit:
            raise TwelveDataReferenceError("cached query limit does not match")

        payload = snapshot_data.get("payload")
        expected_hash = snapshot_data.get("content_hash")
        if (
            not isinstance(expected_hash, str)
            or _payload_hash(payload) != expected_hash
        ):
            raise TwelveDataReferenceError("cached payload integrity check failed")
        if not isinstance(payload, Mapping):
            raise TwelveDataReferenceError(
                "cached symbol directory must be an object"
            )
        self._validate_cached_payload(payload, query)

        observed_at = _aware_datetime(
            snapshot_data.get("observed_at"),
            field_name="observed_at",
        )
        available_at = _aware_datetime(
            snapshot_data.get("available_at"),
            field_name="available_at",
        )
        retrieved_at = _aware_datetime(
            snapshot_data.get("retrieved_at"),
            field_name="retrieved_at",
        )
        if not observed_at <= available_at <= retrieved_at <= cached_at:
            raise TwelveDataReferenceError(
                "cached catalog timestamps are inconsistent"
            )

        snapshot_query = query
        if available_at > query.as_of:
            delay = available_at - query.as_of
            if delay > _LIVE_QUERY_GRACE:
                raise TwelveDataReferenceError(
                    "cached catalog was not available at the requested as-of time"
                )
            snapshot_query = replace(query, as_of=available_at)

        limitations_value = snapshot_data.get("limitations", [])
        if not isinstance(limitations_value, list) or not all(
            isinstance(item, str) and item.strip() for item in limitations_value
        ):
            raise TwelveDataReferenceError("cached limitations are invalid")

        provider_record_value = snapshot_data.get("provider_record_id")
        provider_record_id = None
        if provider_record_value is not None:
            provider_record_id = str(provider_record_value).strip()
            if not provider_record_id:
                raise TwelveDataReferenceError(
                    "cached provider record identity is invalid"
                )

        return ProviderDatasetSnapshot(
            query=snapshot_query,
            provider=self.name,
            source_version=TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION,
            observed_at=observed_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.CACHED,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload={
                "active": list(payload["active"]),
                "delisted": list(payload["delisted"]),
            },
            provider_record_id=provider_record_id,
            limitations=tuple(limitations_value)
            + (
                "A recent integrity-checked Twelve Data reference snapshot was reused "
                "before making another provider request.",
                "Cached reference data retains discovery-only authority and cannot "
                "authorize selection, sizing, construction, or execution.",
            ),
        )

    @staticmethod
    def _validate_cached_payload(
        payload: Mapping[str, Any],
        query: ProviderDatasetQuery,
    ) -> None:
        active = payload.get("active")
        delisted = payload.get("delisted")
        if not isinstance(active, Sequence) or isinstance(active, (str, bytes)):
            raise TwelveDataReferenceError(
                "cached active catalog is invalid"
            )
        if not active:
            raise TwelveDataReferenceError("cached active catalog is empty")
        if not isinstance(delisted, Sequence) or isinstance(
            delisted,
            (str, bytes),
        ):
            raise TwelveDataReferenceError(
                "cached delisted catalog is invalid"
            )
        if len(active) > query.limit:
            raise TwelveDataReferenceError(
                "cached catalog exceeds the query limit"
            )

        identities: set[tuple[str, str, str, str, str]] = set()
        for row in active:
            if not isinstance(row, Mapping):
                raise TwelveDataReferenceError(
                    "cached catalog contains a non-object row"
                )
            code = str(row.get("Code", "")).strip().upper()
            exchange = str(row.get("Exchange", "")).strip().upper()
            source = str(row.get("SourceProvider", "")).strip()
            if (
                not code
                or exchange != query.provider_symbol
                or source != "Twelve Data"
            ):
                raise TwelveDataReferenceError(
                    "cached catalog contains a row outside the requested market"
                )
            identity = (
                code,
                str(row.get("MIC", "")).strip().upper(),
                exchange,
                str(row.get("CountryISO2", "")).strip().upper(),
                str(row.get("Type", "")).strip(),
            )
            if identity in identities:
                raise TwelveDataReferenceError(
                    "cached catalog contains duplicate records"
                )
            identities.add(identity)

    def _rate_limited_get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        timeout: int,
    ) -> Any:
        with self._request_lock:
            if self._pause_before_next_request:
                self._sleeper(self._minute_reset_wait_seconds())
                self._pause_before_next_request = False

            response: Any = None
            for attempt in range(self.max_rate_limit_retries + 1):
                self._pace_next_request()
                self._last_request_started_at = self._monotonic()
                response = self._raw_http_get(
                    url,
                    params=params,
                    timeout=timeout,
                )
                if _response_status_code(response) != 429:
                    if self._credits_left(response) == 0:
                        self._pause_before_next_request = True
                    return response
                if attempt >= self.max_rate_limit_retries:
                    return response
                self._sleeper(self._rate_limit_wait_seconds(response))
            return response

    def _pace_next_request(self) -> None:
        last_started_at = self._last_request_started_at
        if last_started_at is None or self.minimum_request_interval_seconds <= 0.0:
            return
        elapsed = max(0.0, self._monotonic() - last_started_at)
        remaining = self.minimum_request_interval_seconds - elapsed
        if remaining > 0.0:
            self._sleeper(remaining)

    def _rate_limit_wait_seconds(self, response: Any) -> float:
        retry_after = _response_header(response, "Retry-After")
        if retry_after is not None:
            parsed = self._parse_retry_after(retry_after)
            if parsed is not None:
                return min(
                    self.max_rate_limit_wait_seconds,
                    max(1.0, parsed),
                )
        return min(
            self.max_rate_limit_wait_seconds,
            self._minute_reset_wait_seconds(),
        )

    def _parse_retry_after(self, value: str) -> float | None:
        try:
            numeric = float(value)
        except ValueError:
            numeric = math.nan
        if math.isfinite(numeric):
            return numeric
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None or retry_at.utcoffset() is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (retry_at.astimezone(timezone.utc) - self._now()).total_seconds(),
        )

    def _minute_reset_wait_seconds(self) -> float:
        now = self._now()
        elapsed = now.second + (now.microsecond / 1_000_000.0)
        return max(
            1.0,
            min(self.max_rate_limit_wait_seconds, 61.0 - elapsed),
        )

    @staticmethod
    def _credits_left(response: Any) -> int | None:
        value = _response_header(response, "api-credits-left")
        if value is None:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None


def build_twelve_data_rate_limited_reference_provider(
) -> TwelveDataRateLimitedReferenceProvider:
    """Build the production provider with bounded rate and cache continuity."""

    raw_interval = os.getenv(
        _PRODUCTION_INTERVAL_ENV,
        str(_DEFAULT_PRODUCTION_REQUEST_INTERVAL_SECONDS),
    )
    raw_cache_age = os.getenv(
        _CACHE_MAX_AGE_ENV,
        str(_DEFAULT_CACHE_MAX_AGE_SECONDS),
    )
    try:
        minimum_interval = float(raw_interval)
    except ValueError as error:
        raise ValueError(
            f"{_PRODUCTION_INTERVAL_ENV} must be numeric"
        ) from error
    try:
        cache_max_age = float(raw_cache_age)
    except ValueError as error:
        raise ValueError(f"{_CACHE_MAX_AGE_ENV} must be numeric") from error
    return TwelveDataRateLimitedReferenceProvider(
        minimum_request_interval_seconds=minimum_interval,
        cache_directory=os.getenv(_CACHE_DIRECTORY_ENV),
        cache_max_age_seconds=cache_max_age,
    )


__all__ = [
    "TwelveDataRateLimitedReferenceProvider",
    "build_twelve_data_rate_limited_reference_provider",
]
