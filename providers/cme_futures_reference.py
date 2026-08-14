"""CME-first, persistent daily futures contract reference acquisition.

CME Group's public FIXML Product Reference Files (FPRF) are the primary source for the
slow-moving futures instrument master. A qualified snapshot is persisted on the platform
volume and reused inside a 24-hour hot window. Massive remains a bounded secondary source
only when CME reference acquisition is unavailable or incomplete.

Configured-root completeness and point-in-time contract validity remain fail-closed. This
adapter has no ranking, CIO, construction, execution, or real-money authority.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree

import requests

from providers.massive_multi_asset import (
    MassiveFuturesContract,
    MassiveMultiAssetError,
)

_CME_FPRF_BASE = "https://www.cmegroup.com/ftp/fprf"
_DEFAULT_FILES: tuple[tuple[str, str], ...] = (
    ("CME", f"{_CME_FPRF_BASE}/cmeg.cme.fut.prf.xml"),
    ("CBOT", f"{_CME_FPRF_BASE}/cmeg.cbt.fut.prf.xml"),
    ("COMEX", f"{_CME_FPRF_BASE}/cmeg.comex.fut.prf.xml"),
    ("NYMEX", f"{_CME_FPRF_BASE}/cmeg.nymex.fut.prf.xml"),
)
_CACHE_SCHEMA = "cme-futures-reference-cache.v1"
_DEFAULT_CACHE_MAX_AGE_HOURS = 24.0
_DEFAULT_SOURCE_DATE_TOLERANCE_DAYS = 4
_MONTH_CODES = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}
_EXCHANGE_NORMALIZATION = {
    "CBT": "CBOT",
    "XCBT": "CBOT",
    "XCME": "CME",
    "XCEC": "COMEX",
    "XNYM": "NYMEX",
}
_USER_AGENT = (
    "CapitalIntelligencePlatform/1.0 "
    "(+public CME futures reference; paper-only research)"
)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_date(value: object) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _ticker_from_maturity(root: str, maturity: str) -> str | None:
    text = str(maturity or "").strip()
    if len(text) < 6 or not text[:6].isdigit():
        return None
    year = int(text[:4])
    month = int(text[4:6])
    month_code = _MONTH_CODES.get(month)
    if month_code is None:
        return None
    return f"{root}{month_code}{str(year)[-2:]}"


def _cache_id(material: Mapping[str, object]) -> str:
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CmeFuturesReferenceProvider:
    """Resolve configured futures roots from CME FPRF with Massive as fallback only."""

    def __init__(
        self,
        *,
        fallback_provider: Any | None = None,
        http_get: Callable[..., Any] | None = None,
        timeout: int = 30,
        file_urls: Sequence[tuple[str, str]] = _DEFAULT_FILES,
        cache_max_age_hours: float = _DEFAULT_CACHE_MAX_AGE_HOURS,
        source_date_tolerance_days: int = _DEFAULT_SOURCE_DATE_TOLERANCE_DAYS,
        values: Mapping[str, str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.fallback_provider = fallback_provider
        self._http_get = http_get or requests.get
        self.timeout = int(timeout)
        if self.timeout < 1:
            raise ValueError("timeout must be positive")
        self.file_urls = tuple((str(name), str(url)) for name, url in file_urls)
        if not self.file_urls:
            raise ValueError("at least one CME FPRF file is required")
        self.cache_max_age = timedelta(hours=float(cache_max_age_hours))
        if self.cache_max_age <= timedelta(0) or self.cache_max_age > timedelta(hours=48):
            raise ValueError("cache_max_age_hours must be positive and no more than 48")
        if not 1 <= int(source_date_tolerance_days) <= 7:
            raise ValueError("source_date_tolerance_days must be between 1 and 7")
        self.source_date_tolerance_days = int(source_date_tolerance_days)
        self.values = os.environ if values is None else values
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._reference_telemetry: list[dict[str, object]] = []
        self._reference_metadata: dict[str, object] = {}

    @property
    def configured(self) -> bool:
        return True

    @property
    def reference_telemetry(self) -> tuple[Mapping[str, object], ...]:
        return tuple(dict(item) for item in self._reference_telemetry)

    @property
    def reference_metadata(self) -> Mapping[str, object]:
        return dict(self._reference_metadata)

    def _cache_path(self, roots: Sequence[str]) -> Path:
        root = Path(self.values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
        scope = hashlib.sha256("|".join(sorted(roots)).encode("utf-8")).hexdigest()[:16]
        return root / "reference_readiness" / f"cme-futures-daily-{scope}.json"

    def _records_from_cache(
        self,
        *,
        roots: Sequence[str],
        as_of: datetime,
    ) -> tuple[MassiveFuturesContract, ...] | None:
        path = self._cache_path(roots)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping) or payload.get("schema_version") != _CACHE_SCHEMA:
            return None
        expected_id = str(payload.get("cache_id") or "")
        material = {key: value for key, value in payload.items() if key != "cache_id"}
        if not expected_id or _cache_id(material) != expected_id:
            return None
        if tuple(payload.get("roots") or ()) != tuple(sorted(roots)):
            return None
        try:
            captured_at = _aware(
                datetime.fromisoformat(str(payload.get("captured_at") or "").replace("Z", "+00:00")),
                field_name="cached CME captured_at",
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
        raw_records = payload.get("records")
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            return None
        contracts: list[MassiveFuturesContract] = []
        try:
            for item in raw_records:
                if not isinstance(item, Mapping):
                    return None
                contracts.append(
                    MassiveFuturesContract(
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
                )
        except (KeyError, TypeError, ValueError):
            return None
        if not self._complete(contracts, roots):
            return None
        self._reference_metadata = {
            "provider": "cme_fprf_cache",
            "reference_cadence": "daily",
            "captured_at": captured_at.isoformat(),
            "source_business_dates": list(source_dates),
            "configured_roots": len(roots),
            "covered_roots": len(roots),
        }
        self._reference_telemetry = [
            {
                "provider": "cme_fprf",
                "mode": "persistent_cache",
                "configured_roots": len(roots),
                "covered_roots": len(roots),
                "failure_reason": "ok",
            }
        ]
        return tuple(sorted(contracts, key=lambda item: item.ticker))

    def _source_dates_current(self, raw_dates: Sequence[object], reference_date: date) -> bool:
        parsed = {_parse_date(item) for item in raw_dates}
        parsed.discard(None)
        if not parsed:
            return False
        tolerance = timedelta(days=self.source_date_tolerance_days)
        return all(reference_date - tolerance <= item <= reference_date + tolerance for item in parsed)

    @staticmethod
    def _complete(contracts: Sequence[MassiveFuturesContract], roots: Sequence[str]) -> bool:
        covered = {item.product_code.strip().upper() for item in contracts if item.active}
        return set(roots).issubset(covered)

    def _stream(self, response: Any) -> BinaryIO:
        raw = getattr(response, "raw", None)
        if raw is not None and hasattr(raw, "read"):
            try:
                raw.decode_content = True
            except (AttributeError, TypeError):
                pass
            return raw
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return io.BytesIO(content)
        text = getattr(response, "text", None)
        if isinstance(text, str):
            return io.BytesIO(text.encode("utf-8"))
        raise MassiveMultiAssetError("CME FPRF response did not expose a readable body")

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
                    product = str(element.attrib.get("ID") or "").strip().upper()
                    security_type = str(element.attrib.get("SecTyp") or "").strip().upper()
                    status_text = str(element.attrib.get("Status") or "").strip()
                    if product not in roots or security_type != "FUT" or status_text != "1":
                        element.clear()
                        continue
                    maturity = str(element.attrib.get("MMY") or "").strip()
                    ticker = _ticker_from_maturity(product, maturity)
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
                            settlement_date=(None if settlement is None else settlement.isoformat()),
                            active=True,
                            source_identifier=(
                                f"cme-fprf:{exchange_name.lower()}:{product}:{maturity}:"
                                f"{source_date.isoformat()}"
                            ),
                        )
                    )
                    matched_count += 1
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

        telemetry = {
            "provider": "cme_fprf",
            "exchange": exchange_name,
            "http_status": status,
            "instrument_count": instrument_count,
            "matched_contract_count": matched_count,
            "failure_reason": "ok",
        }
        return contracts, business_dates, telemetry

    def _write_cache(
        self,
        *,
        roots: Sequence[str],
        captured_at: datetime,
        business_dates: Sequence[date],
        contracts: Sequence[MassiveFuturesContract],
    ) -> None:
        records = [
            {
                "ticker": item.ticker,
                "product_code": item.product_code,
                "trading_venue": item.trading_venue,
                "first_trade_date": item.first_trade_date,
                "last_trade_date": item.last_trade_date,
                "settlement_date": item.settlement_date,
                "active": item.active,
                "source_identifier": item.source_identifier,
            }
            for item in sorted(contracts, key=lambda contract: contract.ticker)
        ]
        material: dict[str, object] = {
            "schema_version": _CACHE_SCHEMA,
            "captured_at": captured_at.isoformat(),
            "roots": list(sorted(roots)),
            "source_business_dates": [item.isoformat() for item in sorted(set(business_dates))],
            "records": records,
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload = {**material, "cache_id": _cache_id(material)}
        path = self._cache_path(roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _live_cme(
        self,
        *,
        roots: Sequence[str],
        as_of: datetime,
    ) -> tuple[MassiveFuturesContract, ...]:
        target = set(roots)
        contracts: dict[tuple[str, str], MassiveFuturesContract] = {}
        business_dates: set[date] = set()
        telemetry: list[dict[str, object]] = []
        for exchange_name, url in self.file_urls:
            rows, dates, row_telemetry = self._collect_file(
                exchange_name=exchange_name,
                url=url,
                roots=target,
                reference_date=as_of.date(),
            )
            telemetry.append(row_telemetry)
            business_dates.update(dates)
            for row in rows:
                contracts[(row.product_code, row.ticker)] = row
        result = tuple(sorted(contracts.values(), key=lambda item: (item.product_code, item.ticker)))
        if not business_dates or not self._source_dates_current(tuple(business_dates), as_of.date()):
            raise MassiveMultiAssetError("CME FPRF business date is outside the governed current window")
        if not self._complete(result, roots):
            covered = {item.product_code for item in result}
            missing = tuple(sorted(set(roots) - covered))
            raise MassiveMultiAssetError(
                "CME FPRF configured-root coverage incomplete: " + ", ".join(missing)
            )
        captured_at = _aware(self._now(), field_name="CME reference captured_at")
        self._write_cache(
            roots=roots,
            captured_at=captured_at,
            business_dates=tuple(business_dates),
            contracts=result,
        )
        self._reference_telemetry = telemetry
        self._reference_metadata = {
            "provider": "cme_fprf",
            "reference_cadence": "daily",
            "captured_at": captured_at.isoformat(),
            "source_business_dates": [item.isoformat() for item in sorted(business_dates)],
            "configured_roots": len(roots),
            "covered_roots": len(roots),
            "exchange_files": len(self.file_urls),
        }
        return result

    def _fallback(
        self,
        *,
        as_of: datetime,
        roots: Sequence[str],
        maximum_pages: int,
        primary_error: BaseException,
    ) -> tuple[MassiveFuturesContract, ...]:
        fallback = self.fallback_provider
        if fallback is None or not bool(getattr(fallback, "configured", False)):
            raise MassiveMultiAssetError(
                f"CME FPRF primary unavailable and Massive fallback is not configured: {primary_error}"
            ) from primary_error
        try:
            contracts = tuple(
                fallback.futures_contracts(
                    as_of=as_of,
                    product_codes=roots,
                    maximum_pages=maximum_pages,
                )
            )
        except Exception as error:
            raise MassiveMultiAssetError(
                f"CME FPRF primary unavailable; Massive fallback also failed: {error}"
            ) from error
        if not self._complete(contracts, roots):
            raise MassiveMultiAssetError(
                "Massive fallback did not establish complete configured-root coverage"
            )
        self._reference_telemetry = [
            {
                "provider": "cme_fprf",
                "mode": "primary_failed",
                "failure_reason": type(primary_error).__name__,
            },
            {
                "provider": "massive",
                "mode": "secondary_fallback",
                "configured_roots": len(roots),
                "covered_roots": len(roots),
                "failure_reason": "ok",
            },
        ]
        self._reference_metadata = {
            "provider": "massive_fallback",
            "primary_provider": "cme_fprf",
            "reference_cadence": "daily",
            "configured_roots": len(roots),
            "covered_roots": len(roots),
        }
        return tuple(sorted(contracts, key=lambda item: item.ticker))

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        timestamp = _aware(as_of, field_name="as_of")
        roots = tuple(sorted({str(item).strip().upper() for item in product_codes if str(item).strip()}))
        if not roots:
            raise MassiveMultiAssetError("CME futures reference requires configured product roots")
        cached = self._records_from_cache(roots=roots, as_of=timestamp)
        if cached is not None:
            return cached
        try:
            return self._live_cme(roots=roots, as_of=timestamp)
        except (MassiveMultiAssetError, OSError, TypeError, ValueError) as error:
            return self._fallback(
                as_of=timestamp,
                roots=roots,
                maximum_pages=maximum_pages,
                primary_error=error,
            )


__all__ = ["CmeFuturesReferenceProvider"]
