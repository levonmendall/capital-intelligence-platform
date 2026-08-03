"""Runtime safeguards and parsers for public live information collection."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import quote

import requests

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveInformationError,
    PublicLiveInformationProvider,
    PublicLiveSourceDefinition,
    _hash_payload,
    _parse_timestamp,
)


def _plain_text(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return " ".join(text.split())


def _date_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if len(raw) == 4 and raw.isdigit():
        return f"{raw}-01-01"
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return value


def _replace_placeholders(value: object, secrets: Mapping[str, str]) -> object:
    if isinstance(value, str):
        output = value
        for name, secret in secrets.items():
            output = output.replace(f"${{{name}}}", secret)
        return output
    if isinstance(value, Mapping):
        return {
            str(key): _replace_placeholders(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_placeholders(item, secrets) for item in value]
    return value


def _redact(message: str, secrets: Mapping[str, str]) -> str:
    output = message
    for value in secrets.values():
        if value:
            output = output.replace(value, "***")
            output = output.replace(quote(value, safe=""), "***")
    return output


class GovernedPublicLiveInformationProvider(PublicLiveInformationProvider):
    """Apply fail-closed parsing, secret redaction, and time safeguards.

    The canonical v1 record currently requires publication time to be at or after
    event time. Official sources may announce a scheduled event before it begins.
    Until a versioned record-contract upgrade is introduced, publication time is
    used as the canonical event boundary and the scheduled onset is retained in a
    deterministic tag and the raw-record hash.
    """

    def _collect_source(
        self,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> tuple[tuple[DecisionInformationRecord, ...], str]:
        secrets = {
            name: os.getenv(name, "").strip()
            for name in source.credential_environment_variables
        }
        endpoint = source.endpoint
        for name, value in secrets.items():
            endpoint = endpoint.replace(f"${{{name}}}", quote(value, safe=""))
        parameters = _replace_placeholders(dict(source.parameters), secrets)
        headers = _replace_placeholders(dict(source.headers), secrets)
        if source.user_agent_environment_variable:
            user_agent = os.getenv(
                source.user_agent_environment_variable,
                "",
            ).strip()
            if not user_agent:
                raise PublicLiveInformationError(
                    f"{source.user_agent_environment_variable} is not configured"
                )
            headers["User-Agent"] = user_agent
        try:
            response = self._request(
                endpoint,
                parameters=parameters,
                headers=headers,
            )
            raw_hash = hashlib.sha256(response.content).hexdigest()
            parser = getattr(self, f"_parse_{source.parser}", None)
            if parser is None:
                raise PublicLiveInformationError(
                    f"unsupported parser {source.parser!r}"
                )
            rows = parser(response, source, retrieved_at)
        except (
            ET.ParseError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            csv.Error,
            requests.RequestException,
            ValueError,
        ) as error:
            raise PublicLiveInformationError(
                _redact(
                    f"{source.identifier} returned an invalid payload: {error}",
                    secrets,
                )
            ) from error
        except PublicLiveInformationError as error:
            raise PublicLiveInformationError(
                _redact(str(error), secrets)
            ) from error
        return tuple(rows[: source.maximum_records]), raw_hash

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
        normalized_raw_event = _date_value(event_at)
        normalized_raw_publication = _date_value(published_at)
        published = _parse_timestamp(
            normalized_raw_publication,
            fallback=retrieved_at,
        )
        normalized_tags = tags
        if published > retrieved_at:
            normalized_tags = normalized_tags + (
                "future-publication-normalized",
                f"reported-publication-at:{published.isoformat()}",
            )
            published = retrieved_at
        event = _parse_timestamp(normalized_raw_event, fallback=published)
        normalized_event: object = event
        if event > published:
            normalized_event = published
            normalized_tags = normalized_tags + (
                "scheduled-event",
                f"scheduled-event-at:{event.isoformat()}",
            )
        return super()._record(
            source,
            item,
            retrieved_at=retrieved_at,
            topic=topic,
            summary=summary,
            event_at=normalized_event,
            published_at=published,
            source_identifier=source_identifier,
            entities=entities,
            geographies=geographies,
            tags=normalized_tags,
        )

    def _parse_federal_register(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("results", []) if isinstance(payload, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            agencies = tuple(
                str(agency.get("name"))
                for agency in item.get("agencies", [])
                if isinstance(agency, Mapping) and agency.get("name")
            )
            title = item.get("title") or item.get("abstract")
            if not title:
                continue
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=title,
                    summary=item.get("abstract") or title,
                    event_at=item.get("publication_date"),
                    published_at=item.get("publication_date"),
                    source_identifier=(
                        item.get("document_number")
                        or item.get("html_url")
                        or _hash_payload(item)
                    ),
                    entities=agencies,
                    geographies=("United States",),
                    tags=(
                        str(item.get("type", "federal-register-document")),
                        str(item.get("presidential_document_type", "")),
                    ),
                )
            )
        return output

    def _parse_ofac_csv(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        output: list[DecisionInformationRecord] = []
        for raw in reader:
            item = {str(key or "").strip().lower(): value for key, value in raw.items()}
            name = (
                item.get("sdn_name")
                or item.get("name")
                or item.get("primary name")
            )
            if not name:
                continue
            entity_type = item.get("sdn_type") or item.get("type") or "target"
            program = item.get("program") or item.get("programs") or "unspecified"
            remarks = item.get("remarks") or item.get("comments") or ""
            identifier = (
                item.get("ent_num")
                or item.get("entity number")
                or _hash_payload(item)
            )
            flag = item.get("vess_flag") or item.get("country") or ""
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"OFAC sanctions listing: {name}",
                    summary=(
                        f"Type {entity_type}; program {program}. "
                        f"{remarks}"
                    ),
                    event_at=retrieved_at,
                    published_at=retrieved_at,
                    source_identifier=identifier,
                    entities=(str(name),),
                    geographies=((str(flag),) if flag else ()),
                    tags=(str(entity_type), str(program), "sanctions-list"),
                )
            )
        return output

    def _parse_fema_open(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = []
        if isinstance(payload, Mapping):
            rows = (
                payload.get("DisasterDeclarationsSummaries")
                or payload.get("disasterDeclarationsSummaries")
                or payload.get("data")
                or []
            )
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            number = item.get("disasterNumber") or item.get("disaster_number")
            title = item.get("declarationTitle") or item.get("incidentType")
            if not number or not title:
                continue
            state = str(item.get("state", "United States"))
            area = str(item.get("designatedArea", ""))
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"FEMA declaration {number}: {title}",
                    summary=(
                        f"{item.get('declarationType', 'Declaration')} for {state} "
                        f"covering {area or 'reported areas'}; incident type "
                        f"{item.get('incidentType', 'unknown')}."
                    ),
                    event_at=(
                        item.get("incidentBeginDate")
                        or item.get("declarationDate")
                    ),
                    published_at=item.get("declarationDate"),
                    source_identifier=f"{number}:{state}:{area}",
                    entities=("Federal Emergency Management Agency",),
                    geographies=tuple(
                        value for value in (state, area) if value
                    ),
                    tags=(
                        str(item.get("incidentType", "disaster")),
                        str(item.get("declarationType", "declaration")),
                    ),
                )
            )
        return output

    def _parse_openfda_enforcement(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("results", []) if isinstance(payload, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            recall_number = item.get("recall_number")
            firm = item.get("recalling_firm") or "Unknown firm"
            product = item.get("product_description") or "Product recall"
            if not recall_number:
                continue
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"FDA recall {recall_number}: {firm}",
                    summary=(
                        f"{product}. Reason: "
                        f"{item.get('reason_for_recall', 'not stated')}. "
                        f"Classification {item.get('classification', 'unknown')}; "
                        f"status {item.get('status', 'unknown')}."
                    ),
                    event_at=(
                        item.get("recall_initiation_date")
                        or item.get("report_date")
                    ),
                    published_at=item.get("report_date"),
                    source_identifier=recall_number,
                    entities=(str(firm),),
                    geographies=tuple(
                        value
                        for value in (
                            str(item.get("state", "")),
                            str(item.get("country", "")),
                            str(item.get("distribution_pattern", "")),
                        )
                        if value
                    ),
                    tags=(
                        str(item.get("classification", "recall")),
                        str(item.get("status", "unknown")),
                    ),
                )
            )
        return output

    def _parse_who_disease_outbreaks(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows: object = payload
        if isinstance(payload, Mapping):
            rows = payload.get("value") or payload.get("items") or payload.get("data") or []
        if not isinstance(rows, list):
            return []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            title = item.get("Title") or item.get("OverrideTitle")
            don_id = item.get("DonId") or item.get("Id") or item.get("UrlName")
            if not title or not don_id:
                continue
            summary = (
                item.get("Summary")
                or item.get("Overview")
                or item.get("Response")
                or title
            )
            publication = (
                item.get("PublicationDateAndTime")
                or item.get("PublicationDate")
                or item.get("DateCreated")
            )
            region = item.get("WhoRegionCode") or item.get("regionscountries")
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=title,
                    summary=_plain_text(summary),
                    event_at=(
                        item.get("EmergencyEventStartDate") or publication
                    ),
                    published_at=publication,
                    source_identifier=don_id,
                    entities=("World Health Organization",),
                    geographies=((str(region),) if region else ("Global",)),
                    tags=("disease-outbreak-news",),
                )
            )
        return output

    def _parse_firms_csv(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        output: list[DecisionInformationRecord] = []
        for item in reader:
            latitude = item.get("latitude")
            longitude = item.get("longitude")
            date = item.get("acq_date")
            raw_time = str(item.get("acq_time", "0"))
            if not latitude or not longitude or not date:
                continue
            try:
                time_value = f"{int(raw_time):04d}"
            except ValueError:
                time_value = "0000"
            observed = (
                f"{date}T{time_value[:2]}:{time_value[2:]}:00+00:00"
            )
            sensor = item.get("satellite") or item.get("instrument") or "satellite"
            confidence = item.get("confidence", "unknown")
            frp = item.get("frp", "unknown")
            source_id = f"{latitude}:{longitude}:{observed}:{sensor}"
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"NASA FIRMS active fire detection near {latitude}, {longitude}",
                    summary=(
                        f"{sensor} active-fire detection; confidence {confidence}; "
                        f"fire radiative power {frp}."
                    ),
                    event_at=observed,
                    published_at=observed,
                    source_identifier=source_id,
                    entities=("NASA FIRMS",),
                    geographies=(f"{latitude},{longitude}",),
                    tags=(
                        str(sensor),
                        str(confidence),
                        str(item.get("daynight", "unknown")),
                    ),
                )
            )
        return output

    def _parse_imf_datamapper(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        values = payload.get("values", {}) if isinstance(payload, Mapping) else {}
        output: list[DecisionInformationRecord] = []
        if not isinstance(values, Mapping):
            return output
        for indicator, country_values in values.items():
            if not isinstance(country_values, Mapping):
                continue
            for country, year_values in country_values.items():
                if not isinstance(year_values, Mapping):
                    continue
                for year, value in year_values.items():
                    if value is None:
                        continue
                    item = {
                        "indicator": indicator,
                        "country": country,
                        "year": year,
                        "value": value,
                    }
                    output.append(
                        self._record(
                            source,
                            item,
                            retrieved_at=retrieved_at,
                            topic=f"IMF {indicator}: {country}",
                            summary=f"{country} {indicator} value {value} for {year}.",
                            event_at=str(year),
                            published_at=str(year),
                            source_identifier=f"{indicator}:{country}:{year}",
                            entities=("International Monetary Fund",),
                            geographies=(str(country),),
                            tags=(
                                "data-observation",
                                "historical-economic-observation",
                                str(indicator),
                                "imf-datamapper",
                            ),
                        )
                    )
        return output
