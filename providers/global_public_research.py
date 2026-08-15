"""Bounded public research adapters for global decision-depth maintenance.

These adapters are deliberately operational and non-authoritative.  Large SEC
13F archives stream to disk before parsing, Companies House is candidate-driven,
and Deribit uses public aggregate endpoints.  None of these methods is reachable
from a CIO diagnostic or can authorize a portfolio action.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin

import requests


class GlobalPublicResearchError(RuntimeError):
    """Raised when a bounded public research source cannot be collected safely."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_number(value: object) -> float:
    raw = str(value or "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SEC13FHoldingSummary:
    dataset_url: str
    retrieved_at: datetime
    processed_rows: int
    manager_count: int
    distinct_cusip_count: int
    top_holdings: tuple[Mapping[str, object], ...]
    truncated: bool
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "sec-13f-holding-summary.v1",
            "dataset_url": self.dataset_url,
            "retrieved_at": self.retrieved_at.isoformat(),
            "processed_rows": self.processed_rows,
            "manager_count": self.manager_count,
            "distinct_cusip_count": self.distinct_cusip_count,
            "top_holdings": [dict(item) for item in self.top_holdings],
            "truncated": self.truncated,
            "decision_evidence_authority": False,
            "investment_authority": False,
            "real_money_authorized": False,
            "content_hash": self.content_hash,
        }


class SEC13FStructuredDatasetProvider:
    """Stream and summarize the latest SEC Form 13F structured dataset."""

    INDEX_URL = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        http_get: Callable[..., Any] | None = None,
        timeout: int = 45,
        max_download_bytes: int = 180_000_000,
        max_rows: int = 350_000,
        top_n: int = 100,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.user_agent = _text(user_agent or os.getenv("SEC_USER_AGENT", ""))
        if not self.user_agent:
            raise GlobalPublicResearchError("SEC_USER_AGENT is required for SEC 13F")
        self._http_get = http_get or requests.get
        self.timeout = timeout
        self.max_download_bytes = max_download_bytes
        self.max_rows = max_rows
        self.top_n = top_n
        self._clock = clock or _utc_now

    def _get(self, url: str, **kwargs: object) -> Any:
        headers = {"User-Agent": self.user_agent, "Accept": "*/*"}
        response = self._http_get(
            url,
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def latest_dataset_url(self) -> str:
        configured = _text(os.getenv("CAPITAL_INTELLIGENCE_SEC_13F_DATASET_URL", ""))
        if configured:
            if not configured.startswith("https://www.sec.gov/"):
                raise GlobalPublicResearchError(
                    "configured SEC 13F dataset URL must use sec.gov HTTPS"
                )
            return configured
        response = self._get(self.INDEX_URL)
        text = response.text
        candidates = re.findall(
            r'href=["\']([^"\']+\.zip(?:\?[^"\']*)?)["\']',
            text,
            flags=re.IGNORECASE,
        )
        sec_candidates = [urljoin(self.INDEX_URL, item) for item in candidates]
        sec_candidates = [
            item for item in sec_candidates if item.startswith("https://www.sec.gov/")
        ]
        if not sec_candidates:
            raise GlobalPublicResearchError(
                "SEC 13F index did not expose a structured-dataset ZIP"
            )
        # SEC publishes quarterly archive names containing year/quarter. Lexical
        # ordering is deterministic and avoids depending on page presentation order.
        return sorted(set(sec_candidates))[-1]

    def _stream_archive(self, url: str, directory: Path) -> tuple[Path, str]:
        response = self._get(url, stream=True)
        target = directory / "13f.zip"
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > self.max_download_bytes:
                    raise GlobalPublicResearchError(
                        "SEC 13F archive exceeds bounded download budget"
                    )
                digest.update(chunk)
                handle.write(chunk)
        return target, digest.hexdigest()

    @staticmethod
    def _member(archive: zipfile.ZipFile, name: str) -> str:
        matches = [
            member
            for member in archive.namelist()
            if member.rsplit("/", 1)[-1].casefold() == name.casefold()
        ]
        if not matches:
            raise GlobalPublicResearchError(f"SEC 13F archive is missing {name}")
        return matches[0]

    def collect(self) -> SEC13FHoldingSummary:
        dataset_url = self.latest_dataset_url()
        retrieved_at = self._clock()
        with tempfile.TemporaryDirectory(prefix="capital-intelligence-13f-") as temp:
            archive_path, archive_hash = self._stream_archive(
                dataset_url, Path(temp)
            )
            managers: set[str] = set()
            aggregate: dict[str, dict[str, object]] = {}
            processed = 0
            truncated = False
            with zipfile.ZipFile(archive_path) as archive:
                submission_member = self._member(archive, "SUBMISSION.tsv")
                with archive.open(submission_member) as raw:
                    reader = csv.DictReader(
                        io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"),
                        delimiter="\t",
                    )
                    for row in reader:
                        manager = _text(
                            row.get("CIK")
                            or row.get("FILINGMANAGER_NAME")
                            or row.get("ACCESSION_NUMBER")
                        )
                        if manager:
                            managers.add(manager)
                infotable_member = self._member(archive, "INFOTABLE.tsv")
                with archive.open(infotable_member) as raw:
                    reader = csv.DictReader(
                        io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"),
                        delimiter="\t",
                    )
                    for row in reader:
                        if processed >= self.max_rows:
                            truncated = True
                            break
                        processed += 1
                        cusip = _text(row.get("CUSIP") or row.get("CUSIP_NUMBER"))
                        if not cusip:
                            continue
                        value = _safe_number(row.get("VALUE"))
                        shares = _safe_number(
                            row.get("SSHPRNAMT") or row.get("SHARES_OR_PRINCIPAL_AMOUNT")
                        )
                        current = aggregate.setdefault(
                            cusip,
                            {
                                "cusip": cusip,
                                "issuer": _text(
                                    row.get("NAMEOFISSUER") or row.get("NAME_OF_ISSUER")
                                ),
                                "title_of_class": _text(
                                    row.get("TITLEOFCLASS") or row.get("TITLE_OF_CLASS")
                                ),
                                "reported_value": 0.0,
                                "reported_shares_or_principal": 0.0,
                                "manager_positions": 0,
                            },
                        )
                        current["reported_value"] = round(
                            float(current["reported_value"]) + value, 6
                        )
                        current["reported_shares_or_principal"] = round(
                            float(current["reported_shares_or_principal"]) + shares, 6
                        )
                        current["manager_positions"] = int(
                            current["manager_positions"]
                        ) + 1
            top = tuple(
                sorted(
                    aggregate.values(),
                    key=lambda item: float(item["reported_value"]),
                    reverse=True,
                )[: self.top_n]
            )
        summary_material = {
            "dataset_url": dataset_url,
            "archive_hash": archive_hash,
            "processed_rows": processed,
            "manager_count": len(managers),
            "distinct_cusip_count": len(aggregate),
            "top_holdings": top,
            "truncated": truncated,
        }
        return SEC13FHoldingSummary(
            dataset_url=dataset_url,
            retrieved_at=retrieved_at,
            processed_rows=processed,
            manager_count=len(managers),
            distinct_cusip_count=len(aggregate),
            top_holdings=top,
            truncated=truncated,
            content_hash=_hash(summary_material),
        )


@dataclass(frozen=True, slots=True)
class CompaniesHouseCompanyEvidence:
    company_number: str
    retrieved_at: datetime
    profile: Mapping[str, object]
    recent_filings: tuple[Mapping[str, object], ...]
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "company_number": self.company_number,
            "retrieved_at": self.retrieved_at.isoformat(),
            "profile": dict(self.profile),
            "recent_filings": [dict(item) for item in self.recent_filings],
            "content_hash": self.content_hash,
            "decision_evidence_authority": False,
            "real_money_authorized": False,
        }


class CompaniesHouseProvider:
    """Candidate-driven UK issuer profile and filing-history evidence."""

    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_get: Callable[..., Any] | None = None,
        timeout: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.api_key = _text(api_key or os.getenv("COMPANIES_HOUSE_API_KEY", ""))
        if not self.api_key:
            raise GlobalPublicResearchError(
                "COMPANIES_HOUSE_API_KEY is required for Companies House"
            )
        self._http_get = http_get or requests.get
        self.timeout = timeout
        self._clock = clock or _utc_now

    def _json(self, path: str, *, params: Mapping[str, object] | None = None) -> Mapping[str, Any]:
        response = self._http_get(
            self.BASE_URL + path,
            params=dict(params or {}),
            auth=(self.api_key, ""),
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise GlobalPublicResearchError("Companies House response is malformed")
        return payload

    def collect_company(
        self,
        company_number: str,
        *,
        filing_limit: int = 25,
    ) -> CompaniesHouseCompanyEvidence:
        normalized = re.sub(r"[^A-Za-z0-9]", "", company_number).upper()
        if not normalized:
            raise ValueError("company_number cannot be empty")
        if not 1 <= filing_limit <= 100:
            raise ValueError("filing_limit must be between 1 and 100")
        profile = self._json(f"/company/{normalized}")
        filing_payload = self._json(
            f"/company/{normalized}/filing-history",
            params={"items_per_page": filing_limit},
        )
        items = filing_payload.get("items", [])
        filings = tuple(
            dict(item)
            for item in items
            if isinstance(item, Mapping)
        )[:filing_limit]
        retrieved_at = self._clock()
        material = {
            "company_number": normalized,
            "profile": dict(profile),
            "recent_filings": filings,
        }
        return CompaniesHouseCompanyEvidence(
            company_number=normalized,
            retrieved_at=retrieved_at,
            profile=dict(profile),
            recent_filings=filings,
            content_hash=_hash(material),
        )


@dataclass(frozen=True, slots=True)
class DeribitMarketSummary:
    currency: str
    kind: str
    retrieved_at: datetime
    instruments: tuple[Mapping[str, object], ...]
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "kind": self.kind,
            "retrieved_at": self.retrieved_at.isoformat(),
            "instruments": [dict(item) for item in self.instruments],
            "content_hash": self.content_hash,
            "decision_evidence_authority": False,
            "execution_authority": False,
            "real_money_authorized": False,
        }


class DeribitPublicMarketProvider:
    """Bounded aggregate derivatives context from Deribit's public API."""

    ENDPOINT = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"

    def __init__(
        self,
        *,
        http_get: Callable[..., Any] | None = None,
        timeout: int = 20,
        clock: Callable[[], datetime] | None = None,
        max_records: int = 500,
    ) -> None:
        self._http_get = http_get or requests.get
        self.timeout = timeout
        self._clock = clock or _utc_now
        self.max_records = max_records

    def collect(self, currency: str, *, kind: str) -> DeribitMarketSummary:
        resolved_currency = _text(currency).upper()
        resolved_kind = _text(kind).lower()
        if resolved_currency not in {"BTC", "ETH", "USDC", "USDT"}:
            raise ValueError("unsupported bounded Deribit currency")
        if resolved_kind not in {"future", "option", "spot"}:
            raise ValueError("unsupported Deribit instrument kind")
        response = self._http_get(
            self.ENDPOINT,
            params={"currency": resolved_currency, "kind": resolved_kind},
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("result", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list):
            raise GlobalPublicResearchError("Deribit summary result is malformed")
        normalized: list[Mapping[str, object]] = []
        for raw in rows[: self.max_records]:
            if not isinstance(raw, Mapping):
                continue
            normalized.append(
                {
                    "instrument_name": _text(raw.get("instrument_name")),
                    "open_interest": raw.get("open_interest"),
                    "volume": raw.get("volume"),
                    "volume_usd": raw.get("volume_usd"),
                    "bid_price": raw.get("bid_price"),
                    "ask_price": raw.get("ask_price"),
                    "mark_price": raw.get("mark_price"),
                    "estimated_delivery_price": raw.get("estimated_delivery_price"),
                    "interest_rate": raw.get("interest_rate"),
                    "creation_timestamp": raw.get("creation_timestamp"),
                }
            )
        retrieved_at = self._clock()
        material = {
            "currency": resolved_currency,
            "kind": resolved_kind,
            "instruments": normalized,
        }
        return DeribitMarketSummary(
            currency=resolved_currency,
            kind=resolved_kind,
            retrieved_at=retrieved_at,
            instruments=tuple(normalized),
            content_hash=_hash(material),
        )


__all__ = [
    "CompaniesHouseCompanyEvidence",
    "CompaniesHouseProvider",
    "DeribitMarketSummary",
    "DeribitPublicMarketProvider",
    "GlobalPublicResearchError",
    "SEC13FHoldingSummary",
    "SEC13FStructuredDatasetProvider",
]
