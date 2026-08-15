"""Bounded public security-catalog ingestion for global discovery evidence.

Large regulator and exchange catalogs are acquired only by background evidence
maintenance.  A bounded page can be projected into the canonical temporal
security-master contracts, but public discovery catalogs never gain investment
or screening authority merely because retrieval succeeded.
"""

from __future__ import annotations

import csv
import hashlib
import io
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
from data.security_master import (
    IdentifierAssignment,
    InstrumentRecord,
    ListingRecord,
    ListingStatus,
    SecurityEntityType,
    SecurityMasterCatalog,
    SecurityMasterCoverage,
)
from data.security_master_ingestion import SecurityMasterCatalogDelivery


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


def _classify(cfi: str) -> tuple[AssetClass, InstrumentType]:
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
        for name in (
            "source_identifier",
            "provider_instrument_identifier",
            "name",
            "symbol",
            "venue",
            "country_code",
        ):
            if not _text(getattr(self, name)):
                raise ValueError(f"{name} cannot be empty")
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
    """Fetch one bounded page from a regulator/exchange discovery catalog."""

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
            headers={
                "Accept": (
                    "application/json,text/csv,text/plain,application/xml,"
                    "application/zip,application/octet-stream"
                )
            },
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
        # Canonical master contracts require one active venue-symbol mapping.  If a
        # public file contains duplicates, retain the first deterministic row rather
        # than allowing a low-authority discovery source to create ambiguity.
        by_venue_symbol: dict[tuple[str, str], NormalizedPublicInstrument] = {}
        for item in records:
            key = (item.venue.upper(), item.symbol.upper())
            by_venue_symbol.setdefault(key, item)
        raw = bytes(response.content)
        return PublicCatalogPage(
            source_identifier=self.source.identifier,
            retrieved_at=self._clock(),
            records=tuple(by_venue_symbol.values()),
            next_cursor=next_cursor,
            complete=complete,
            content_hash=hashlib.sha256(raw).hexdigest(),
        )

    def _fetch_esma_solr(self, *, cursor: str | None) -> PublicCatalogPage:
        start = int(cursor or "0")
        if start < 0:
            raise PublicSecurityCatalogError("ESMA cursor cannot be negative")
        response = self._request(
            params={
                "q": "*:*",
                "rows": self.source.page_size,
                "start": start,
                "wt": "json",
            }
        )
        payload = response.json()
        body = payload.get("response", {}) if isinstance(payload, Mapping) else {}
        docs = body.get("docs", []) if isinstance(body, Mapping) else []
        if not isinstance(docs, list):
            raise PublicSecurityCatalogError("ESMA response docs are malformed")
        num_found = int(body.get("numFound", len(docs)))
        normalized = tuple(
            item
            for row in docs
            if isinstance(row, Mapping)
            if (item := self._normalize_generic(row)) is not None
        )
        next_start = start + len(docs)
        complete = not docs or next_start >= num_found
        return self._finish(
            response,
            normalized,
            next_cursor=None if complete else str(next_start),
            complete=complete,
        )

    def _fetch_nasdaq_pipe(self, *, cursor: str | None) -> PublicCatalogPage:
        if cursor not in {None, "0"}:
            raise PublicSecurityCatalogError(
                "Nasdaq symbol directories are single-page snapshots"
            )
        response = self._request()
        reader = csv.DictReader(
            io.StringIO(response.text.lstrip("\ufeff")), delimiter="|"
        )
        output: list[NormalizedPublicInstrument] = []
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
            output.append(
                NormalizedPublicInstrument(
                    source_identifier=f"{self.source.identifier}:{provider_id}",
                    provider_instrument_identifier=provider_id,
                    name=name,
                    symbol=symbol,
                    venue=venue,
                    country_code=self.source.country_code,
                )
            )
        return self._finish(response, output, next_cursor=None, complete=True)

    def _fetch_csv(self, *, cursor: str | None) -> PublicCatalogPage:
        if cursor not in {None, "0"}:
            raise PublicSecurityCatalogError("CSV catalog is a single-page snapshot")
        response = self._request()
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        output = tuple(
            item
            for raw in reader
            if isinstance(raw, Mapping)
            if (item := self._normalize_generic(raw)) is not None
        )
        return self._finish(response, output, next_cursor=None, complete=True)

    def _fetch_deribit_instruments(self, *, cursor: str | None) -> PublicCatalogPage:
        currencies = ("BTC", "ETH", "USDC", "USDT")
        index = int(cursor or "0")
        if not 0 <= index < len(currencies):
            raise PublicSecurityCatalogError("invalid Deribit catalog cursor")
        response = self._request(
            params={"currency": currencies[index], "expired": "false"}
        )
        payload = response.json()
        rows = payload.get("result", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list):
            raise PublicSecurityCatalogError("Deribit instrument result is malformed")
        output: list[NormalizedPublicInstrument] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            name = _text(raw.get("instrument_name"))
            if not name:
                continue
            kind = _text(raw.get("kind")).casefold()
            settlement = _text(raw.get("settlement_period")).casefold()
            if kind == "option":
                instrument_type = InstrumentType.OPTION
            elif kind == "future":
                instrument_type = (
                    InstrumentType.PERPETUAL
                    if settlement == "perpetual"
                    else InstrumentType.FUTURE
                )
            elif kind == "spot":
                instrument_type = InstrumentType.SPOT
            else:
                instrument_type = InstrumentType.OTHER
            output.append(
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
            output,
            next_cursor=None if complete else str(index + 1),
            complete=complete,
        )

    def _normalize_generic(
        self,
        raw: Mapping[str, Any],
    ) -> NormalizedPublicInstrument | None:
        # Include both human-readable labels and common FIRDS field aliases.  Unknown
        # columns remain raw-provider concerns and never silently become authority.
        isin = _first(
            raw,
            "isin",
            "instrument identification code",
            "instrument_identification_code",
            "FinInstrmGnlAttrbts_Id",
            "id",
        )
        symbol = _first(
            raw,
            "symbol",
            "ticker",
            "code",
            "local code",
            "FinInstrmGnlAttrbts_ShrtNm",
        )
        name = _first(
            raw,
            "instrument full name",
            "instrument_full_name",
            "security name",
            "name",
            "issue name",
            "FinInstrmGnlAttrbts_FullNm",
        )
        venue = _first(
            raw,
            "trading venue",
            "mic",
            "venue",
            "exchange",
            "TradgVnRltdAttrbts_Id",
        ) or self.source.venue
        cfi = _first(
            raw,
            "instrument classification",
            "cfi",
            "cfi code",
            "FinInstrmGnlAttrbts_ClssfctnTp",
        )
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
    catalog_fingerprint: str,
) -> SecurityMasterCatalogDelivery:
    """Project one immutable public page into canonical security-master records."""

    rows = tuple(records)
    if not rows:
        raise PublicSecurityCatalogError("cannot publish an empty public security catalog")
    fingerprint = _text(catalog_fingerprint)
    if not fingerprint:
        raise ValueError("catalog_fingerprint cannot be empty")

    instrument_records: list[InstrumentRecord] = []
    identifier_records: list[IdentifierAssignment] = []
    listing_records: list[ListingRecord] = []
    seen_venue_symbols: set[tuple[str, str]] = set()

    for position, row in enumerate(rows, start=1):
        venue_symbol = (row.venue.upper(), row.symbol.upper())
        if venue_symbol in seen_venue_symbols:
            continue
        seen_venue_symbols.add(venue_symbol)
        canonical_id = (
            "instrument:public:"
            + _stable(source.identifier, row.provider_instrument_identifier)[:24]
        )
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
        identifiers.append(
            InstrumentIdentifier(
                IdentifierScheme.TICKER,
                row.symbol,
                provider=source.identifier,
            )
        )
        instrument_kwargs: dict[str, object] = {}
        if row.instrument_type in {
            InstrumentType.SPOT,
            InstrumentType.FUTURE,
            InstrumentType.PERPETUAL,
        }:
            instrument_kwargs.update(
                base_asset=row.base_asset or row.symbol.split("-")[0],
                quote_currency=row.quote_currency or "USD",
                settlement_currency=row.settlement_currency,
            )
        instrument = Instrument(
            instrument_id=canonical_id,
            name=row.name,
            asset_class=row.asset_class,
            instrument_type=row.instrument_type,
            identifiers=tuple(identifiers),
            uses_derivatives=row.instrument_type
            in {InstrumentType.FUTURE, InstrumentType.PERPETUAL, InstrumentType.OPTION},
            **instrument_kwargs,
        )
        base_record_id = f"{source.identifier}:{fingerprint}:{position}"
        instrument_records.append(
            InstrumentRecord(
                record_identifier=f"{base_record_id}:instrument",
                instrument=instrument,
                effective_from=observed_at,
                effective_until=None,
                available_at=retrieved_at,
                source_identifier=row.source_identifier,
            )
        )
        for id_position, identifier in enumerate(identifiers, start=1):
            assignment_id = (
                f"{canonical_id}:{identifier.scheme.value}:{identifier.value}:{id_position}"
            )
            identifier_records.append(
                IdentifierAssignment(
                    record_identifier=f"{base_record_id}:identifier:{id_position}",
                    assignment_identifier=assignment_id,
                    entity_type=SecurityEntityType.INSTRUMENT,
                    entity_identifier=canonical_id,
                    identifier=identifier,
                    effective_from=observed_at,
                    effective_until=None,
                    available_at=retrieved_at,
                    source_identifier=row.source_identifier,
                )
            )
        listing_records.append(
            ListingRecord(
                record_identifier=f"{base_record_id}:listing",
                listing_identifier=f"listing:{canonical_id}:{row.venue}:{row.symbol}",
                instrument_identifier=canonical_id,
                venue=row.venue,
                symbol=row.symbol,
                country_code=row.country_code,
                trading_calendar=(
                    TradingCalendar.CONTINUOUS
                    if row.asset_class is AssetClass.CRYPTO
                    else TradingCalendar.EXCHANGE
                ),
                status=ListingStatus.ACTIVE,
                primary=True,
                effective_from=observed_at,
                effective_until=None,
                available_at=retrieved_at,
                source_identifier=row.source_identifier,
            )
        )

    if not instrument_records:
        raise PublicSecurityCatalogError(
            "public catalog contained no unique venue-symbol instruments"
        )
    coverage = SecurityMasterCoverage(
        source=source.source_name,
        source_version=f"public-discovery:{fingerprint[:24]}",
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
    catalog = SecurityMasterCatalog(
        identifier=f"catalog:{source.identifier}:{fingerprint[:32]}",
        version=retrieved_at.isoformat(),
        issuers=(),
        instruments=tuple(instrument_records),
        identifiers=tuple(identifier_records),
        listings=tuple(listing_records),
        actions=(),
        coverage=coverage,
    )
    return SecurityMasterCatalogDelivery(
        catalog=catalog,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        request_identifier=(
            f"public-catalog:{source.identifier}:{fingerprint[:24]}"
        ),
    )


__all__ = [
    "NormalizedPublicInstrument",
    "PublicCatalogPage",
    "PublicCatalogSourceDefinition",
    "PublicSecurityCatalogError",
    "PublicSecurityCatalogProvider",
    "security_master_delivery_from_public_records",
]
