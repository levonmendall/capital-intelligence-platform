"""Executable-symbol refinement for CME FPRF futures reference data.

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
"""

from __future__ import annotations

from datetime import date
from typing import Any
from xml.etree import ElementTree

import requests

from providers.cme_futures_reference import (
    CmeFuturesReferenceProvider,
    _EXCHANGE_NORMALIZATION,
    _MONTH_CODES,
    _USER_AGENT,
    _local_name,
    _parse_date,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


_GLOBEX_ALIAS_SOURCES = ("101", "103", "8")
_DEFAULT_EXECUTABLE_REQUEST_TIMEOUT_SECONDS = 15


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
    """Resolve a configured Globex root from one CME clearing instrument.

    FPRF ``Instrmt.ID`` is a clearing code and cannot be treated as the executable root.
    Exact equality remains valid for products whose clearing and Globex codes coincide,
    while Globex aliases are authoritative when the codes differ.
    """

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


class CmeExecutableFuturesReferenceProvider(CmeFuturesReferenceProvider):
    """CME-primary reference provider that preserves executable Globex symbology.

    The executable adapter uses a shorter per-file request timeout than the generic base
    provider. Four FPRF files are fetched sequentially, so the previous 30-second default
    could consume the entire 120-second futures component budget and starve the governed
    Massive fallback. Fifteen seconds keeps every CME HTTP request bounded while leaving
    time for the independently durable fallback path.
    """

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


__all__ = ["CmeExecutableFuturesReferenceProvider"]
