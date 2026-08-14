"""Governed Massive futures-reference adapter for constrained provider plans.

This adapter changes only reference-data acquisition. It preserves exact point-in-time
contract identity and complete configured-root coverage while preventing a broad futures
directory crawl from exhausting the provider call budget. It has no investment,
construction, execution, or real-money authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from providers.massive_multi_asset import (
    MASSIVE_BASE_URL,
    MassiveFuturesContract,
    MassiveMultiAssetError,
    MassiveMultiAssetProvider,
)


_DEFAULT_MINIMUM_CALL_INTERVAL_SECONDS = 12.5
_DEFAULT_RATE_LIMIT_RETRY_SECONDS = 60.0
_DEFAULT_REFERENCE_MAX_ATTEMPTS = 4


class MassiveFuturesReferenceProvider(MassiveMultiAssetProvider):
    """Retrieve exact dated contracts with root-scoped, rate-budgeted requests."""

    def __init__(
        self,
        *args: object,
        minimum_call_interval_seconds: float = _DEFAULT_MINIMUM_CALL_INTERVAL_SECONDS,
        rate_limit_retry_seconds: float = _DEFAULT_RATE_LIMIT_RETRY_SECONDS,
        reference_max_attempts: int = _DEFAULT_REFERENCE_MAX_ATTEMPTS,
        **kwargs: object,
    ) -> None:
        if isinstance(minimum_call_interval_seconds, bool) or not isinstance(
            minimum_call_interval_seconds, (int, float)
        ):
            raise TypeError("minimum_call_interval_seconds must be numeric")
        if not 0.0 <= float(minimum_call_interval_seconds) <= 60.0:
            raise ValueError("minimum_call_interval_seconds must be between 0 and 60")
        if isinstance(rate_limit_retry_seconds, bool) or not isinstance(
            rate_limit_retry_seconds, (int, float)
        ):
            raise TypeError("rate_limit_retry_seconds must be numeric")
        if not 0.0 <= float(rate_limit_retry_seconds) <= 120.0:
            raise ValueError("rate_limit_retry_seconds must be between 0 and 120")
        if isinstance(reference_max_attempts, bool) or not isinstance(
            reference_max_attempts, int
        ):
            raise TypeError("reference_max_attempts must be an integer")
        if not 1 <= reference_max_attempts <= 8:
            raise ValueError("reference_max_attempts must be between 1 and 8")

        # A reference request owns its retry schedule so an HTTP 429 does not receive
        # several short retries inside the same provider rate-limit window.
        kwargs = dict(kwargs)
        kwargs["max_attempts"] = 1
        super().__init__(*args, **kwargs)
        self.minimum_call_interval_seconds = float(minimum_call_interval_seconds)
        self.rate_limit_retry_seconds = float(rate_limit_retry_seconds)
        self.reference_max_attempts = reference_max_attempts

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
    ) -> Mapping[str, Any]:
        last_error: MassiveMultiAssetError | None = None
        for attempt in range(1, self.reference_max_attempts + 1):
            try:
                return super()._get_url(url, params=params)
            except MassiveMultiAssetError as error:
                last_error = error
                if not error.retryable or attempt >= self.reference_max_attempts:
                    raise
                if error.status_code == 429:
                    delay = self.rate_limit_retry_seconds
                else:
                    delay = min(30.0, 2.0 ** (attempt - 1))
                if delay > 0.0:
                    self._sleeper(delay)
        assert last_error is not None
        raise last_error

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        if not self.api_key:
            raise MassiveMultiAssetError("Massive API key is not configured")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if isinstance(maximum_pages, bool) or not isinstance(maximum_pages, int):
            raise TypeError("maximum_pages must be an integer")
        if maximum_pages < 1:
            raise ValueError("maximum_pages must be positive")

        target_codes = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        query_codes: tuple[str | None, ...] = target_codes or (None,)
        result: dict[str, MassiveFuturesContract] = {}
        request_count = 0
        reference_date = as_of.astimezone(timezone.utc).date().isoformat()

        for target_code in query_codes:
            url = f"{MASSIVE_BASE_URL}/futures/v1/contracts"
            params: dict[str, object] = {
                "date": reference_date,
                "active": "true",
                "limit": 1000,
                "apiKey": self.api_key,
            }
            if target_code is not None:
                params["product_code"] = target_code

            pagination_complete = False
            for _ in range(maximum_pages):
                if request_count and self.minimum_call_interval_seconds > 0.0:
                    self._sleeper(self.minimum_call_interval_seconds)
                payload = self._reference_get(url, params=params)
                request_count += 1
                raw = payload.get("results") if isinstance(payload, Mapping) else None
                if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                    raise MassiveMultiAssetError(
                        "Massive futures contract response is missing results"
                    )
                for item in raw:
                    if not isinstance(item, Mapping):
                        continue
                    ticker = str(item.get("ticker") or "").strip().upper()
                    product = str(item.get("product_code") or "").strip().upper()
                    venue = str(item.get("trading_venue") or "").strip().upper()
                    first = str(item.get("first_trade_date") or "").strip()
                    last = str(item.get("last_trade_date") or "").strip()
                    if not ticker or not product or not venue or not first or not last:
                        continue
                    if target_code is not None and product != target_code:
                        continue
                    raw_active = item.get("active", True)
                    active = (
                        raw_active.strip().lower() == "true"
                        if isinstance(raw_active, str)
                        else bool(raw_active)
                    )
                    result[ticker] = MassiveFuturesContract(
                        ticker=ticker,
                        product_code=product,
                        trading_venue=venue,
                        first_trade_date=first,
                        last_trade_date=last,
                        settlement_date=(
                            str(item.get("settlement_date")).strip()
                            if item.get("settlement_date")
                            else None
                        ),
                        active=active,
                        source_identifier=(
                            f"massive:futures-contract:{ticker}:{reference_date}"
                        ),
                    )

                next_url = (
                    str(payload.get("next_url") or "").strip()
                    if isinstance(payload, Mapping)
                    else ""
                )
                if not next_url:
                    pagination_complete = True
                    break
                parsed = urlparse(next_url)
                if parsed.scheme != "https" or parsed.netloc != "api.massive.com":
                    raise MassiveMultiAssetError(
                        "Massive futures pagination returned an invalid next_url"
                    )
                url = next_url
                params = {"apiKey": self.api_key}

            if not pagination_complete:
                subject = target_code or "all products"
                raise MassiveMultiAssetError(
                    "Massive futures contract pagination exceeded the completeness guard "
                    f"for {subject}"
                )

        return tuple(result[key] for key in sorted(result))


__all__ = ["MassiveFuturesReferenceProvider"]
