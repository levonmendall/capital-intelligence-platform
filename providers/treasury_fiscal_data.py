"""Keyless U.S. Treasury Fiscal Data reference evidence.

This adapter supplies point-in-time identity and terms for marketable U.S. Treasury
securities from the Bureau of the Fiscal Service. It is reference evidence only: it
does not provide evaluated prices, authorize trades, or synthesize missing securities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping

import requests

from providers.redundancy_audit import (
    ProviderCapabilityKey,
    current_redundancy_ledger,
)


TREASURY_AUCTIONS_ENDPOINT = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v1/accounting/od/auctions_query"
)


class TreasuryFiscalDataError(RuntimeError):
    """Raised when Treasury reference evidence cannot be retrieved or validated."""


def is_valid_cusip(value: object) -> bool:
    """Return whether ``value`` satisfies the CUSIP 8-character body + check digit."""

    if not isinstance(value, str):
        return False
    normalized = value.strip().upper()
    if len(normalized) != 9 or not normalized[-1].isdigit():
        return False
    total = 0
    for index, character in enumerate(normalized[:8], start=1):
        if character.isdigit():
            number = int(character)
        elif "A" <= character <= "Z":
            number = ord(character) - ord("A") + 10
        elif character == "*":
            number = 36
        elif character == "@":
            number = 37
        elif character == "#":
            number = 38
        else:
            return False
        if index % 2 == 0:
            number *= 2
        total += number // 10 + number % 10
    check_digit = (10 - total % 10) % 10
    return int(normalized[-1]) == check_digit


def _date(value: object, *, field: str) -> date:
    if not isinstance(value, str) or not value.strip():
        raise TreasuryFiscalDataError(f"Treasury record missing {field}")
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as error:
        raise TreasuryFiscalDataError(f"Treasury record has invalid {field}") from error


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class TreasurySecurityReference:
    cusip: str
    security_type: str
    security_term: str
    record_date: date
    auction_date: date
    issue_date: date
    maturity_date: date
    high_yield: float | None = None
    high_discount_rate: float | None = None
    investment_rate: float | None = None
    price_per_100: float | None = None
    bid_to_cover_ratio: float | None = None

    def __post_init__(self) -> None:
        normalized = self.cusip.strip().upper()
        if not is_valid_cusip(normalized):
            raise ValueError("TreasurySecurityReference requires a valid CUSIP")
        object.__setattr__(self, "cusip", normalized)

    @property
    def evidence_identifier(self) -> str:
        return (
            "treasury-fiscal-data:auctions_query:"
            f"{self.cusip}:{self.record_date.isoformat()}"
        )


class TreasuryFiscalDataProvider:
    """Retrieve active, already-issued Treasury securities known at ``as_of``."""

    endpoint = TREASURY_AUCTIONS_ENDPOINT

    def __init__(
        self,
        *,
        timeout_seconds: int = 20,
        page_size: int = 500,
        maximum_pages: int = 20,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        if timeout_seconds < 1 or page_size < 1 or maximum_pages < 1:
            raise ValueError("Treasury provider bounds must be positive")
        self.timeout_seconds = timeout_seconds
        self.page_size = min(page_size, 1000)
        self.maximum_pages = maximum_pages
        self._http_get = http_get or requests.get

    def fetch_active_securities(
        self,
        *,
        as_of: datetime,
    ) -> tuple[TreasurySecurityReference, ...]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        as_of_date = as_of.astimezone(timezone.utc).date()
        audit_key = ProviderCapabilityKey(
            "treasury_fiscal_data",
            "treasury_security_reference",
            "auctions_query",
        )
        ledger = current_redundancy_ledger()
        if ledger is not None:
            ledger.declare(
                audit_key,
                configured=True,
                authenticated=True,
                routed=True,
                certified_for_evidence_role=True,
            )
            ledger.attempted(audit_key)
        fields = ",".join(
            (
                "record_date",
                "cusip",
                "security_type",
                "security_term",
                "auction_date",
                "issue_date",
                "maturity_date",
                "high_yield",
                "high_discount_rate",
                "investment_rate",
                "price_per100",
                "bid_to_cover_ratio",
            )
        )
        filters = ",".join(
            (
                f"record_date:lte:{as_of_date.isoformat()}",
                f"issue_date:lte:{as_of_date.isoformat()}",
                f"maturity_date:gte:{as_of_date.isoformat()}",
            )
        )
        latest_by_cusip: dict[str, TreasurySecurityReference] = {}
        for page_number in range(1, self.maximum_pages + 1):
            try:
                response = self._http_get(
                    self.endpoint,
                    params={
                        "fields": fields,
                        "filter": filters,
                        "sort": "-record_date,-auction_date",
                        "page[number]": page_number,
                        "page[size]": self.page_size,
                    },
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "Capital-Intelligence-Platform/1.0",
                    },
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as error:
                raise TreasuryFiscalDataError("Treasury Fiscal Data request failed") from error
            status = int(getattr(response, "status_code", 0))
            if status < 200 or status >= 300:
                raise TreasuryFiscalDataError(
                    f"Treasury Fiscal Data returned HTTP {status or 'unknown'}"
                )
            try:
                payload = response.json()
            except (TypeError, ValueError) as error:
                raise TreasuryFiscalDataError(
                    "Treasury Fiscal Data returned invalid JSON"
                ) from error
            if not isinstance(payload, Mapping):
                raise TreasuryFiscalDataError("Treasury Fiscal Data response must be an object")
            raw_rows = payload.get("data")
            if not isinstance(raw_rows, list):
                raise TreasuryFiscalDataError("Treasury Fiscal Data response missing data")
            for raw in raw_rows:
                if not isinstance(raw, Mapping):
                    continue
                cusip = str(raw.get("cusip", "")).strip().upper()
                security_type = str(raw.get("security_type", "")).strip()
                security_term = str(raw.get("security_term", "")).strip()
                if not is_valid_cusip(cusip) or not security_type or not security_term:
                    continue
                reference = TreasurySecurityReference(
                    cusip=cusip,
                    security_type=security_type,
                    security_term=security_term,
                    record_date=_date(raw.get("record_date"), field="record_date"),
                    auction_date=_date(raw.get("auction_date"), field="auction_date"),
                    issue_date=_date(raw.get("issue_date"), field="issue_date"),
                    maturity_date=_date(raw.get("maturity_date"), field="maturity_date"),
                    high_yield=_optional_float(raw.get("high_yield")),
                    high_discount_rate=_optional_float(raw.get("high_discount_rate")),
                    investment_rate=_optional_float(raw.get("investment_rate")),
                    price_per_100=_optional_float(raw.get("price_per100")),
                    bid_to_cover_ratio=_optional_float(raw.get("bid_to_cover_ratio")),
                )
                if reference.record_date > as_of_date:
                    continue
                if reference.issue_date > as_of_date or reference.maturity_date < as_of_date:
                    continue
                previous = latest_by_cusip.get(reference.cusip)
                if previous is None or reference.record_date > previous.record_date:
                    latest_by_cusip[reference.cusip] = reference
            meta = payload.get("meta")
            total_pages: int | None = None
            if isinstance(meta, Mapping):
                try:
                    total_pages = int(meta.get("total-pages"))
                except (TypeError, ValueError):
                    total_pages = None
            if not raw_rows or (total_pages is not None and page_number >= total_pages):
                break
            if len(raw_rows) < self.page_size:
                break
        if not latest_by_cusip:
            raise TreasuryFiscalDataError(
                "Treasury Fiscal Data returned no active point-in-time securities"
            )
        result = tuple(
            sorted(
                latest_by_cusip.values(),
                key=lambda item: (item.maturity_date, item.cusip),
            )
        )
        if ledger is not None:
            ledger.used(
                audit_key,
                source_identifiers=tuple(
                    item.evidence_identifier for item in result[:25]
                ),
                failed_over=False,
            )
        return result


def build_treasury_fiscal_data_provider() -> TreasuryFiscalDataProvider:
    """Build the keyless Treasury provider; no credential is required."""

    return TreasuryFiscalDataProvider()


__all__ = [
    "TREASURY_AUCTIONS_ENDPOINT",
    "TreasuryFiscalDataError",
    "TreasuryFiscalDataProvider",
    "TreasurySecurityReference",
    "build_treasury_fiscal_data_provider",
    "is_valid_cusip",
]
