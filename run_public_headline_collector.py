"""Collect redundant headline metadata for the investor-facing Today surface.

This worker supplements the governed public-information collector with independent
publisher RSS feeds and optional financial-news APIs. It stores headline metadata,
short source-provided descriptions, and original links only. It never stores article
bodies and has no candidate, ranking, sizing, execution, or CIO authority.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import requests

from public_live_record_history import merge_public_event_records


_MAX_DESCRIPTION = 360
_MAX_HEADLINE_AGE = timedelta(hours=48)
_REQUEST_TIMEOUT_SECONDS = 30
_MAX_ATTEMPTS = 4


class PublicHeadlineCollectionError(RuntimeError):
    """Raised when a headline source cannot be retrieved or interpreted."""


@dataclass(frozen=True, slots=True)
class HeadlineSource:
    identifier: str
    provider: str
    endpoint: str
    parser: str
    source_type: str
    independence_group: str
    reliability: float
    key_environment_variable: str | None = None
    parameters: Mapping[str, object] | None = None
    headers: Mapping[str, str] | None = None
    relevance_screen: bool = False

    @property
    def configured(self) -> bool:
        return self.key_environment_variable is None or bool(
            os.getenv(self.key_environment_variable, "").strip()
        )


@dataclass(frozen=True, slots=True)
class HeadlineSourceStatus:
    identifier: str
    provider: str
    configured: bool
    succeeded: bool
    record_count: int
    error: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "provider": self.provider,
            "configured": self.configured,
            "succeeded": self.succeeded,
            "record_count": self.record_count,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class HeadlineCollectionResult:
    evaluated_at: datetime
    records: tuple[dict[str, object], ...]
    sources: tuple[HeadlineSourceStatus, ...]

    @property
    def configured_source_count(self) -> int:
        return sum(item.configured for item in self.sources)

    @property
    def successful_source_count(self) -> int:
        return sum(item.succeeded for item in self.sources)

    @property
    def failed_source_count(self) -> int:
        return sum(item.configured and not item.succeeded for item in self.sources)

    @property
    def provider_count(self) -> int:
        return len(
            {
                str(item.get("provenance", {}).get("provider", ""))
                for item in self.records
                if isinstance(item.get("provenance"), Mapping)
                and str(item.get("provenance", {}).get("provider", "")).strip()
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "public-headline-collection.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "current_record_count": len(self.records),
            "configured_source_count": self.configured_source_count,
            "successful_source_count": self.successful_source_count,
            "failed_source_count": self.failed_source_count,
            "provider_count": self.provider_count,
            "sources": [item.to_dict() for item in self.sources],
            "full_article_text_stored": False,
            "decision_evidence_authority": False,
            "candidate_authority": False,
            "ranking_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "real_money_authorized": False,
        }


def _source(
    identifier: str,
    provider: str,
    endpoint: str,
    *,
    parser: str = "rss",
    source_type: str = "journalism",
    independence_group: str,
    reliability: float,
    key_environment_variable: str | None = None,
    parameters: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
    relevance_screen: bool = False,
) -> HeadlineSource:
    return HeadlineSource(
        identifier=identifier,
        provider=provider,
        endpoint=endpoint,
        parser=parser,
        source_type=source_type,
        independence_group=independence_group,
        reliability=reliability,
        key_environment_variable=key_environment_variable,
        parameters=parameters,
        headers=headers,
        relevance_screen=relevance_screen,
    )


HEADLINE_SOURCES: tuple[HeadlineSource, ...] = (
    _source(
        "bbc-business-rss",
        "BBC Business",
        "https://feeds.bbci.co.uk/news/business/rss.xml",
        independence_group="bbc-news",
        reliability=0.88,
    ),
    _source(
        "bbc-world-rss",
        "BBC World",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        independence_group="bbc-news",
        reliability=0.88,
        relevance_screen=True,
    ),
    _source(
        "npr-business-rss",
        "NPR Business",
        "https://feeds.npr.org/1006/rss.xml",
        independence_group="npr",
        reliability=0.87,
    ),
    _source(
        "npr-economy-rss",
        "NPR Economy",
        "https://feeds.npr.org/1017/rss.xml",
        independence_group="npr",
        reliability=0.87,
    ),
    _source(
        "guardian-business-rss",
        "The Guardian Business",
        "https://www.theguardian.com/business/rss",
        independence_group="guardian-news-media",
        reliability=0.84,
    ),
    _source(
        "coindesk-rss",
        "CoinDesk",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        independence_group="coindesk",
        reliability=0.82,
    ),
    _source(
        "finnhub-general-news",
        "Finnhub",
        "https://finnhub.io/api/v1/news",
        parser="finnhub",
        source_type="alternative",
        independence_group="finnhub",
        reliability=0.78,
        key_environment_variable="FINNHUB_API_KEY",
        parameters={"category": "general", "minId": 0},
    ),
    _source(
        "finnhub-crypto-news",
        "Finnhub",
        "https://finnhub.io/api/v1/news",
        parser="finnhub",
        source_type="alternative",
        independence_group="finnhub",
        reliability=0.78,
        key_environment_variable="FINNHUB_API_KEY",
        parameters={"category": "crypto", "minId": 0},
    ),
    _source(
        "alpha-vantage-market-news",
        "Alpha Vantage Market News",
        "https://www.alphavantage.co/query",
        parser="alpha_vantage",
        source_type="alternative",
        independence_group="alpha-vantage",
        reliability=0.76,
        key_environment_variable="ALPHA_VANTAGE_API_KEY",
        parameters={"function": "NEWS_SENTIMENT", "sort": "LATEST", "limit": 100},
    ),
    _source(
        "eodhd-financial-news",
        "EODHD Financial News",
        "https://eodhd.com/api/news",
        parser="eodhd",
        source_type="alternative",
        independence_group="eodhd",
        reliability=0.78,
        key_environment_variable="EODHD_API_KEY",
        parameters={"fmt": "json", "limit": 100},
    ),
    _source(
        "marketaux-financial-news",
        "Marketaux Financial News",
        "https://api.marketaux.com/v1/news/all",
        parser="marketaux",
        source_type="alternative",
        independence_group="marketaux",
        reliability=0.76,
        key_environment_variable="MARKETAUX_API_TOKEN",
        parameters={"language": "en", "limit": 50, "group_similar": "true"},
    ),
)


_INVESTMENT_TERMS = frozenset(
    {
        "acquisition",
        "bank",
        "bond",
        "business",
        "central bank",
        "ceasefire",
        "commodity",
        "company",
        "conflict",
        "credit",
        "currency",
        "cyber",
        "debt",
        "economy",
        "election",
        "energy",
        "earnings",
        "employment",
        "export",
        "fed",
        "finance",
        "financial",
        "forex",
        "gas",
        "gdp",
        "growth",
        "import",
        "inflation",
        "interest rate",
        "investment",
        "jobs",
        "market",
        "merger",
        "oil",
        "policy",
        "regulation",
        "sanction",
        "shipping",
        "stock",
        "supply",
        "tariff",
        "technology",
        "trade",
        "treasury",
        "unemployment",
        "volatility",
        "yield",
    }
)


def _aware_utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("headline collection requires a timezone-aware timestamp")
    return resolved.astimezone(timezone.utc)


def _plain_text(value: object, *, maximum: int = _MAX_DESCRIPTION) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    normalized = " ".join(text.split())
    return normalized[:maximum]


def _clean_url(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw[:1000]
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))[:1000]


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        scale = 1000.0 if abs(float(value)) > 10_000_000_000 else 1.0
        try:
            parsed = datetime.fromtimestamp(float(value) / scale, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        for pattern in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(raw, pattern).replace(tzinfo=timezone.utc)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(raw)
                except (TypeError, ValueError, OverflowError):
                    return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _entry_value(entry: ET.Element, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for child in entry.iter():
        if child is entry or _local_name(child.tag) not in wanted:
            continue
        text = (child.text or "").strip()
        if text:
            return text
        href = str(child.attrib.get("href", "")).strip()
        if href:
            return href
    return None


def _parse_rss(response: Any) -> list[dict[str, object]]:
    root = ET.fromstring(response.content)
    entries = [
        element
        for element in root.iter()
        if _local_name(element.tag) in {"item", "entry"}
    ]
    output: list[dict[str, object]] = []
    for entry in entries:
        title = _entry_value(entry, "title")
        published = _entry_value(entry, "pubdate", "published", "updated", "date")
        link = _entry_value(entry, "link", "guid", "id")
        summary = _entry_value(entry, "description", "summary", "content", "subtitle")
        if title and published:
            output.append(
                {
                    "title": title,
                    "url": link,
                    "summary": summary,
                    "published_at": published,
                }
            )
    return output


def _json_payload(response: Any) -> object:
    try:
        return response.json()
    except (AttributeError, ValueError) as error:
        raise PublicHeadlineCollectionError(f"invalid JSON payload: {error}") from error


def _parse_finnhub(response: Any) -> list[dict[str, object]]:
    payload = _json_payload(response)
    if not isinstance(payload, list):
        raise PublicHeadlineCollectionError("Finnhub returned a non-list news payload")
    return [
        {
            "title": item.get("headline"),
            "url": item.get("url"),
            "summary": item.get("summary"),
            "published_at": item.get("datetime"),
        }
        for item in payload
        if isinstance(item, Mapping) and item.get("headline")
    ]


def _parse_alpha_vantage(response: Any) -> list[dict[str, object]]:
    payload = _json_payload(response)
    if not isinstance(payload, Mapping):
        raise PublicHeadlineCollectionError("Alpha Vantage returned a non-object payload")
    if payload.get("Note") or payload.get("Information") or payload.get("Error Message"):
        message = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
        raise PublicHeadlineCollectionError(_plain_text(message, maximum=240))
    feed = payload.get("feed", [])
    if not isinstance(feed, list):
        raise PublicHeadlineCollectionError("Alpha Vantage news feed is missing")
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "summary": item.get("summary"),
            "published_at": item.get("time_published"),
        }
        for item in feed
        if isinstance(item, Mapping) and item.get("title")
    ]


def _parse_eodhd(response: Any) -> list[dict[str, object]]:
    payload = _json_payload(response)
    if isinstance(payload, Mapping) and payload.get("error"):
        raise PublicHeadlineCollectionError(_plain_text(payload.get("error"), maximum=240))
    if not isinstance(payload, list):
        raise PublicHeadlineCollectionError("EODHD returned a non-list news payload")
    return [
        {
            "title": item.get("title"),
            "url": item.get("link") or item.get("url"),
            "summary": item.get("content") or item.get("description"),
            "published_at": item.get("date") or item.get("published_at"),
        }
        for item in payload
        if isinstance(item, Mapping) and item.get("title")
    ]


def _parse_marketaux(response: Any) -> list[dict[str, object]]:
    payload = _json_payload(response)
    if not isinstance(payload, Mapping):
        raise PublicHeadlineCollectionError("Marketaux returned a non-object payload")
    if payload.get("error"):
        raise PublicHeadlineCollectionError(_plain_text(payload.get("error"), maximum=240))
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise PublicHeadlineCollectionError("Marketaux news data is missing")
    return [
        {
            "title": item.get("title"),
            "url": item.get("url"),
            "summary": item.get("description") or item.get("snippet"),
            "published_at": item.get("published_at"),
        }
        for item in data
        if isinstance(item, Mapping) and item.get("title")
    ]


_PARSERS: Mapping[str, Callable[[Any], list[dict[str, object]]]] = {
    "rss": _parse_rss,
    "finnhub": _parse_finnhub,
    "alpha_vantage": _parse_alpha_vantage,
    "eodhd": _parse_eodhd,
    "marketaux": _parse_marketaux,
}


def _request_parameters(source: HeadlineSource) -> dict[str, object]:
    parameters = dict(source.parameters or {})
    if source.key_environment_variable:
        secret = os.getenv(source.key_environment_variable, "").strip()
        key_name = {
            "FINNHUB_API_KEY": "token",
            "ALPHA_VANTAGE_API_KEY": "apikey",
            "EODHD_API_KEY": "api_token",
            "MARKETAUX_API_TOKEN": "api_token",
        }[source.key_environment_variable]
        parameters[key_name] = secret
    return parameters


def _retry_after_seconds(response: Any) -> float | None:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return None
    raw = str(headers.get("Retry-After", "")).strip()
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), 60.0))
    except ValueError:
        return None


def _request(
    source: HeadlineSource,
    *,
    http_get: Callable[..., Any],
    sleeper: Callable[[float], None],
) -> Any:
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        response: Any = None
        try:
            response = http_get(
                source.endpoint,
                params=_request_parameters(source),
                headers=dict(source.headers or {}),
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            status_code = int(getattr(response, "status_code", 200) or 200)
            if status_code == 429 or status_code >= 500:
                raise PublicHeadlineCollectionError(
                    f"retryable HTTP status {status_code}",
                )
            response.raise_for_status()
            return response
        except (requests.RequestException, PublicHeadlineCollectionError, OSError) as error:
            last_error = error
            if attempt + 1 >= _MAX_ATTEMPTS:
                break
            retry_after = _retry_after_seconds(response)
            delay = retry_after if retry_after is not None else min(2.0**attempt, 8.0)
            sleeper(delay)
    raise PublicHeadlineCollectionError(f"headline request failed: {last_error}")


def _investment_relevant(title: str, summary: str) -> bool:
    text = f"{title} {summary}".casefold()
    return any(term in text for term in _INVESTMENT_TERMS)


def _normalize_record(
    source: HeadlineSource,
    item: Mapping[str, object],
    *,
    retrieved_at: datetime,
) -> dict[str, object] | None:
    title = _plain_text(item.get("title"), maximum=300)
    summary = _plain_text(item.get("summary"), maximum=_MAX_DESCRIPTION)
    published_at = _parse_time(item.get("published_at"))
    url = _clean_url(item.get("url"))
    if not title or published_at is None:
        return None
    if published_at > retrieved_at + timedelta(minutes=5):
        return None
    if retrieved_at - published_at > _MAX_HEADLINE_AGE:
        return None
    if source.relevance_screen and not _investment_relevant(title, summary):
        return None

    identity_material = f"{source.independence_group}|{url or title}|{published_at.isoformat()}"
    digest = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()
    source_identifier = url or f"{source.identifier}:{digest[:20]}"
    record_summary = summary or f"{title} — {source.provider}"
    return {
        "identifier": f"headline:{source.identifier}:{digest[:24]}",
        "topic": title,
        "summary": record_summary,
        "event_at": published_at.isoformat(),
        "published_at": published_at.isoformat(),
        "available_at": retrieved_at.isoformat(),
        "knowledge_cutoff": retrieved_at.isoformat(),
        "provenance": {
            "provider": source.provider,
            "source_identifier": source_identifier,
            "source_type": source.source_type,
            "retrieved_at": retrieved_at.isoformat(),
            "license_identifier": f"{source.identifier}.headline-metadata",
            "usage_rights_identifier": "headline-metadata-and-source-link-only",
            "raw_content_hash": digest,
            "quality_state": "live",
            "limitations": [
                "Headline metadata, short source description, and original link only; article body is not stored.",
                "Educational awareness only; independent corroboration is required before CIO reliance.",
            ],
        },
        "canonical_event_identifier": f"event:headline:{digest}",
        "entities": [],
        "instruments": [],
        "geographies": [],
        "sectors": [],
        "tags": [
            "current_events_news",
            "broad-news",
            "headline-metadata",
            "metadata-only",
            source.identifier,
        ],
        "impact_channels": ["sentiment"],
        "reliability": source.reliability,
        "relevance": 0.78,
        "materiality": 0.5,
        "independence": 1.0,
    }


def collect_headlines(
    *,
    now: datetime | None = None,
    sources: Iterable[HeadlineSource] = HEADLINE_SOURCES,
    http_get: Callable[..., Any] = requests.get,
    sleeper: Callable[[float], None] = time.sleep,
) -> HeadlineCollectionResult:
    evaluated_at = _aware_utc(now)
    records: list[dict[str, object]] = []
    statuses: list[HeadlineSourceStatus] = []

    for source in sources:
        if not source.configured:
            statuses.append(
                HeadlineSourceStatus(
                    identifier=source.identifier,
                    provider=source.provider,
                    configured=False,
                    succeeded=False,
                    record_count=0,
                    error=f"{source.key_environment_variable} is not configured",
                )
            )
            continue
        try:
            response = _request(source, http_get=http_get, sleeper=sleeper)
            parser = _PARSERS[source.parser]
            parsed = parser(response)
            normalized = [
                record
                for item in parsed
                if (record := _normalize_record(source, item, retrieved_at=evaluated_at))
                is not None
            ]
        except (KeyError, ET.ParseError, TypeError, ValueError, PublicHeadlineCollectionError) as error:
            statuses.append(
                HeadlineSourceStatus(
                    identifier=source.identifier,
                    provider=source.provider,
                    configured=True,
                    succeeded=False,
                    record_count=0,
                    error=str(error)[:500],
                )
            )
            continue
        records.extend(normalized)
        statuses.append(
            HeadlineSourceStatus(
                identifier=source.identifier,
                provider=source.provider,
                configured=True,
                succeeded=True,
                record_count=len(normalized),
                error=None,
            )
        )

    deduplicated = {
        str(item["canonical_event_identifier"]): item
        for item in records
    }
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: str(item.get("published_at", "")),
        reverse=True,
    )
    return HeadlineCollectionResult(
        evaluated_at=evaluated_at,
        records=tuple(ordered),
        sources=tuple(statuses),
    )


def _data_path(environment_name: str, default_name: str) -> Path:
    configured = os.getenv(environment_name, "").strip()
    if configured:
        return Path(configured).expanduser()
    root = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return root / default_name


def _read_mapping(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _acquire_shared_lock(path: Path, *, now: datetime) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    stale_after = timedelta(minutes=20)
    for attempt in range(12):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                return False
            if now - modified_at > stale_after:
                try:
                    path.unlink()
                except OSError:
                    return False
                continue
            if attempt < 11:
                time.sleep(2.0)
                continue
            return False
        try:
            os.write(descriptor, (now.isoformat() + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
        return True
    return False


def persist_headline_collection(result: HeadlineCollectionResult) -> dict[str, object]:
    records_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS",
        "public-live-information-records.json",
    )
    report_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_REPORT",
        "public-headline-collection-report.json",
    )
    state_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_STATE",
        "public-headline-collection-state.json",
    )
    lock_path = _data_path(
        "CAPITAL_INTELLIGENCE_PUBLIC_LIVE_COLLECTION_LOCK",
        "public-live-information-runtime.lock",
    )

    if not _acquire_shared_lock(lock_path, now=result.evaluated_at):
        payload = {
            "schema_version": "public-headline-collection-state.v1",
            "state": "deferred",
            "detail": "The governed public-information collector currently owns the shared persistence lease.",
            "evaluated_at": result.evaluated_at.isoformat(),
            **result.to_dict(),
        }
        _atomic_write(state_path, payload)
        return payload

    try:
        existing = _read_mapping(records_path)
        rolling_records = merge_public_event_records(
            records_path,
            result.records,
            evaluated_at=result.evaluated_at,
        )
        coverage = dict(existing.get("coverage", {})) if isinstance(existing.get("coverage"), Mapping) else {}
        rolling_headline_providers = {
            str(provenance.get("provider", "")).strip()
            for record in rolling_records
            if "broad-news" in {str(tag) for tag in record.get("tags", [])}
            and isinstance((provenance := record.get("provenance")), Mapping)
            and str(provenance.get("provider", "")).strip()
        }
        coverage.update(
            {
                "headline_configured_source_count": result.configured_source_count,
                "headline_successful_source_count": result.successful_source_count,
                "headline_failed_source_count": result.failed_source_count,
                "headline_current_record_count": len(result.records),
                "headline_rolling_provider_count": len(rolling_headline_providers),
                "headline_rolling_record_count": sum(
                    "broad-news" in {str(tag) for tag in record.get("tags", [])}
                    for record in rolling_records
                ),
                "broad_news_ready": bool(rolling_headline_providers),
            }
        )
        records_payload = {
            **existing,
            "schema_version": str(
                existing.get("schema_version", "public-live-information-record-set.v2")
            ),
            "evaluated_at": result.evaluated_at.isoformat(),
            "records": rolling_records,
            "coverage": coverage,
            "headline_coverage": result.to_dict(),
            "full_article_text_stored": False,
            "decision_evidence_authority": False,
            "real_money_authorized": False,
        }
        _atomic_write(records_path, records_payload)
        _atomic_write(report_path, result.to_dict())

        if result.records and result.successful_source_count >= 2:
            state = "available"
            detail = "Independent headline sources supplied current investor-facing metadata."
        elif rolling_headline_providers:
            state = "degraded"
            detail = "Current collection was thin, so recent verified headline metadata remains visible with original timestamps."
        else:
            state = "failed"
            detail = "No current or retained broad-news metadata is available; Today must show the live market-pulse fallback."
        state_payload = {
            "schema_version": "public-headline-collection-state.v1",
            "state": state,
            "detail": detail,
            "evaluated_at": result.evaluated_at.isoformat(),
            "records_path": str(records_path),
            "report_path": str(report_path),
            **result.to_dict(),
        }
        _atomic_write(state_path, state_payload)
        return state_payload
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _interval_seconds() -> int:
    raw = os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_INTERVAL_SECONDS", "300")
    interval = int(raw)
    if not 60 <= interval <= 3600:
        raise ValueError("CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_INTERVAL_SECONDS must be between 60 and 3600")
    return interval


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=int)
    args = parser.parse_args(argv)
    if args.once and args.loop:
        parser.error("--once and --loop are mutually exclusive")
    interval = args.poll_seconds or _interval_seconds()
    if interval < 60:
        parser.error("--poll-seconds must be at least 60")

    run_once = args.once or not args.loop
    while True:
        evaluated_at = datetime.now(timezone.utc)
        try:
            result = collect_headlines(now=evaluated_at)
            state = persist_headline_collection(result)
        except (OSError, TypeError, ValueError, RuntimeError) as error:
            state = {
                "schema_version": "public-headline-collection-state.v1",
                "state": "failed",
                "detail": str(error)[:1000],
                "evaluated_at": evaluated_at.isoformat(),
                "full_article_text_stored": False,
                "decision_evidence_authority": False,
                "real_money_authorized": False,
            }
            try:
                _atomic_write(
                    _data_path(
                        "CAPITAL_INTELLIGENCE_PUBLIC_HEADLINE_STATE",
                        "public-headline-collection-state.json",
                    ),
                    state,
                )
            except OSError:
                pass
        print(json.dumps(state, sort_keys=True), flush=True)
        if run_once:
            return 0 if state.get("state") in {"available", "degraded", "deferred"} else 2
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
