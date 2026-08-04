"""Production compatibility for Twelve Data exchange reference responses.

Twelve Data's ``/stocks`` reference endpoint may ignore ``outputsize`` and ``page`` for
an exchange-filtered request and return the complete filtered catalog in one response.
The base adapter intentionally assumes ordinary pagination.  This runtime adapter accepts
that observed reference-endpoint behavior only when the first response includes an exact
provider count matching the returned rows and remains within the explicit exchange memory
bound.  Ambiguous, incomplete, repeated, or oversized responses remain fail-closed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from data.provider_dataset import ProviderDatasetQuery, ProviderDatasetSnapshot
from providers.twelve_data_reference import (
    ExchangeSelector,
    TwelveDataReferenceError,
    TwelveDataReferenceProvider,
)


TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION = "twelve-data-stocks-reference.v3"


def _normalized_identity(item: Mapping[str, str]) -> tuple[str, str, str, str, str]:
    return (
        item["Code"],
        item["MIC"],
        item["Exchange"],
        item["CountryISO2"],
        item["Type"],
    )


class TwelveDataRuntimeReferenceProvider(TwelveDataReferenceProvider):
    """Accept count-certified complete exchange responses without global retention."""

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        snapshot = super().fetch_dataset(query)
        limitations = tuple(
            (
                "Exchange-scoped reference responses are accepted only when ordinary "
                "pagination completes or a single provider-count-certified response "
                "contains the complete requested exchange within the explicit memory "
                "bound."
            )
            if item.startswith("Raw pages were bounded to ")
            else item
            for item in snapshot.limitations
        )
        return replace(
            snapshot,
            source_version=TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION,
            limitations=limitations,
        )

    def _collect_filter(
        self,
        *,
        exchange: str,
        selector: ExchangeSelector,
        filter_name: str,
        filter_value: str,
        unique: dict[tuple[str, str, str, str, str], dict[str, str]],
        maximum: int,
    ) -> None:
        seen_pages: set[str] = set()
        reported_count: int | None = None
        raw_count = 0
        completed = False

        for page in range(1, self.max_pages + 1):
            payload = self._request_page(
                page,
                filter_name=filter_name,
                filter_value=filter_value,
            )
            status = str(payload.get("status", "ok")).strip().lower()
            if status not in {"ok", "success"}:
                raise TwelveDataReferenceError(
                    "Twelve Data stock catalog returned a provider rejection"
                )
            data = payload.get("data")
            if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
                raise TwelveDataReferenceError(
                    "Twelve Data stock catalog data must be an array"
                )
            page_rows = tuple(item for item in data if isinstance(item, Mapping))
            if len(page_rows) != len(data):
                raise TwelveDataReferenceError(
                    "Twelve Data stock catalog contains a non-object record"
                )

            if page == 1:
                value = payload.get("count")
                try:
                    reported_count = int(value)
                except (TypeError, ValueError):
                    reported_count = None
                if reported_count is not None and reported_count < 0:
                    raise TwelveDataReferenceError(
                        "Twelve Data stock catalog reported an invalid count"
                    )

            if not page_rows:
                completed = True
                break

            unpaginated_complete_response = len(page_rows) > self.page_size
            if unpaginated_complete_response:
                if page != 1:
                    raise TwelveDataReferenceError(
                        "Twelve Data stock catalog returned an oversized response after "
                        "pagination had already started"
                    )
                if reported_count is None:
                    raise TwelveDataReferenceError(
                        "Twelve Data stock catalog ignored the requested page size "
                        "without an exact provider count"
                    )
                if reported_count != len(page_rows):
                    raise TwelveDataReferenceError(
                        "Twelve Data unpaginated stock catalog row count did not match "
                        "the provider-reported count"
                    )
                if len(page_rows) > maximum:
                    raise TwelveDataReferenceError(
                        f"Twelve Data directory {exchange} exceeded the explicit "
                        f"{maximum}-record memory safety bound"
                    )

            page_fingerprint = self._page_fingerprint(page_rows)
            if page_fingerprint in seen_pages:
                raise TwelveDataReferenceError(
                    "Twelve Data stock catalog pagination repeated a prior page"
                )
            seen_pages.add(page_fingerprint)
            raw_count += len(page_rows)

            for item in page_rows:
                if not self._matches_filter(
                    item,
                    selector=selector,
                    filter_name=filter_name,
                    filter_value=filter_value,
                ):
                    raise TwelveDataReferenceError(
                        "Twelve Data stock catalog returned a record outside the "
                        "requested exchange filter"
                    )
                normalized = self._normalized_directory_row(
                    item,
                    exchange=exchange,
                    selector=selector,
                )
                unique.setdefault(_normalized_identity(normalized), normalized)
                if len(unique) > maximum:
                    raise TwelveDataReferenceError(
                        f"Twelve Data directory {exchange} exceeded the explicit "
                        f"{maximum}-record memory safety bound"
                    )

            if unpaginated_complete_response:
                completed = True
                break
            if reported_count is not None and raw_count >= reported_count:
                completed = True
                break
            if len(page_rows) < self.page_size:
                completed = True
                break

        if not completed:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog exceeded the certified pagination bound"
            )
        if reported_count is not None and raw_count < reported_count:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog pagination ended before the reported count"
            )
        if reported_count is not None and raw_count > reported_count:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog returned more records than the reported count"
            )


def build_twelve_data_runtime_reference_provider() -> TwelveDataRuntimeReferenceProvider:
    """Build the production compatibility provider from normalized environment keys."""

    return TwelveDataRuntimeReferenceProvider()


__all__ = [
    "TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION",
    "TwelveDataRuntimeReferenceProvider",
    "build_twelve_data_runtime_reference_provider",
]
