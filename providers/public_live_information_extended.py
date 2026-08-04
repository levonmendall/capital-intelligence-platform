"""Final normalization layer for expanded public live information sources."""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveSourceDefinition,
    _hash_payload,
)
from providers.public_live_information_runtime import (
    GovernedPublicLiveInformationProvider,
)


def _nonempty(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            normalized
            for value in values
            if (normalized := str(value).strip())
            and normalized.lower() not in {"none", "null", "nan"}
        )
    )


class ImpactfulPublicLiveInformationProvider(
    GovernedPublicLiveInformationProvider
):
    """Normalize optional dimensions and official legacy formats."""

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
        return super()._record(
            source,
            item,
            retrieved_at=retrieved_at,
            topic=topic,
            summary=summary,
            event_at=event_at,
            published_at=published_at,
            source_identifier=source_identifier,
            entities=_nonempty(entities),
            geographies=_nonempty(geographies),
            tags=_nonempty(tags),
        )

    def _parse_ofac_csv(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        text = response.text.lstrip("\ufeff")
        first_row = next(csv.reader(io.StringIO(text)), [])
        normalized_headers = {str(item).strip().lower() for item in first_row}
        expected = {"ent_num", "sdn_name", "sdn_type", "program"}
        if expected & normalized_headers:
            reader = csv.DictReader(io.StringIO(text))
        else:
            reader = csv.DictReader(
                io.StringIO(text),
                fieldnames=(
                    "ent_num",
                    "sdn_name",
                    "sdn_type",
                    "program",
                    "title",
                    "call_sign",
                    "vess_type",
                    "tonnage",
                    "grt",
                    "vess_flag",
                    "vess_owner",
                    "remarks",
                ),
            )
        output: list[DecisionInformationRecord] = []
        for raw in reader:
            item = {
                str(key or "").strip().lower(): value
                for key, value in raw.items()
            }
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

    def _parse_bls_series(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        status = str(payload.get("status", "")).upper() if isinstance(payload, Mapping) else ""
        if status not in {"REQUEST_SUCCEEDED", "REQUEST_SUCCEEDED_WITH_WARNINGS"}:
            raise ValueError("BLS request did not succeed")
        series_rows = payload.get("Results", {}).get("series", [])
        output: list[DecisionInformationRecord] = []
        for series in series_rows:
            if not isinstance(series, Mapping):
                continue
            series_id = str(series.get("seriesID", "")).strip()
            for item in series.get("data", []):
                if not isinstance(item, Mapping):
                    continue
                year = str(item.get("year", "")).strip()
                period = str(item.get("period", "")).strip()
                value = item.get("value")
                if not series_id or not year or not period or value in {None, ""}:
                    continue
                month = period[1:] if period.startswith("M") and period[1:].isdigit() else "01"
                observation_date = f"{year}-{month.zfill(2)}-01"
                output.append(
                    self._record(
                        source,
                        item,
                        retrieved_at=retrieved_at,
                        topic=f"BLS {series_id} observation",
                        summary=f"{series_id} reported {value} for {year} {period}.",
                        event_at=observation_date,
                        published_at=retrieved_at,
                        source_identifier=f"{series_id}:{year}:{period}",
                        geographies=("United States",),
                        tags=("official-statistic", series_id, period),
                    )
                )
        return output

    def _parse_nyfed_rates(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("refRates", []) if isinstance(payload, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            rate_type = str(item.get("type") or item.get("rateType") or "SOFR").strip()
            effective_date = item.get("effectiveDate") or item.get("effective_date")
            rate = item.get("percentRate") or item.get("rate")
            if effective_date is None or rate is None:
                continue
            revision = item.get("revisionIndicator") or item.get("revision_indicator") or ""
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"New York Fed {rate_type}",
                    summary=f"{rate_type} was {rate}% for {effective_date}.",
                    event_at=effective_date,
                    published_at=item.get("publicationTime") or retrieved_at,
                    source_identifier=f"{rate_type}:{effective_date}:{revision}",
                    geographies=("United States",),
                    tags=("reference-rate", rate_type, str(revision)),
                )
            )
        return output

    def _parse_treasury_yield_xml(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        root = ET.fromstring(response.content)
        output: list[DecisionInformationRecord] = []
        for entry in root.findall(".//{*}entry"):
            properties = entry.find(".//{*}properties")
            if properties is None:
                continue
            values = {child.tag.rsplit("}", 1)[-1]: child.text for child in properties}
            observation_date = values.get("NEW_DATE") or values.get("Date")
            yields = {
                key.removeprefix("BC_"): value
                for key, value in values.items()
                if key.startswith("BC_") and value not in {None, ""}
            }
            if not observation_date or not yields:
                continue
            latest = ", ".join(f"{name}={value}%" for name, value in sorted(yields.items()))
            raw = {"observation_date": observation_date, "yields": yields}
            output.append(
                self._record(
                    source,
                    raw,
                    retrieved_at=retrieved_at,
                    topic="U.S. Treasury yield curve",
                    summary=f"Treasury par yields for {observation_date}: {latest}.",
                    event_at=observation_date,
                    published_at=retrieved_at,
                    source_identifier=f"treasury-yield-curve:{observation_date}",
                    geographies=("United States",),
                    tags=("yield-curve", "government-bonds", "interest-rates"),
                )
            )
        return output

    def _parse_sdmx_csv(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        output: list[DecisionInformationRecord] = []
        for raw in reader:
            item = {str(key or "").strip(): value for key, value in raw.items()}
            period = item.get("TIME_PERIOD") or item.get("Time period") or item.get("TIME")
            value = item.get("OBS_VALUE") or item.get("Observation value") or item.get("Value")
            if period in {None, ""} or value in {None, ""}:
                continue
            series_parts = tuple(
                str(item.get(name, "")).strip()
                for name in ("FREQ", "REF_AREA", "MEASURE", "UNIT_MEASURE", "SUBJECT")
                if str(item.get(name, "")).strip()
            )
            series_name = ":".join(series_parts) or source.identifier
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"{source.source_name} observation",
                    summary=f"{series_name} reported {value} for {period}.",
                    event_at=period,
                    published_at=retrieved_at,
                    source_identifier=f"{series_name}:{period}",
                    geographies=((str(item.get("REF_AREA")),) if item.get("REF_AREA") else ()),
                    tags=("official-statistic", "sdmx", series_name),
                )
            )
        return output

    def _parse_eurostat_jsonstat(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        if not isinstance(payload, Mapping):
            return []
        values = payload.get("value", {})
        dimension = payload.get("dimension", {})
        time = dimension.get("time", {}) if isinstance(dimension, Mapping) else {}
        categories = time.get("category", {}).get("index", {}) if isinstance(time, Mapping) else {}
        periods = sorted(categories, key=lambda name: categories[name]) if isinstance(categories, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for index, period in enumerate(periods):
            value = values.get(str(index), values.get(index)) if isinstance(values, Mapping) else None
            if value is None:
                continue
            item = {"period": period, "value": value}
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"{source.source_name} observation",
                    summary=f"Eurostat reported {value} for {period}.",
                    event_at=period,
                    published_at=retrieved_at,
                    source_identifier=f"eurostat:{period}:{value}",
                    geographies=("European Union",),
                    tags=("official-statistic", "eurostat", "national-accounts"),
                )
            )
        return output

    def _parse_bea_api(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        results = payload.get("BEAAPI", {}).get("Results", {}) if isinstance(payload, Mapping) else {}
        rows = results.get("Data", []) if isinstance(results, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            period = item.get("TimePeriod") or item.get("Year")
            value = item.get("DataValue")
            line = item.get("LineDescription") or item.get("LineNumber") or "BEA series"
            if period in {None, ""} or value in {None, ""}:
                continue
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"BEA {line}",
                    summary=f"{line}: {value} for {period}.",
                    event_at=period,
                    published_at=retrieved_at,
                    source_identifier=f"bea:{line}:{period}",
                    geographies=("United States",),
                    tags=("official-statistic", "bea", str(item.get("TableName", "NIPA"))),
                )
            )
        return output

    def _parse_census_eits(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[0], list):
            return []
        headers = [str(item) for item in payload[0]]
        output: list[DecisionInformationRecord] = []
        for row in payload[1:]:
            if not isinstance(row, list):
                continue
            item = dict(zip(headers, row))
            period = item.get("time") or item.get("TIME")
            value_name = next((name for name in headers if name.lower() not in {"time", "time_slot_id", "seasonally_adj"}), None)
            value = item.get(value_name) if value_name else None
            if period in {None, ""} or value in {None, ""}:
                continue
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"Census {value_name or 'economic indicator'}",
                    summary=f"Census reported {value} for {period}.",
                    event_at=period,
                    published_at=retrieved_at,
                    source_identifier=f"census:{value_name}:{period}",
                    geographies=("United States",),
                    tags=("official-statistic", "census", "economic-indicator"),
                )
            )
        return output

    def _parse_usda_quickstats(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            year = item.get("year")
            value = item.get("Value") or item.get("value")
            commodity = item.get("commodity_desc") or "Agricultural commodity"
            statistic = (
                item.get("statisticcat_desc")
                or item.get("short_desc")
                or "USDA observation"
            )
            period = (
                item.get("reference_period_desc")
                or item.get("freq_desc")
                or year
            )
            if year in {None, ""} or value in {None, ""}:
                continue
            geography = (
                item.get("state_name")
                or item.get("country_name")
                or "United States"
            )
            unit = item.get("unit_desc") or "reported units"
            identifier = item.get("CV") or item.get("asd_code") or _hash_payload(item)
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"USDA {commodity} {statistic}",
                    summary=(
                        f"{commodity} {statistic} was {value} {unit} "
                        f"for {period} {year}."
                    ),
                    event_at=str(year),
                    published_at=retrieved_at,
                    source_identifier=f"{identifier}:{year}:{period}",
                    entities=(
                        "USDA National Agricultural Statistics Service",
                        str(commodity),
                    ),
                    geographies=(str(geography),),
                    tags=(
                        "official-statistic",
                        "agriculture",
                        "physical-commodity",
                        "usda-nass",
                    ),
                )
            )
        return output

