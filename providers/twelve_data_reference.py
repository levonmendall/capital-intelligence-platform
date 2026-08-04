"""Twelve Data reference-catalog fallback for global equity discovery.

The canonical runtime prefers the configured EODHD symbol directory and its bounded
last-success cache. This provider is a second independent reference source used only
when EODHD returns HTTP 402 and no valid EODHD cache exists. It retrieves Twelve
Data's daily global stock catalog, proves pagination completion, and then exposes the
subset belonging to the requested configured exchange.

The adapter has discovery authority only. It cannot rank candidates, size positions,
construct a portfolio, authorize execution, or enable real money.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetError,
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)
from providers.environment_aliases import provider_environment_value


TWELVE_DATA_API_BASE = "https://api.twelvedata.com"
TWELVE_DATA_REFERENCE_SOURCE_VERSION = "twelve-data-stocks-reference.v1"
_LIVE_QUERY_GRACE = timedelta(minutes=5)
_DEFAULT_PAGE_SIZE = 5_000
_DEFAULT_MAX_PAGES = 250


def _normalized_text(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()


class TwelveDataReferenceError(ProviderDatasetError):
    """Raised when the Twelve Data reference catalog is unavailable or incomplete."""


@dataclass(frozen=True, slots=True)
class ExchangeSelector:
    """Map one configured EODHD exchange code to Twelve Data reference fields."""

    country_code: str
    mic_codes: frozenset[str]
    exchange_aliases: tuple[str, ...]
    allow_country_fallback: bool = False

    def __post_init__(self) -> None:
        country = self.country_code.strip().upper()
        if len(country) != 2:
            raise ValueError("country_code must be an ISO alpha-2 code")
        object.__setattr__(self, "country_code", country)
        object.__setattr__(
            self,
            "mic_codes",
            frozenset(item.strip().upper() for item in self.mic_codes if item.strip()),
        )
        aliases = tuple(
            _normalized_text(item)
            for item in self.exchange_aliases
            if str(item).strip()
        )
        if not self.mic_codes and not aliases:
            raise ValueError("exchange selector requires a MIC or exchange alias")
        object.__setattr__(self, "exchange_aliases", aliases)


_EXCHANGE_SELECTORS: dict[str, ExchangeSelector] = {
    "LSE": ExchangeSelector(
        "GB",
        frozenset({"XLON"}),
        ("LSE", "London Stock Exchange"),
        True,
    ),
    "XETRA": ExchangeSelector(
        "DE",
        frozenset({"XETR"}),
        ("Xetra", "Deutsche Boerse Xetra"),
        True,
    ),
    "PA": ExchangeSelector(
        "FR",
        frozenset({"XPAR"}),
        ("Euronext Paris", "Paris"),
        True,
    ),
    "AS": ExchangeSelector(
        "NL",
        frozenset({"XAMS"}),
        ("Euronext Amsterdam", "Amsterdam"),
        True,
    ),
    "BR": ExchangeSelector(
        "BE",
        frozenset({"XBRU"}),
        ("Euronext Brussels", "Brussels"),
        True,
    ),
    "SW": ExchangeSelector(
        "CH",
        frozenset({"XSWX", "XVTX"}),
        ("SIX Swiss Exchange", "Swiss Exchange", "Virt-X"),
        True,
    ),
    "TO": ExchangeSelector(
        "CA",
        frozenset({"XTSE"}),
        ("Toronto Stock Exchange", "TSX"),
    ),
    "V": ExchangeSelector(
        "CA",
        frozenset({"XTSX"}),
        ("TSX Venture", "TSXV"),
    ),
    "AU": ExchangeSelector(
        "AU",
        frozenset({"XASX"}),
        ("Australian Securities Exchange", "ASX"),
        True,
    ),
    "HK": ExchangeSelector(
        "HK",
        frozenset({"XHKG"}),
        ("Hong Kong Stock Exchange", "Hong Kong Exchanges", "HKEX"),
        True,
    ),
    "TSE": ExchangeSelector(
        "JP",
        frozenset({"XTKS", "XJPX"}),
        ("Tokyo Stock Exchange", "Japan Exchange Group", "JPX"),
        True,
    ),
    "NSE": ExchangeSelector(
        "IN",
        frozenset({"XNSE"}),
        ("National Stock Exchange of India", "NSE"),
    ),
    "BSE": ExchangeSelector(
        "IN",
        frozenset({"XBOM"}),
        ("Bombay Stock Exchange", "BSE"),
    ),
    "SG": ExchangeSelector(
        "SG",
        frozenset({"XSES"}),
        ("Singapore Exchange", "SGX"),
        True,
    ),
    "KO": ExchangeSelector(
        "KR",
        frozenset({"XKRX", "XKOS"}),
        ("Korea Exchange", "KRX", "KOSDAQ"),
    ),
    "WAR": ExchangeSelector(
        "PL",
        frozenset({"XWAR"}),
        ("Warsaw Stock Exchange", "WSE"),
        True,
    ),
    "SA": ExchangeSelector(
        "BR",
        frozenset({"BVMF", "XBSP"}),
        ("B3", "Bovespa", "Sao Paulo Stock Exchange"),
    ),
    "MX": ExchangeSelector(
        "MX",
        frozenset({"XMEX"}),
        ("Mexican Stock Exchange", "Bolsa Mexicana", "BMV"),
        True,
    ),
}

_COUNTRY_CODES = {
    "AUSTRALIA": "AU",
    "BELGIUM": "BE",
    "BRAZIL": "BR",
    "CANADA": "CA",
    "CHINA": "CN",
    "FRANCE": "FR",
    "GERMANY": "DE",
    "HONG KONG": "HK",
    "INDIA": "IN",
    "JAPAN": "JP",
    "MEXICO": "MX",
    "NETHERLANDS": "NL",
    "POLAND": "PL",
    "SINGAPORE": "SG",
    "SOUTH KOREA": "KR",
    "KOREA REPUBLIC OF": "KR",
    "SWITZERLAND": "CH",
    "UNITED KINGDOM": "GB",
    "UK": "GB",
}


def _country_code(value: object) -> str:
    normalized = _normalized_text(value)
    if len(normalized) == 2:
        return normalized
    return _COUNTRY_CODES.get(normalized, normalized or "GLOBAL")


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TwelveDataReferenceError(f"{field_name} is missing")
    return value.strip()


class TwelveDataReferenceProvider:
    """Retrieve and partition Twelve Data's complete current global stock catalog."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: int = 30,
        page_size: int = _DEFAULT_PAGE_SIZE,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        self.api_key = api_key or provider_environment_value(
            "TWELVE_API_KEY",
            "TWELVE_DATA_API_KEY",
        )
        self._http_get = http_get or requests.get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.timeout_seconds = int(timeout_seconds)
        self.page_size = int(page_size)
        self.max_pages = int(max_pages)
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= self.page_size <= 5_000:
            raise ValueError("page_size must be between 1 and 5000")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")
        self._catalog_rows: tuple[Mapping[str, Any], ...] | None = None
        self._catalog_retrieved_at: datetime | None = None

    @property
    def name(self) -> str:
        return "Twelve Data"

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def fetch_dataset(
        self,
        query: ProviderDatasetQuery,
    ) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        if query.dataset_type is not ProviderDatasetType.SYMBOL_DIRECTORY:
            raise TwelveDataReferenceError(
                "Twelve Data reference fallback supports only symbol directories"
            )
        exchange = query.provider_symbol.strip().upper()
        selector = _EXCHANGE_SELECTORS.get(exchange)
        if selector is None:
            raise TwelveDataReferenceError(
                f"no Twelve Data reference selector is certified for {exchange}"
            )
        if not self.api_key:
            raise TwelveDataReferenceError(
                "TWELVE_API_KEY or TWELVE_DATA_API_KEY is not configured"
            )

        rows, retrieved_at = self._global_stock_catalog()
        selected = self._select_exchange(rows, selector)
        if not selected:
            raise TwelveDataReferenceError(
                f"Twelve Data returned no certified current records for {exchange}"
            )
        if len(selected) > query.limit:
            raise TwelveDataReferenceError(
                f"Twelve Data directory {exchange} exceeds the query completeness limit"
            )

        snapshot_query = query
        if retrieved_at > query.as_of:
            delay = retrieved_at - query.as_of
            if delay > _LIVE_QUERY_GRACE:
                raise TwelveDataReferenceError(
                    "Twelve Data catalog completed outside the live query grace window"
                )
            snapshot_query = replace(query, as_of=retrieved_at)

        normalized = tuple(
            self._normalized_directory_row(
                item,
                exchange=exchange,
                selector=selector,
            )
            for item in selected
        )
        material = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        fingerprint = hashlib.sha256(material).hexdigest()
        return ProviderDatasetSnapshot(
            query=snapshot_query,
            provider=self.name,
            source_version=TWELVE_DATA_REFERENCE_SOURCE_VERSION,
            observed_at=retrieved_at,
            available_at=retrieved_at,
            retrieved_at=retrieved_at,
            quality_state=DataQualityState.FALLBACK,
            availability_basis=AvailabilityBasis.RETRIEVAL_PROXY,
            payload={"active": list(normalized), "delisted": []},
            provider_record_id=(
                f"twelve-data:stocks-reference:{exchange}:{fingerprint}"
            ),
            limitations=(
                "Twelve Data's daily current stock catalog was used as an independent "
                "reference fallback after EODHD entitlement failure.",
                "The fallback catalog is current-only and does not certify historical "
                "delisting or identifier-change lineage.",
                "Reference-catalog fallback has discovery authority only and cannot "
                "authorize a candidate, decision, size, construction, or execution.",
            ),
        )

    def _global_stock_catalog(
        self,
    ) -> tuple[tuple[Mapping[str, Any], ...], datetime]:
        if self._catalog_rows is not None and self._catalog_retrieved_at is not None:
            return self._catalog_rows, self._catalog_retrieved_at

        rows: list[Mapping[str, Any]] = []
        seen_pages: set[str] = set()
        first_reported_count: int | None = None
        raw_count = 0
        for page in range(1, self.max_pages + 1):
            payload = self._request_page(page)
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
                raw_count_value = payload.get("count")
                try:
                    first_reported_count = int(raw_count_value)
                except (TypeError, ValueError):
                    first_reported_count = None
            if not page_rows:
                break
            page_fingerprint = hashlib.sha256(
                json.dumps(
                    page_rows,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            if page_fingerprint in seen_pages:
                raise TwelveDataReferenceError(
                    "Twelve Data stock catalog pagination repeated a prior page"
                )
            seen_pages.add(page_fingerprint)
            rows.extend(page_rows)
            raw_count += len(page_rows)
        else:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog exceeded the certified pagination bound"
            )

        if not rows:
            raise TwelveDataReferenceError("Twelve Data stock catalog is empty")
        if first_reported_count is not None and first_reported_count > raw_count:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog pagination ended before the reported count"
            )

        unique: dict[tuple[str, str, str, str, str], Mapping[str, Any]] = {}
        for item in rows:
            key = (
                str(item.get("symbol", "")).strip().upper(),
                str(item.get("mic_code", "")).strip().upper(),
                _normalized_text(item.get("exchange")),
                _country_code(item.get("country")),
                _normalized_text(item.get("type")),
            )
            if not key[0]:
                continue
            unique.setdefault(key, item)
        if not unique:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog contains no usable symbol identities"
            )
        retrieved_at = self._now()
        self._catalog_rows = tuple(unique.values())
        self._catalog_retrieved_at = retrieved_at
        return self._catalog_rows, retrieved_at

    def _request_page(self, page: int) -> Mapping[str, Any]:
        try:
            response = self._http_get(
                TWELVE_DATA_API_BASE + "/stocks",
                params={
                    "apikey": self.api_key,
                    "format": "JSON",
                    "include_delisted": "false",
                    "outputsize": self.page_size,
                    "page": page,
                },
                timeout=self.timeout_seconds,
            )
        except requests.Timeout as error:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog request timed out"
            ) from error
        except requests.ConnectionError as error:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog connection failed"
            ) from error
        except requests.RequestException as error:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog request failed"
            ) from error
        try:
            status_code = int(getattr(response, "status_code", 0))
        except (TypeError, ValueError) as error:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog returned an invalid HTTP response"
            ) from error
        if status_code < 200 or status_code >= 300:
            raise TwelveDataReferenceError(
                f"Twelve Data stock catalog returned HTTP {status_code}"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog returned invalid JSON"
            ) from error
        if not isinstance(payload, Mapping):
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog response must be an object"
            )
        if payload.get("code") or (
            payload.get("message") and payload.get("status") == "error"
        ):
            raise TwelveDataReferenceError(
                "Twelve Data stock catalog returned a provider error"
            )
        return payload

    @staticmethod
    def _select_exchange(
        rows: Sequence[Mapping[str, Any]],
        selector: ExchangeSelector,
    ) -> tuple[Mapping[str, Any], ...]:
        direct: list[Mapping[str, Any]] = []
        country_rows: list[Mapping[str, Any]] = []
        for item in rows:
            country = _country_code(item.get("country"))
            if country == selector.country_code:
                country_rows.append(item)
            mic = str(item.get("mic_code", "")).strip().upper()
            exchange = _normalized_text(item.get("exchange"))
            if mic in selector.mic_codes or any(
                alias and alias in exchange for alias in selector.exchange_aliases
            ):
                direct.append(item)
        if direct:
            return tuple(direct)
        if selector.allow_country_fallback:
            return tuple(country_rows)
        return ()

    @staticmethod
    def _normalized_directory_row(
        item: Mapping[str, Any],
        *,
        exchange: str,
        selector: ExchangeSelector,
    ) -> dict[str, str]:
        symbol = _required_text(item.get("symbol"), field_name="symbol").upper()
        name = str(item.get("name") or symbol).strip()
        currency = str(item.get("currency") or "USD").strip().upper()
        issue_type = str(item.get("type") or "Common Stock").strip()
        mic = str(item.get("mic_code") or "").strip().upper()
        country = _country_code(item.get("country"))
        if country == "GLOBAL":
            country = selector.country_code
        return {
            "Code": symbol,
            "Name": name,
            "Exchange": exchange,
            "MIC": mic,
            "Currency": currency,
            "CountryISO2": country,
            "Type": issue_type,
            "Figi": str(item.get("figi_code") or "").strip(),
            "CFI": str(item.get("cfi_code") or "").strip(),
            "ISIN": str(item.get("isin") or "").strip(),
            "SourceProvider": "Twelve Data",
        }

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)


def build_twelve_data_reference_provider() -> TwelveDataReferenceProvider:
    """Build the production reference provider from normalized environment keys."""

    return TwelveDataReferenceProvider()


__all__ = [
    "ExchangeSelector",
    "TWELVE_DATA_API_BASE",
    "TWELVE_DATA_REFERENCE_SOURCE_VERSION",
    "TwelveDataReferenceError",
    "TwelveDataReferenceProvider",
    "build_twelve_data_reference_provider",
]
