"""Executable and resumable CME FPRF futures reference acquisition.

CME product reference identifies a contract by clearing root plus maturity and may also
publish exchange/Globex aliases. Databento and the existing exact-futures evidence route
consume CME raw symbols, which are usually one-year-digit symbols (for example ESU6) but
can be two-year-digit symbols for newer listings. Prefer CME's explicit Globex alias when
present and derive the conventional one-digit symbol only as a fallback.

CME clearing product IDs are not always the same as Globex roots. For example, CME
publishes 10-Year T-Note as clearing code ``21`` with Globex root ``ZN`` and major FX
contracts as clearing codes such as ``EC``/``BP``/``J1`` with Globex roots
``6E``/``6B``/``6J``. Configured-root completeness therefore resolves each FPRF
instrument through its Globex alias before applying the fail-closed coverage test.

Production reference acquisition is resumable below the governed all-roots manifest.
Each CME venue is qualified and persisted immediately. A later venue failure therefore
does not discard already-qualified work, and Massive is invoked only for the exact roots
that CME did not establish. The final configured-root completeness rule is unchanged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests

from providers.cme_futures_reference import (
    CmeFuturesReferenceProvider,
    _EXCHANGE_NORMALIZATION,
    _MONTH_CODES,
    _USER_AGENT,
    _aware,
    _cache_id,
    _local_name,
    _parse_date,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


_GLOBEX_ALIAS_SOURCES = ("101", "103", "8")
_DEFAULT_EXECUTABLE_REQUEST_TIMEOUT_SECONDS = 15
_VENUE_CACHE_SCHEMA = "cme-futures-reference-venue-cache.v1"
_ROOT_VENUES: Mapping[str, str] = {
    "ES": "CME",
    "NQ": "CME",
    "RTY": "CME",
    "6E": "CME",
    "6B": "CME",
    "6J": "CME",
    "ZN": "CBOT",
    "ZB": "CBOT",
    "GC": "COMEX",
    "SI": "COMEX",
    "HG": "COMEX",
    "CL": "NYMEX",
    "NG": "NYMEX",
}


def _valid_raw_symbol(candidate: object, product: str) -> str | None:
    symbol = "".join(str(candidate or "").strip().upper().split())
    if not symbol or symbol == product or not symbol.startswith(product):
        return None
    suffix = symbol[len(product) :]
    if len(suffix) < 2 or suffix[0] not in set(_MONTH_CODES.values()):
        return None
    if not suffix[1:].isdigit():
        return None
    return symbol


def _derived_raw_symbol(product: str, maturity: str) -> str | None:
    text = str(maturity or "").strip()
    if len(text) < 6 or not text[:6].isdigit():
        return None
    year = int(text[:4])
    month = int(text[4:6])
    month_code = _MONTH_CODES.get(month)
    if month_code is None:
        return None
    return f"{product}{month_code}{str(year)[-1]}"


def _instrument_aliases(element: ElementTree.Element) -> dict[str, tuple[str, ...]]:
    aliases: dict[str, list[str]] = {}
    for child in element:
        if _local_name(child.tag) != "AID":
            continue
        source = str(child.attrib.get("AltIDSrc") or "").strip()
        value = str(child.attrib.get("AltID") or "").strip()
        if source and value:
            aliases.setdefault(source, []).append(value)
    return {source: tuple(values) for source, values in aliases.items()}


def _configured_root_for_instrument(
    element: ElementTree.Element,
    roots: set[str],
) -> str | None:
    """Resolve a configured Globex root from one CME clearing instrument."""

    ordered_roots = tuple(sorted(roots, key=lambda item: (-len(item), item)))
    clearing_id = str(element.attrib.get("ID") or "").strip().upper()
    direct_symbol = str(element.attrib.get("Sym") or "").strip().upper()

    for root in ordered_roots:
        if clearing_id == root or direct_symbol == root:
            return root
        if _valid_raw_symbol(direct_symbol, root) is not None:
            return root

    aliases = _instrument_aliases(element)
    for source in _GLOBEX_ALIAS_SOURCES:
        for candidate in aliases.get(source, ()):
            for root in ordered_roots:
                if _valid_raw_symbol(candidate, root) is not None:
                    return root
    return None


def _canonical_exchange(value: object) -> str:
    raw = str(value or "").strip().upper()
    return _EXCHANGE_NORMALIZATION.get(raw, raw)


def _contract_payload(item: MassiveFuturesContract) -> dict[str, object]:
    return {
        "ticker": item.ticker,
        "product_code": item.product_code,
        "trading_venue": item.trading_venue,
        "first_trade_date": item.first_trade_date,
        "last_trade_date": item.last_trade_date,
        "settlement_date": item.settlement_date,
        "active": item.active,
        "source_identifier": item.source_identifier,
    }


def _contract_from_payload(item: Mapping[str, object]) -> MassiveFuturesContract:
    return MassiveFuturesContract(
        ticker=str(item["ticker"]),
        product_code=str(item["product_code"]),
        trading_venue=str(item["trading_venue"]),
        first_trade_date=str(item["first_trade_date"]),
        last_trade_date=str(item["last_trade_date"]),
        settlement_date=(
            None
            if item.get("settlement_date") in (None, "")
            else str(item.get("settlement_date"))
        ),
        active=bool(item.get("active", True)),
        source_identifier=str(item["source_identifier"]),
    )


class CmeExecutableFuturesReferenceProvider(CmeFuturesReferenceProvider):
    """CME-primary executable reference provider with durable venue qualification."""

    def __init__(
        self,
        *args: object,
        timeout: int = _DEFAULT_EXECUTABLE_REQUEST_TIMEOUT_SECONDS,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, timeout=timeout, **kwargs)

    @staticmethod
    def _instrument_symbol(element: ElementTree.Element, product: str, maturity: str) -> str | None:
        direct = _valid_raw_symbol(element.attrib.get("Sym"), product)
        if direct is not None:
            return direct
        aliases = _instrument_aliases(element)
        for source in _GLOBEX_ALIAS_SOURCES:
            for candidate in aliases.get(source, ()):
                alias = _valid_raw_symbol(candidate, product)
                if alias is not None:
                    return alias
        return _derived_raw_symbol(product, maturity)

    def _collect_file(
        self,
        *,
        exchange_name: str,
        url: str,
        roots: set[str],
        reference_date: date,
    ) -> tuple[list[MassiveFuturesContract], set[date], dict[str, object]]:
        try:
            response = self._http_get(
                url,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/xml,text/xml,*/*"},
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as error:
            raise MassiveMultiAssetError(f"CME FPRF {exchange_name} request failed") from error
        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            raise MassiveMultiAssetError(
                f"CME FPRF {exchange_name} returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=status in {408, 425, 429} or 500 <= status <= 599,
            )

        contracts: list[MassiveFuturesContract] = []
        business_dates: set[date] = set()
        current_business_date: date | None = None
        instrument_count = 0
        matched_count = 0
        matched_roots: set[str] = set()
        try:
            for event, element in ElementTree.iterparse(self._stream(response), events=("start", "end")):
                name = _local_name(element.tag)
                if event == "start" and name == "SecDef":
                    current_business_date = _parse_date(element.attrib.get("BizDt"))
                    if current_business_date is not None:
                        business_dates.add(current_business_date)
                    continue
                if event != "end":
                    continue
                if name == "Instrmt":
                    instrument_count += 1
                    security_type = str(element.attrib.get("SecTyp") or "").strip().upper()
                    status_text = str(element.attrib.get("Status") or "").strip()
                    if security_type != "FUT" or status_text != "1":
                        element.clear()
                        continue
                    product = _configured_root_for_instrument(element, roots)
                    if product is None:
                        element.clear()
                        continue
                    maturity = str(element.attrib.get("MMY") or "").strip()
                    ticker = self._instrument_symbol(element, product, maturity)
                    first_trade: date | None = None
                    last_trade: date | None = None
                    for child in element:
                        if _local_name(child.tag) != "Evnt":
                            continue
                        event_type = str(child.attrib.get("EventTyp") or "").strip()
                        if event_type == "5":
                            first_trade = _parse_date(child.attrib.get("Dt"))
                        elif event_type == "7":
                            last_trade = _parse_date(child.attrib.get("Dt"))
                    if ticker is None or first_trade is None or last_trade is None:
                        element.clear()
                        continue
                    if not first_trade <= reference_date <= last_trade:
                        element.clear()
                        continue
                    venue = str(element.attrib.get("Exch") or exchange_name).strip().upper()
                    venue = _EXCHANGE_NORMALIZATION.get(venue, venue)
                    settlement = _parse_date(element.attrib.get("MatDt"))
                    source_date = current_business_date or reference_date
                    contracts.append(
                        MassiveFuturesContract(
                            ticker=ticker,
                            product_code=product,
                            trading_venue=venue,
                            first_trade_date=first_trade.isoformat(),
                            last_trade_date=last_trade.isoformat(),
                            settlement_date=None if settlement is None else settlement.isoformat(),
                            active=True,
                            source_identifier=(
                                f"cme-fprf:{exchange_name.lower()}:{product}:{maturity}:"
                                f"{source_date.isoformat()}"
                            ),
                        )
                    )
                    matched_count += 1
                    matched_roots.add(product)
                    element.clear()
                elif name == "SecDef":
                    current_business_date = None
                    element.clear()
        except (ElementTree.ParseError, OSError, ValueError) as error:
            raise MassiveMultiAssetError(f"CME FPRF {exchange_name} XML parsing failed") from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        return contracts, business_dates, {
            "provider": "cme_fprf",
            "exchange": exchange_name,
            "http_status": status,
            "instrument_count": instrument_count,
            "matched_contract_count": matched_count,
            "matched_roots": sorted(matched_roots),
            "missing_roots": sorted(roots - matched_roots),
            "failure_reason": "ok",
        }

    def _venue_cache_path(self, venue: str, roots: Sequence[str]) -> Path:
        data_root = Path(
            self.values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
        ).expanduser()
        normalized = _canonical_exchange(venue) or "FALLBACK"
        scope = hashlib.sha256("|".join(sorted(roots)).encode("utf-8")).hexdigest()[:16]
        return (
            data_root
            / "reference_readiness"
            / f"cme-futures-venue-{normalized.lower()}-{scope}.json"
        )

    def _records_from_venue_cache(
        self,
        *,
        venue: str,
        roots: Sequence[str],
        as_of: datetime,
    ) -> tuple[tuple[MassiveFuturesContract, ...], tuple[date, ...]] | None:
        path = self._venue_cache_path(venue, roots)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping) or payload.get("schema_version") != _VENUE_CACHE_SCHEMA:
            return None
        expected_id = str(payload.get("cache_id") or "")
        material = {key: value for key, value in payload.items() if key != "cache_id"}
        if not expected_id or _cache_id(material) != expected_id:
            return None
        if str(payload.get("venue") or "") != _canonical_exchange(venue):
            return None
        expected_roots = tuple(sorted(roots))
        if tuple(payload.get("roots") or ()) != expected_roots:
            return None
        try:
            captured_at = _aware(
                datetime.fromisoformat(
                    str(payload.get("captured_at") or "").replace("Z", "+00:00")
                ),
                field_name="cached CME venue captured_at",
            )
        except (TypeError, ValueError):
            return None
        age = as_of - captured_at
        if age < timedelta(0) or age > self.cache_max_age:
            return None
        source_dates = payload.get("source_business_dates")
        if not isinstance(source_dates, Sequence) or isinstance(source_dates, (str, bytes)):
            return None
        if not self._source_dates_current(source_dates, as_of.date()):
            return None
        parsed_dates = tuple(
            item for item in (_parse_date(value) for value in source_dates) if item is not None
        )
        if not parsed_dates:
            return None
        raw_records = payload.get("records")
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            return None
        try:
            contracts = tuple(
                _contract_from_payload(item)
                for item in raw_records
                if isinstance(item, Mapping)
            )
        except (KeyError, TypeError, ValueError):
            return None
        if len(contracts) != len(raw_records) or not self._complete(contracts, roots):
            return None
        return (
            tuple(sorted(contracts, key=lambda item: (item.product_code, item.ticker))),
            parsed_dates,
        )

    def _write_venue_cache(
        self,
        *,
        venue: str,
        roots: Sequence[str],
        captured_at: datetime,
        business_dates: Sequence[date],
        contracts: Sequence[MassiveFuturesContract],
    ) -> None:
        normalized = _canonical_exchange(venue)
        dates = tuple(sorted(set(business_dates))) or (captured_at.date(),)
        material: dict[str, object] = {
            "schema_version": _VENUE_CACHE_SCHEMA,
            "venue": normalized,
            "captured_at": captured_at.isoformat(),
            "roots": list(sorted(roots)),
            "source_business_dates": [item.isoformat() for item in dates],
            "records": [
                _contract_payload(item)
                for item in sorted(contracts, key=lambda row: (row.product_code, row.ticker))
            ],
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload = {**material, "cache_id": _cache_id(material)}
        path = self._venue_cache_path(normalized, roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _collect_venue(
        self,
        *,
        venue: str,
        url: str,
        roots: Sequence[str],
        as_of: datetime,
        maximum_pages: int,
    ) -> tuple[tuple[MassiveFuturesContract, ...], tuple[date, ...], list[dict[str, object]]]:
        target = tuple(sorted(set(roots)))
        cached = self._records_from_venue_cache(venue=venue, roots=target, as_of=as_of)
        if cached is not None:
            rows, dates = cached
            return rows, dates, [
                {
                    "provider": "cme_fprf",
                    "exchange": _canonical_exchange(venue),
                    "mode": "venue_cache",
                    "configured_roots": len(target),
                    "covered_roots": len(target),
                    "failure_reason": "ok",
                }
            ]

        cme_rows: tuple[MassiveFuturesContract, ...] = ()
        business_dates: tuple[date, ...] = ()
        telemetry: list[dict[str, object]] = []
        primary_error: BaseException | None = None
        try:
            rows, dates, row_telemetry = self._collect_file(
                exchange_name=venue,
                url=url,
                roots=set(target),
                reference_date=as_of.date(),
            )
            cme_rows = tuple(rows)
            business_dates = tuple(sorted(dates))
            telemetry.append(dict(row_telemetry))
            if cme_rows and (
                not business_dates
                or not self._source_dates_current(business_dates, as_of.date())
            ):
                raise MassiveMultiAssetError(
                    f"CME FPRF {venue} business date is outside the governed current window"
                )
        except (MassiveMultiAssetError, OSError, TypeError, ValueError) as error:
            primary_error = error
            cme_rows = ()
            business_dates = ()
            telemetry.append(
                {
                    "provider": "cme_fprf",
                    "exchange": _canonical_exchange(venue),
                    "mode": "primary_failed",
                    "failure_reason": type(error).__name__,
                }
            )

        covered = {
            item.product_code.strip().upper()
            for item in cme_rows
            if item.active and item.product_code.strip().upper() in target
        }
        missing = tuple(root for root in target if root not in covered)
        fallback_rows: tuple[MassiveFuturesContract, ...] = ()
        if missing:
            cause = primary_error or MassiveMultiAssetError(
                f"CME FPRF {venue} configured-root coverage incomplete: "
                + ", ".join(missing)
            )
            fallback_rows = tuple(
                item
                for item in self._fallback(
                    as_of=as_of,
                    roots=missing,
                    maximum_pages=maximum_pages,
                    primary_error=cause,
                )
                if item.product_code.strip().upper() in set(missing)
            )
            telemetry.extend(dict(item) for item in self.reference_telemetry)

        combined: dict[tuple[str, str], MassiveFuturesContract] = {}
        for row in (*cme_rows, *fallback_rows):
            root = row.product_code.strip().upper()
            if root in target:
                combined[(root, row.ticker)] = row
        result = tuple(sorted(combined.values(), key=lambda item: (item.product_code, item.ticker)))
        if not self._complete(result, target):
            raise MassiveMultiAssetError(
                f"futures reference venue {venue} did not establish complete configured-root coverage"
            )

        captured_at = _aware(self._now(), field_name="CME venue reference captured_at")
        cache_dates = business_dates or (as_of.date(),)
        self._write_venue_cache(
            venue=venue,
            roots=target,
            captured_at=captured_at,
            business_dates=cache_dates,
            contracts=result,
        )
        telemetry.append(
            {
                "provider": "cme_fprf_composite" if missing else "cme_fprf",
                "exchange": _canonical_exchange(venue),
                "mode": "qualified_venue",
                "configured_roots": len(target),
                "covered_roots": len(target),
                "fallback_roots": list(missing),
                "failure_reason": "ok",
            }
        )
        return result, tuple(cache_dates), telemetry

    def _live_resumable(
        self,
        *,
        roots: Sequence[str],
        as_of: datetime,
        maximum_pages: int,
    ) -> tuple[MassiveFuturesContract, ...]:
        target = tuple(sorted(set(roots)))
        unresolved = set(target)
        contracts: dict[tuple[str, str], MassiveFuturesContract] = {}
        business_dates: set[date] = set()
        telemetry: list[dict[str, object]] = []
        fallback_used = False
        visited_venues: set[str] = set()

        for raw_venue, url in self.file_urls:
            venue = _canonical_exchange(raw_venue)
            if venue in visited_venues:
                continue
            visited_venues.add(venue)
            venue_roots = tuple(
                root
                for root in target
                if _ROOT_VENUES.get(root) == venue and root in unresolved
            )
            if not venue_roots:
                continue
            rows, dates, venue_telemetry = self._collect_venue(
                venue=venue,
                url=url,
                roots=venue_roots,
                as_of=as_of,
                maximum_pages=maximum_pages,
            )
            for row in rows:
                contracts[(row.product_code.strip().upper(), row.ticker)] = row
                if not row.source_identifier.startswith("cme-fprf:"):
                    fallback_used = True
            business_dates.update(dates)
            telemetry.extend(venue_telemetry)
            unresolved.difference_update(venue_roots)

        if unresolved:
            fallback_roots = tuple(sorted(unresolved))
            fallback_rows = tuple(
                item
                for item in self._fallback(
                    as_of=as_of,
                    roots=fallback_roots,
                    maximum_pages=maximum_pages,
                    primary_error=MassiveMultiAssetError(
                        "configured futures roots have no matching CME venue file: "
                        + ", ".join(fallback_roots)
                    ),
                )
                if item.product_code.strip().upper() in unresolved
            )
            for row in fallback_rows:
                contracts[(row.product_code.strip().upper(), row.ticker)] = row
            business_dates.add(as_of.date())
            telemetry.extend(dict(item) for item in self.reference_telemetry)
            fallback_used = True

        result = tuple(sorted(contracts.values(), key=lambda item: (item.product_code, item.ticker)))
        if not self._complete(result, target):
            covered = {item.product_code.strip().upper() for item in result if item.active}
            missing = tuple(root for root in target if root not in covered)
            raise MassiveMultiAssetError(
                "futures reference configured-root coverage incomplete: " + ", ".join(missing)
            )

        captured_at = _aware(self._now(), field_name="CME reference captured_at")
        cache_dates = tuple(sorted(business_dates)) or (as_of.date(),)
        self._write_cache(
            roots=target,
            captured_at=captured_at,
            business_dates=cache_dates,
            contracts=result,
        )
        self._reference_telemetry = telemetry
        self._reference_metadata = {
            "provider": "cme_fprf_composite" if fallback_used else "cme_fprf",
            "primary_provider": "cme_fprf",
            "reference_cadence": "daily",
            "captured_at": captured_at.isoformat(),
            "source_business_dates": [item.isoformat() for item in cache_dates],
            "configured_roots": len(target),
            "covered_roots": len(target),
            "venue_components": len(visited_venues),
            "fallback_used": fallback_used,
        }
        return result

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        roots = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        if not roots:
            raise MassiveMultiAssetError("CME futures reference requires configured product roots")
        cached = self._records_from_cache(roots=roots, as_of=timestamp)
        if cached is not None:
            return cached
        return self._live_resumable(
            roots=roots,
            as_of=timestamp,
            maximum_pages=maximum_pages,
        )


__all__ = ["CmeExecutableFuturesReferenceProvider"]
