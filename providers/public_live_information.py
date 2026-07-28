"""Live public-source information acquisition with point-in-time provenance.

This adapter deliberately stores normalized metadata and official/public records,
not copyrighted article bodies. Paid newswires, journalism, estimates, exchange
feeds, and proprietary alternative data remain separate licensed providers.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import requests

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)


class PublicLiveInformationError(RuntimeError):
    """Raised when a live public source cannot be retrieved or interpreted."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: object, *, fallback: datetime) -> datetime:
    if value is None or value == "":
        return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        scale = 1000.0 if abs(float(value)) > 10_000_000_000 else 1.0
        return datetime.fromtimestamp(float(value) / scale, tz=timezone.utc)
    raw = str(value).strip()
    if not raw:
        return fallback
    compact_formats = ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%d")
    for pattern in compact_formats:
        try:
            parsed = datetime.strptime(raw, pattern)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return fallback
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _safe_summary(value: object, *, maximum: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum] if text else "Public source update"


@dataclass(frozen=True, slots=True)
class PublicLiveSourceDefinition:
    identifier: str
    source_name: str
    parser: str
    endpoint: str
    source_type: InformationSourceType
    independence_group: str
    domains: tuple[str, ...]
    impact_channels: tuple[PortfolioImpactChannel, ...]
    enabled: bool
    required: bool
    credential_environment_variables: tuple[str, ...]
    user_agent_environment_variable: str | None
    parameters: Mapping[str, Any]
    headers: Mapping[str, str]
    maximum_records: int
    reliability: float
    relevance: float
    materiality: float
    license_identifier: str
    usage_rights_identifier: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "source_name",
            "parser",
            "endpoint",
            "independence_group",
            "license_identifier",
            "usage_rights_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("public live endpoints must use absolute HTTPS URLs")
        if not isinstance(self.enabled, bool) or not isinstance(self.required, bool):
            raise TypeError("enabled and required must be bool values")
        if isinstance(self.maximum_records, bool) or not isinstance(
            self.maximum_records, int
        ) or self.maximum_records < 1:
            raise ValueError("maximum_records must be a positive integer")
        for name in ("reliability", "relevance", "materiality"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)

    @property
    def configured(self) -> bool:
        return all(
            str(os.getenv(name, "")).strip()
            for name in self.credential_environment_variables
        )


@dataclass(frozen=True, slots=True)
class PublicLiveSourceResult:
    source_identifier: str
    source_name: str
    retrieved_at: datetime
    configured: bool
    succeeded: bool
    record_count: int
    content_hash: str | None
    error: str | None
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identifier": self.source_identifier,
            "source_name": self.source_name,
            "retrieved_at": self.retrieved_at.isoformat(),
            "configured": self.configured,
            "succeeded": self.succeeded,
            "record_count": self.record_count,
            "content_hash": self.content_hash,
            "error": self.error,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class PublicLiveCoverageReport:
    catalog_identifier: str
    evaluated_at: datetime
    sources: tuple[PublicLiveSourceResult, ...]
    records: tuple[DecisionInformationRecord, ...]

    @property
    def required_sources_ready(self) -> bool:
        required = tuple(item for item in self.sources if "required" in item.limitations)
        return bool(required) and all(item.succeeded for item in required)

    @property
    def successful_source_count(self) -> int:
        return sum(item.succeeded for item in self.sources)

    @property
    def live_record_count(self) -> int:
        return len(self.records)

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": "public-live-information-report.v1",
            "catalog_identifier": self.catalog_identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "successful_source_count": self.successful_source_count,
            "source_count": len(self.sources),
            "live_record_count": self.live_record_count,
            "sources": [item.to_dict() for item in self.sources],
            "secret_values_disclosed": False,
            "full_article_text_stored": False,
            "real_money_authorized": False,
        }
        if include_records:
            payload["records"] = [item.to_dict() for item in self.records]
        return payload


@dataclass(frozen=True, slots=True)
class PublicLiveSourceCatalog:
    identifier: str
    sources: tuple[PublicLiveSourceDefinition, ...]


def source_from_payload(payload: Mapping[str, Any]) -> PublicLiveSourceDefinition:
    return PublicLiveSourceDefinition(
        identifier=str(payload["identifier"]),
        source_name=str(payload["source_name"]),
        parser=str(payload["parser"]),
        endpoint=str(payload["endpoint"]),
        source_type=InformationSourceType(str(payload["source_type"])),
        independence_group=str(payload["independence_group"]),
        domains=tuple(str(item) for item in payload.get("domains", ())),
        impact_channels=tuple(
            PortfolioImpactChannel(str(item))
            for item in payload.get("impact_channels", ())
        ),
        enabled=bool(payload.get("enabled", True)),
        required=bool(payload.get("required", False)),
        credential_environment_variables=tuple(
            str(item).upper()
            for item in payload.get("credential_environment_variables", ())
        ),
        user_agent_environment_variable=(
            None
            if payload.get("user_agent_environment_variable") is None
            else str(payload["user_agent_environment_variable"]).upper()
        ),
        parameters=dict(payload.get("parameters", {})),
        headers={str(key): str(value) for key, value in payload.get("headers", {}).items()},
        maximum_records=int(payload.get("maximum_records", 100)),
        reliability=float(payload.get("reliability", 0.8)),
        relevance=float(payload.get("relevance", 0.6)),
        materiality=float(payload.get("materiality", 0.5)),
        license_identifier=str(payload["license_identifier"]),
        usage_rights_identifier=str(payload["usage_rights_identifier"]),
        limitations=(
            ("required",) if bool(payload.get("required", False)) else ()
        )
        + tuple(str(item) for item in payload.get("limitations", ())),
    )


def load_public_live_source_catalog(path: str | Path) -> PublicLiveSourceCatalog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    sources = tuple(source_from_payload(item) for item in payload["sources"])
    identifiers = tuple(item.identifier for item in sources)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("public live source identifiers cannot repeat")
    return PublicLiveSourceCatalog(
        identifier=_text(payload["identifier"], field_name="identifier"),
        sources=sources,
    )


class PublicLiveInformationProvider:
    """Retrieve and normalize the widest immediately usable public live coverage."""

    def __init__(
        self,
        catalog: PublicLiveSourceCatalog,
        *,
        timeout: int = 20,
        max_attempts: int = 3,
        http_get: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.catalog = catalog
        self.timeout = timeout
        self.max_attempts = max_attempts
        self._http_get = http_get or requests.get
        self._clock = clock or _utc_now
        self._sleeper = sleeper or time.sleep

    def collect(self, *, include_optional: bool = True) -> PublicLiveCoverageReport:
        evaluated_at = self._clock()
        results: list[PublicLiveSourceResult] = []
        records: list[DecisionInformationRecord] = []
        for source in self.catalog.sources:
            if not source.enabled or (not include_optional and not source.required):
                continue
            if not source.configured:
                results.append(
                    PublicLiveSourceResult(
                        source_identifier=source.identifier,
                        source_name=source.source_name,
                        retrieved_at=evaluated_at,
                        configured=False,
                        succeeded=False,
                        record_count=0,
                        content_hash=None,
                        error="missing required configuration: "
                        + ", ".join(source.credential_environment_variables),
                        limitations=source.limitations,
                    )
                )
                continue
            try:
                source_records, raw_hash = self._collect_source(source, evaluated_at)
            except (PublicLiveInformationError, requests.RequestException, ValueError) as error:
                results.append(
                    PublicLiveSourceResult(
                        source_identifier=source.identifier,
                        source_name=source.source_name,
                        retrieved_at=evaluated_at,
                        configured=True,
                        succeeded=False,
                        record_count=0,
                        content_hash=None,
                        error=str(error),
                        limitations=source.limitations,
                    )
                )
                continue
            records.extend(source_records)
            results.append(
                PublicLiveSourceResult(
                    source_identifier=source.identifier,
                    source_name=source.source_name,
                    retrieved_at=evaluated_at,
                    configured=True,
                    succeeded=True,
                    record_count=len(source_records),
                    content_hash=raw_hash,
                    error=None,
                    limitations=source.limitations,
                )
            )
        deduplicated = {item.content_hash: item for item in records}
        return PublicLiveCoverageReport(
            catalog_identifier=self.catalog.identifier,
            evaluated_at=evaluated_at,
            sources=tuple(results),
            records=tuple(deduplicated.values()),
        )

    def _collect_source(
        self,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> tuple[tuple[DecisionInformationRecord, ...], str]:
        parameters = dict(source.parameters)
        for name in source.credential_environment_variables:
            value = os.getenv(name, "").strip()
            placeholder = f"${{{name}}}"
            for key, current in tuple(parameters.items()):
                if current == placeholder:
                    parameters[key] = value
        headers = dict(source.headers)
        if source.user_agent_environment_variable:
            user_agent = os.getenv(source.user_agent_environment_variable, "").strip()
            if not user_agent:
                raise PublicLiveInformationError(
                    f"{source.user_agent_environment_variable} is not configured"
                )
            headers["User-Agent"] = user_agent
        response = self._request(source.endpoint, parameters=parameters, headers=headers)
        raw_hash = hashlib.sha256(response.content).hexdigest()
        parser = getattr(self, f"_parse_{source.parser}", None)
        if parser is None:
            raise PublicLiveInformationError(f"unsupported parser {source.parser!r}")
        rows = parser(response, source, retrieved_at)
        return tuple(rows[: source.maximum_records]), raw_hash

    def _request(
        self,
        endpoint: str,
        *,
        parameters: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http_get(
                    endpoint,
                    params=dict(parameters),
                    headers=dict(headers),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt == self.max_attempts:
                    break
                self._sleeper(0.25 * (2 ** (attempt - 1)))
        raise PublicLiveInformationError(f"live source request failed: {last_error}")

    def _record(
        self,
        source: PublicLiveSourceDefinition,
        item: Mapping[str, Any],
        *,
        retrieved_at: datetime,
        topic: object,
        summary: object,
        event_at: object,
        published_at: object,
        source_identifier: object,
        entities: tuple[str, ...] = (),
        geographies: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
    ) -> DecisionInformationRecord:
        published = _parse_timestamp(published_at, fallback=retrieved_at)
        event = _parse_timestamp(event_at, fallback=published)
        source_id = _safe_summary(source_identifier, maximum=300)
        item_hash = _hash_payload(item)
        canonical = hashlib.sha256(
            f"{source.identifier}|{source_id}".encode("utf-8")
        ).hexdigest()
        return DecisionInformationRecord(
            identifier=f"live:{source.identifier}:{canonical[:24]}",
            topic=_safe_summary(topic, maximum=300),
            summary=_safe_summary(summary),
            event_at=event,
            published_at=published,
            available_at=retrieved_at,
            knowledge_cutoff=retrieved_at,
            provenance=InformationProvenance(
                provider=source.source_name,
                source_identifier=source_id,
                source_type=source.source_type,
                retrieved_at=retrieved_at,
                license_identifier=source.license_identifier,
                usage_rights_identifier=source.usage_rights_identifier,
                raw_content_hash=item_hash,
                quality_state=InformationQualityState.LIVE,
                limitations=source.limitations,
            ),
            canonical_event_identifier=f"event:{canonical}",
            entities=tuple(dict.fromkeys(entities)),
            instruments=(),
            geographies=tuple(dict.fromkeys(geographies)),
            sectors=(),
            tags=tuple(dict.fromkeys(source.domains + tags)),
            impact_channels=source.impact_channels,
            reliability=source.reliability,
            relevance=source.relevance,
            materiality=source.materiality,
            independence=1.0,
        )

    def _parse_gdelt_doc(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("articles", []) if isinstance(payload, Mapping) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic=item.get("title"),
                summary=f"{item.get('title', '')} [{item.get('domain', '')}]",
                event_at=item.get("seendate"),
                published_at=item.get("seendate"),
                source_identifier=item.get("url") or item.get("title"),
                geographies=(str(item.get("sourcecountry", "global")),),
                tags=(str(item.get("language", "unknown")), "metadata-only"),
            )
            for item in rows
            if isinstance(item, Mapping) and item.get("title")
        ]

    def _parse_rss_atom(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        root = ET.fromstring(response.content)
        entries = root.findall(".//item")
        if not entries:
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        output: list[DecisionInformationRecord] = []
        for entry in entries:
            def first(*names: str) -> str | None:
                for name in names:
                    node = entry.find(name)
                    if node is not None:
                        if node.text and node.text.strip():
                            return node.text.strip()
                        href = node.attrib.get("href")
                        if href:
                            return href
                return None
            title = first("title", "{http://www.w3.org/2005/Atom}title")
            link = first("link", "{http://www.w3.org/2005/Atom}link")
            summary = first("description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content")
            published = first("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated")
            if title:
                item = {"title": title, "link": link, "summary": summary, "published": published}
                output.append(
                    self._record(
                        source,
                        item,
                        retrieved_at=retrieved_at,
                        topic=title,
                        summary=summary or title,
                        event_at=published,
                        published_at=published,
                        source_identifier=link or title,
                    )
                )
        return output

    def _parse_cftc_socrata(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload if isinstance(payload, list) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic=f"CFTC positioning: {item.get('market_and_exchange_names') or item.get('commodity_name')}",
                summary=(
                    f"Open interest {item.get('open_interest_all', 'unknown')}; "
                    f"managed-money long {item.get('m_money_positions_long_all', 'unknown')}; "
                    f"managed-money short {item.get('m_money_positions_short_all', 'unknown')}"
                ),
                event_at=item.get("report_date_as_yyyy_mm_dd"),
                published_at=item.get("report_date_as_yyyy_mm_dd"),
                source_identifier=item.get("id") or _hash_payload(item),
                entities=(str(item.get("contract_market_name", "CFTC")),),
                tags=(str(item.get("commodity_name", "commodity")),),
            )
            for item in rows
            if isinstance(item, Mapping)
        ]

    def _parse_nws_alerts(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("features", []) if isinstance(payload, Mapping) else []
        output = []
        for feature in rows:
            properties = feature.get("properties", {}) if isinstance(feature, Mapping) else {}
            if not isinstance(properties, Mapping):
                continue
            output.append(
                self._record(
                    source,
                    properties,
                    retrieved_at=retrieved_at,
                    topic=properties.get("event") or properties.get("headline"),
                    summary=properties.get("description") or properties.get("headline"),
                    event_at=properties.get("onset") or properties.get("sent"),
                    published_at=properties.get("sent"),
                    source_identifier=properties.get("id") or feature.get("id"),
                    geographies=(str(properties.get("areaDesc", "United States")),),
                    tags=(str(properties.get("severity", "unknown")), str(properties.get("urgency", "unknown"))),
                )
            )
        return output

    def _parse_usgs_geojson(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("features", []) if isinstance(payload, Mapping) else []
        output = []
        for feature in rows:
            properties = feature.get("properties", {}) if isinstance(feature, Mapping) else {}
            if not isinstance(properties, Mapping):
                continue
            output.append(
                self._record(
                    source,
                    properties,
                    retrieved_at=retrieved_at,
                    topic=properties.get("title") or properties.get("place"),
                    summary=f"Magnitude {properties.get('mag', 'unknown')} earthquake near {properties.get('place', 'unknown')}",
                    event_at=properties.get("time"),
                    published_at=properties.get("updated") or properties.get("time"),
                    source_identifier=feature.get("id") or properties.get("url"),
                    geographies=(str(properties.get("place", "global")),),
                    tags=(str(properties.get("type", "earthquake")),),
                )
            )
        return output

    def _parse_cisa_kev(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("vulnerabilities", []) if isinstance(payload, Mapping) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic=f"Known exploited vulnerability: {item.get('cveID')}",
                summary=item.get("shortDescription") or item.get("requiredAction"),
                event_at=item.get("dateAdded"),
                published_at=item.get("dateAdded"),
                source_identifier=item.get("cveID"),
                entities=(str(item.get("vendorProject", "unknown")), str(item.get("product", "unknown"))),
                tags=("known-exploited", str(item.get("knownRansomwareCampaignUse", "unknown"))),
            )
            for item in rows
            if isinstance(item, Mapping) and item.get("cveID")
        ]

    def _parse_treasury_fiscal(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic="U.S. Treasury fiscal update",
                summary="; ".join(f"{key}={value}" for key, value in list(item.items())[:8]),
                event_at=item.get("record_date"),
                published_at=item.get("record_date"),
                source_identifier=f"{source.identifier}:{item.get('record_date', _hash_payload(item))}",
                geographies=("United States",),
            )
            for item in rows
            if isinstance(item, Mapping)
        ]

    def _parse_world_bank(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic=f"World Bank indicator {item.get('indicator', {}).get('value', '')}",
                summary=f"{item.get('country', {}).get('value', '')}: {item.get('value')} ({item.get('date')})",
                event_at=item.get("date"),
                published_at=retrieved_at,
                source_identifier=f"{item.get('countryiso3code')}:{item.get('indicator', {}).get('id')}:{item.get('date')}",
                geographies=(str(item.get("country", {}).get("value", "global")),),
            )
            for item in rows
            if isinstance(item, Mapping) and item.get("value") is not None
        ]

    def _parse_eia_v2(self, response: Any, source: PublicLiveSourceDefinition, retrieved_at: datetime) -> list[DecisionInformationRecord]:
        payload = response.json()
        body = payload.get("response", {}) if isinstance(payload, Mapping) else {}
        rows = body.get("data", []) if isinstance(body, Mapping) else []
        return [
            self._record(
                source,
                item,
                retrieved_at=retrieved_at,
                topic=f"EIA energy update: {item.get('series-description') or item.get('series')}",
                summary="; ".join(f"{key}={value}" for key, value in list(item.items())[:8]),
                event_at=item.get("period"),
                published_at=retrieved_at,
                source_identifier=f"{item.get('series')}:{item.get('period')}",
                geographies=("United States",),
            )
            for item in rows
            if isinstance(item, Mapping)
        ]
