"""Bounded public security-catalog ingestion for global discovery evidence.

Public catalogs can materially widen instrument discovery without becoming
investment authority.  This module normalizes heterogeneous regulator/exchange
rows, preserves provider provenance, and can project a *completed* page set into
the canonical point-in-time security-master contracts.  Coverage is deliberately
non-authoritative unless a separately governed source definition can satisfy all
security-master authority requirements.

The collector is page-oriented so very large sources such as FIRDS are never
materialized synchronously inside a CIO request.  Continuous maintenance owns
page acquisition and may persist/resume the returned cursor between passes.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

import requests

from data.security import (
    AssetClass,
    IdentifierScheme,
    Instrument,
    InstrumentIdentifier,
    InstrumentType,
    TradingCalendar,
)
from data.security_master import SecurityMasterCatalog, SecurityMasterCoverage
from data.security_master_ingestion import SecurityMasterCatalogDelivery
from data.security import SecurityMasterSnapshot, VenueListing


class PublicSecurityCatalogError(RuntimeError):
    """Raised when a public discovery catalog cannot be safely normalized."""


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable(*parts: object) -> str:
    payload = "|".join(_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _first(row: Mapping[str, Any], *names: str) -> str:
    folded = {str(key).casefold(): value for key, value in row.items()}
    for name in names:
        value = folded.get(name.casefold())
        if _text(value):
            return _text(value)
    return ""


def _classify(cfi: str, kind: str = "") -> tuple[AssetClass, InstrumentType]:
    normalized_kind = kind.casefold()
    if normalized_kind == "option":
        return AssetClass.CRYPTO, InstrumentType.OPTION
    if normalized_kind in {"future", "future_combo"}:
        return AssetClass.CRYPTO, InstrumentType.FUTURE
    if normalized_kind == "spot":
        return AssetClass.CRYPTO, InstrumentType.SPOT
    if normalized_kind == "perpetual":
        return AssetClass.CRYPTO, InstrumentType.PERPETUAL
    prefix = cfi[:1].upper()
    if prefix == "E":
        return AssetClass.EQUITY, InstrumentType.COMMON_STOCK
    if prefix == "D":
        return AssetClass.FIXED_INCOME, InstrumentType.BOND
    if prefix in {"C", "I"}:
        return AssetClass.ETF, InstrumentType.FUND
    if prefix == "O":
        return AssetClass.ALTERNATIVE, InstrumentType.OPTION
    if prefix == "F":
        return AssetClass.ALTERNATIVE, InstrumentType.FUTURE
    return AssetClass.UNKNOWN, InstrumentType.OTHER


@dataclass(frozen=True, slots=True)
class PublicCatalogSourceDefinition:
    identifier: str
    source_name: str
    endpoint: str
    parser: str
    venue: str = "UNKNOWN"
    country_code: str = "ZZ"
    page_size: int = 500
    maximum_pages_per_pass: int = 1
    licensed_for_internal_analysis: bool = True
    point_in_time: bool = False
    historical_identifiers: bool = False
    listing_history: bool = False
    delistings: bool = False
    corporate_actions: bool = False
    provenance_complete: bool = True
    service_level_defined: bool = False

    def __post_init__(self) -> None:
        for name in ("identifier", "source_name", "endpoint", "parser"):
            if not _text(getattr(self, name)):
                raise ValueError(f"{name} cannot be empty")
        if not self.endpoint.startswith("https://"):
            raise ValueError("public catalog endpoint must use HTTPS")
        if self.page_size < 1 or self.page_size > 5000:
            raise ValueError("page_size must be between 1 and 5000")
        if self.maximum_pages_per_pass < 1 or self.maximum_pages_per_pass > 10:
            raise ValueError("maximum_pages_per_pass must be between 1 and 10")


@dataclass(frozen=True, slots=True)
class NormalizedPublicInstrument:
    source_identifier: str
    provider_instrument_identifier: str
    name: str
    symbol: str
    venue: str
    country_code: str
    isin: str = ""
    figi: str = ""
    cfi: str = ""
    asset_class: AssetClass = AssetClass.UNKNOWN
    instrument_type: InstrumentType = InstrumentType.OTHER
    base_asset: str | None = None
    quote_currency: str | None = None
    settlement_currency: str | None = None

    def __post_init__(self) -> None:
        if not _text(self.provider_instrument_identifier):
            raise ValueError("provider_instrument_identifier cannot be empty")
        if not _text(self.name):
            raise ValueError("name cannot be empty")
        if not isinstance(self.asset_class, AssetClass):
            raise TypeError("asset_class must be AssetClass")
        if not isinstance(self.instrument_type, InstrumentType):
            raise TypeError("instrument_type must be InstrumentType")


@dataclass(frozen=True, slots=True)
class PublicCatalogPage:
    source_identifier: str
    retrieved_at: datetime
    records: tuple[NormalizedPublicInstrument, ...]
    next_cursor: str | None
    complete: bool
    content_hash: str


class PublicSecurityCatalogProvider:
    """Fetch one bounded page from regulator/exchange discovery catalogs."""

    def __init__(
        self,
        source: PublicCatalogSourceDefinition,
        *,
        http_get: Callable[..., Any] | None = None,
        timeout: int = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.source = source
        self._http_get = http_get or requests.get
        self.timeout = timeout
        self._clock = clock or _utc_now

    def fetch_page(self, *, cursor: str | None = None) -> PublicCatalogPage:
        parser = getattr(self, f"_fetch_{self.source.parser}", None)
        if parser is None:
            raise PublicSecurityCatalogError(
                f"unsupported public catalog parser {self.source.parser!r}"
            )
        return parser(cursor=cursor)

    def _request(self, *, params: Mapping[str, object] | None = None) -> Any:
        response = self._http_get(
            self.source.endpoint,
            params=dict(params or {}),
            headers={"Accept": "application/json,text/csv,text/plain,application/xml"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def _finish(
        self,
        response: Any,
        records: Iterable[NormalizedPublicInstrument],
        *,
        next_cursor: str | None,
        complete: bool,
    ) -> PublicCatalogPage:
        raw = bytes(response.content)
        deduplicated: dict[tuple[str, str, str], NormalizedPublicInstrument] = {}
        for item in records:
            key = (
                item.provider_instrument_identifier,
                item.venue.upper(),
                item.symbol.upper(),
            )
            deduplicated[key] = item
        return PublicCatalogPage(
            source_identifier=self.source.identifier,
            retrieved_at=self._clock(),
            records=tuple(deduplicated.values()),
            next_cursor=next_cursor,
            complete=complete,
            content_hash=hashlib.sha256(raw).hexdigest(),
        )

    def _fetch_esma_solr(self, *, cursor: str | None) -> PublicCatalogPage:
        start = int(cursor or "0")
        params = {
            "q": "*:*",
            "rows": self.source.page_size,
            "start": start,
            "wt": "json",
        }
        response = self._request(params=params)
        payload = response.json()
        body = payload.get("response", {}) if isinstance(payload, Mapping) else {}
        docs = body.get("docs", []) if isinstance(body, Mapping) else []
        num_found = int(body.get("numFound", len(docs))) if isinstance(body, Mapping) else len(docs)
        records = [self._normalize_generic(row) for row in docs if isinstance(row, Mapping)]
        records = [item for item in records if item is not None]
        next_start = start + len(docs)
        complete = not docs or next_start >= num_found
        return self._finish(
            response,
            records,
            next_cursor=None if complete else str(next_start),
            complete=complete,
        )

    def _fetch_nasdaq_pipe(self, *, cursor: str | None) -> PublicCatalogPage:
        if cursor not in {None, "0"}:
            raise PublicSecurityCatalogError("nasdaq symbol directories are single-page snapshots")
        response = self._request()
        text = response.text.lstrip("\ufeff")
        reader = csv.DictReader(io.StringIO(text), delimiter="|")
        rows: list[NormalizedPublicInstrument] = []
        for raw in reader:
            if not isinstance(raw, Mapping):
                continue
            symbol = _first(raw, "Symbol", "ACT Symbol", "NASDAQ Symbol")
            if not symbol or symbol.startswith("File Creation Time"):
                continue
            name = _first(raw, "Security Name") or symbol
            exchange = _first(raw, "Exchange")
            venue = {
                "A": "NYSEAMERICAN",
                "N": "NYSE",
                "P": "NYSEARCA",
                "Z": "CBOE",
                "V": "IEX",
            }.get(exchange.upper(), self.source.venue)
            provider_id = f"{venue}:{symbol}"
            rows.append(
                NormalizedPublicInstrument(
                    source_identifier=f"{self.source.identifier}:{provider_id}",
                    provider_instrument_identifier=provider_id,
                    name=name,
                    symbol=symbol,
                    venue=venue,
                    country_code=self.source.country_code,
                    asset_class=AssetClass.UNKNOWN,
                    instrument_type=InstrumentType.OTHER,
                )
            )
        return self._finish(response, rows, next_cursor=None, complete=True)

    def _fetch_csv(self, *, cursor: str | None) -> PublicCatalogPage:
        if cursor not in {None, "0"}:
            raise PublicSecurityCatalogError("CSV catalog is a single-page snapshot")
        response = self._request()
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        rows = [self._normalize_generic(raw) for raw in reader if isinstance(raw, Mapping)]
        return self._finish(
            response,
            (item for item in rows if item is not None),
            next_cursor=None,
            complete=True,
        )

    def _fetch_deribit_instruments(self, *, cursor: str | None) -> PublicCatalogPage:
        # Cursor is the currency index.  One currency per pass keeps the public
        # derivative catalog small and rate-limit friendly.
        currencies = ("BTC", "ETH", "USDC", "USDT")
        index = int(cursor or "0")
        if not 0 <= index < len(currencies):
            raise PublicSecurityCatalogError("invalid Deribit catalog cursor")
        response = self._request(params={"currency": currencies[index], "expired": "false"})
        payload = response.json()
        rows = payload.get("result", []) if isinstance(payload, Mapping) else []
        normalized: list[NormalizedPublicInstrument] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            name = _text(raw.get("instrument_name"))
            if not name:
                continue
            kind = _text(raw.get("kind"))
            instrument_type = InstrumentType.OTHER
            if kind == "option":
                instrument_type = InstrumentType.OPTION
            elif kind == "future":
                settlement = _text(raw.get("settlement_period"))
                instrument_type = (
                    InstrumentType.PERPETUAL if settlement == "perpetual" else InstrumentType.FUTURE
                )
            elif kind == "spot":
                instrument_type = InstrumentType.SPOT
            normalized.append(
                NormalizedPublicInstrument(
                    source_identifier=f"{self.source.identifier}:{name}",
                    provider_instrument_identifier=name,
                    name=name,
                    symbol=name,
                    venue="DERIBIT",
                    country_code="ZZ",
                    asset_class=AssetClass.CRYPTO,
                    instrument_type=instrument_type,
                    base_asset=_text(raw.get("base_currency")) or None,
                    quote_currency=_text(raw.get("quote_currency")) or "USD",
                    settlement_currency=_text(raw.get("settlement_currency")) or None,
                )
            )
        complete = index == len(currencies) - 1
        return self._finish(
            response,
            normalized,
            next_cursor=None if complete else str(index + 1),
            complete=complete,
        )

    def _normalize_generic(
        self,
        raw: Mapping[str, Any],
    ) -> NormalizedPublicInstrument | None:
        isin = _first(
            raw,
            "isin",
            "instrument identification code",
            "instrument_identification_code",
            "id",
        )
        symbol = _first(raw, "symbol", "ticker", "code", "local code")
        name = _first(
            raw,
            "instrument full name",
            "instrument_full_name",
            "security name",
            "name",
            "issue name",
        )
        venue = _first(raw, "trading venue", "mic", "venue", "exchange") or self.source.venue
        cfi = _first(raw, "instrument classification", "cfi", "cfi code")
        figi = _first(raw, "figi", "composite figi")
        provider_id = isin or figi or (f"{venue}:{symbol}" if symbol else "")
        if not provider_id:
            return None
        if not name:
            name = symbol or provider_id
        asset_class, instrument_type = _classify(cfi)
        return NormalizedPublicInstrument(
            source_identifier=f"{self.source.identifier}:{provider_id}",
            provider_instrument_identifier=provider_id,
            name=name,
            symbol=symbol or provider_id,
            venue=venue,
            country_code=self.source.country_code,
            isin=isin if len(isin) == 12 else "",
            figi=figi,
            cfi=cfi,
            asset_class=asset_class,
            instrument_type=instrument_type,
        )


def security_master_delivery_from_public_records(
    source: PublicCatalogSourceDefinition,
    records: Iterable[NormalizedPublicInstrument],
    *,
    observed_at: datetime,
    retrieved_at: datetime,
    complete_source_snapshot: bool,
) -> SecurityMasterCatalogDelivery:
    """Project public discovery rows into canonical point-in-time master records.

    The projection is intentionally conservative: public catalogs are stored as
    discovery/reference evidence and their coverage cannot become authoritative
    merely because a complete download succeeded.
    """

    instruments: list[Instrument] = []
    listings: list[VenueListing] = []
    for row in records:
        identifiers: list[InstrumentIdentifier] = [
            InstrumentIdentifier(
                IdentifierScheme.PROVIDER,
                row.provider_instrument_identifier,
                provider=source.identifier,
            )
        ]
        if row.isin:
            identifiers.append(InstrumentIdentifier(IdentifierScheme.ISIN, row.isin))
        if row.figi:
            identifiers.append(InstrumentIdentifier(IdentifierScheme.FIGI, row.figi))
        if row.symbol:
            identifiers.append(
                InstrumentIdentifier(
                    IdentifierScheme.TICKER,
                    row.symbol,
                    provider=source.identifier,
                )
            )
        canonical_id = f"instrument:public:{_stable(source.identifier, row.provider_instrument_identifier)[:24]}"
        kwargs: dict[str, object] = {}
        if row.instrument_type in {
            InstrumentType.SPOT,
            InstrumentType.FUTURE,
            InstrumentType.PERPETUAL,
        }:
            kwargs.update(
                base_asset=row.base_asset or row.symbol.split("-")[0],
                quote_currency=row.quote_currency or "USD",
                settlement_currency=row.settlement_currency,
            )
        instruments.append(
            Instrument(
                instrument_id=canonical_id,
                name=row.name,
                asset_class=row.asset_class,
                instrument_type=row.instrument_type,
                identifiers=tuple(identifiers),
                uses_derivatives=row.instrument_type
                in {InstrumentType.FUTURE, InstrumentType.PERPETUAL, InstrumentType.OPTION},
                **kwargs,
            )
        )
        listings.append(
            VenueListing(
                instrument_id=canonical_id,
                venue=row.venue or source.venue,
                symbol=row.symbol or row.provider_instrument_identifier,
                trading_calendar=(
                    TradingCalendar.CONTINUOUS
                    if row.asset_class is AssetClass.CRYPTO
                    else TradingCalendar.EXCHANGE
                ),
            )
        )
    if not instruments:
        raise PublicSecurityCatalogError("cannot publish an empty public security catalog")
    snapshot = SecurityMasterSnapshot(
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        issuers=(),
        instruments=tuple(instruments),
        listings=tuple(listings),
        source=source.identifier,
    )
    coverage = SecurityMasterCoverage(
        source=source.source_name,
        source_version=f"public-discovery:{retrieved_at.date().isoformat()}",
        licensed=source.licensed_for_internal_analysis,
        complete_universe=bool(complete_source_snapshot),
        point_in_time=source.point_in_time,
        historical_identifiers=source.historical_identifiers,
        listing_history=source.listing_history,
        delistings=source.delistings,
        corporate_actions=source.corporate_actions,
        provenance_complete=source.provenance_complete,
        service_level_defined=source.service_level_defined,
    )
    catalog = SecurityMasterCatalog.from_current_snapshot(
        snapshot,
        identifier=f"catalog:{source.identifier}:{retrieved_at.date().isoformat()}",
        version=f"{retrieved_at.isoformat()}",
        coverage=coverage,
    )
    return SecurityMasterCatalogDelivery(
        catalog=catalog,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        request_identifier=f"public-catalog:{source.identifier}:{_stable(retrieved_at.isoformat())[:16]}",
    )


__all__ = [
    "NormalizedPublicInstrument",
    "PublicCatalogPage",
    "PublicCatalogSourceDefinition",
    "PublicSecurityCatalogError",
    "PublicSecurityCatalogProvider",
    "security_master_delivery_from_public_records",
]
