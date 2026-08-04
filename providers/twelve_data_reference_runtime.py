"""Production compatibility for Twelve Data reference responses.

Twelve Data's ``/stocks`` reference endpoint may ignore ``outputsize`` and ``page`` for
an exchange-filtered request and return the complete filtered catalog in one response.
The base adapter intentionally assumes ordinary pagination. This runtime adapter accepts
that observed reference-endpoint behavior only when the first response includes an exact
provider count matching the returned rows and remains within the explicit exchange memory
bound.

The runtime adapter also certifies Twelve Data's dedicated ``/forex_pairs`` endpoint as
an independent current foreign-exchange directory when EODHD cannot supply its virtual
``FOREX`` symbol directory. Forex responses are accepted only when the provider supplies
an exact count matching a non-empty, unique, structurally valid pair catalog within the
explicit memory bound. Twelve Data may return the base and quote fields as descriptive
currency names rather than ISO codes, so pair identity is governed by the canonical
``AAA/BBB`` symbol while non-empty component metadata remains required. Ambiguous,
incomplete, duplicated, or oversized responses remain fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import requests

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.twelve_data_reference import (
    TWELVE_DATA_API_BASE,
    ExchangeSelector,
    TwelveDataReferenceError,
    TwelveDataReferenceProvider,
)


TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION = "twelve-data-reference.v5-forex-components"
_FOREX_EXCHANGE = "FOREX"
_FOREX_SYMBOL = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")
_FOREX_CODE_COMPONENT = re.compile(r"^[A-Z]{3}$")


def _normalized_identity(item: Mapping[str, str]) -> tuple[str, str, str, str, str]:
    return (
        item["Code"],
        item["MIC"],
        item["Exchange"],
        item["CountryISO2"],
        item["Type"],
    )


class TwelveDataRuntimeReferenceProvider(TwelveDataReferenceProvider):
    """Accept count-certified complete stock and forex reference responses."""

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        exchange = query.provider_symbol.strip().upper()
        if (
            query.dataset_type is ProviderDatasetType.SYMBOL_DIRECTORY
            and exchange == _FOREX_EXCHANGE
        ):
            return self._fetch_forex_dataset(query)

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

    def _fetch_forex_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        if not self.api_key:
            raise TwelveDataReferenceError(
                "TWELVE_API_KEY or TWELVE_DATA_API_KEY is not configured"
            )
        payload = self._request_forex_catalog()
        status = str(payload.get("status", "ok")).strip().lower()
        if status not in {"ok", "success"}:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog returned a provider rejection"
            )
        data = payload.get("data")
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog data must be an array"
            )
        rows = tuple(item for item in data if isinstance(item, Mapping))
        if len(rows) != len(data):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog contains a non-object record"
            )
        try:
            reported_count = int(payload.get("count"))
        except (TypeError, ValueError) as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog requires an exact provider count"
            ) from error
        if reported_count < 1:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog reported an empty or invalid count"
            )
        if reported_count != len(rows):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog row count did not match the provider count"
            )
        maximum = min(query.limit, self.max_records)
        if len(rows) > maximum:
            raise TwelveDataReferenceError(
                f"Twelve Data directory FOREX exceeded the explicit {maximum}-record "
                "memory safety bound"
            )

        normalized: dict[str, dict[str, str]] = {}
        for item in rows:
            row = self._normalized_forex_row(item)
            symbol = row["Code"]
            if symbol in normalized:
                raise TwelveDataReferenceError(
                    f"Twelve Data forex catalog contains duplicate pair {symbol}"
                )
            normalized[symbol] = row
        if not normalized:
            raise TwelveDataReferenceError(
                "Twelve Data returned no certified current records for FOREX"
            )

        retrieved_at = self._now()
        snapshot_query = query
        if retrieved_at > query.as_of:
            delay_seconds = (retrieved_at - query.as_of).total_seconds()
            if delay_seconds > 300:
                raise TwelveDataReferenceError(
                    "Twelve Data catalog completed outside the live query grace window"
                )
            snapshot_query = replace(query, as_of=retrieved_at)

        ordered = tuple(normalized[symbol] for symbol in sorted(normalized))
        fingerprint = hashlib.sha256()
        for item in ordered:
            fingerprint.update(
                json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
            fingerprint.update(b"\n")
        return ProviderDatasetSnapshot(
            query=snapshot_query,
            provider=self.name,
            source_version=TWELVE_DATA_RUNTIME_REFERENCE_SOURCE_VERSION,
            observed_at=retrieved_at,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.FALLBACK,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload={"active": list(ordered), "delisted": []},
            provider_record_id=(
                "twelve-data:forex-reference:FOREX:"
                + fingerprint.hexdigest()
            ),
            limitations=(
                "Twelve Data's daily current forex-pair catalog was used as an "
                "independent reference fallback after EODHD directory failure.",
                "The provider-reported count exactly matched the complete response; "
                "pair symbols passed ISO-style structural and duplicate validation, "
                "component metadata was non-empty, and code-valued components were "
                "cross-checked against the pair symbol.",
                "The fallback catalog is current-only and does not certify historical "
                "pair availability or identifier-change lineage.",
                "Reference-catalog fallback has discovery authority only and cannot "
                "authorize a candidate, decision, size, construction, or execution.",
            ),
        )

    def _request_forex_catalog(self) -> Mapping[str, Any]:
        try:
            response = self._http_get(
                TWELVE_DATA_API_BASE + "/forex_pairs",
                params={"apikey": self.api_key, "format": "JSON"},
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog request timed out"
            ) from error
        except requests.ConnectionError as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog connection failed"
            ) from error
        except requests.RequestException as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog request failed"
            ) from error
        try:
            status_code = int(getattr(response, "status_code", 0))
        except (TypeError, ValueError) as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog returned an invalid HTTP response"
            ) from error
        if status_code < 200 or status_code >= 300:
            raise TwelveDataReferenceError(
                f"Twelve Data forex catalog returned HTTP {status_code}"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog returned invalid JSON"
            ) from error
        if not isinstance(payload, Mapping):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog response must be an object"
            )
        if payload.get("code") or (
            payload.get("message") and payload.get("status") == "error"
        ):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog returned a provider error"
            )
        return payload

    @staticmethod
    def _normalized_forex_row(item: Mapping[str, Any]) -> dict[str, str]:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not _FOREX_SYMBOL.fullmatch(symbol):
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog contains an invalid pair symbol"
            )
        base, quote = symbol.split("/", maxsplit=1)
        reported_base = str(item.get("currency_base") or "").strip()
        reported_quote = str(item.get("currency_quote") or "").strip()
        if not reported_base or not reported_quote:
            raise TwelveDataReferenceError(
                "Twelve Data forex catalog requires non-empty currency components"
            )
        if (
            _FOREX_CODE_COMPONENT.fullmatch(reported_base)
            and reported_base != base
        ) or (
            _FOREX_CODE_COMPONENT.fullmatch(reported_quote)
            and reported_quote != quote
        ):
            raise TwelveDataReferenceError(
                "Twelve Data forex code components do not match the pair symbol"
            )
        group = str(item.get("currency_group") or "").strip()
        return {
            "Code": symbol,
            "Name": f"{base} / {quote}" + (f" ({group})" if group else ""),
            "Exchange": _FOREX_EXCHANGE,
            "MIC": "",
            "Currency": quote,
            "CountryISO2": "GLOBAL",
            "Type": "Currency",
            "Figi": "",
            "CFI": "",
            "ISIN": "",
            "SourceProvider": "Twelve Data",
        }

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
