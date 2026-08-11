"""Keyless decision-depth parsers for globally relevant public information.

These sources fill specific underwriting gaps rather than broadening the provider
count for its own sake. They remain evidence inputs only: none can authorize a
portfolio action, weaken a readiness gate, or bypass the six-specialist/CIO path.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urljoin

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import (
    PublicLiveInformationError,
    PublicLiveSourceDefinition,
    _hash_payload,
)
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider


_XBRL_FACT_FILING_LIMIT = 8
_XBRL_METADATA_RECORD_LIMIT = 20
_XBRL_FACTS_PER_FILING_LIMIT = 24
_FUNDAMENTAL_CONCEPTS = {
    "revenue": "revenue",
    "revenuefromcontractswithcustomers": "revenue",
    "revenuefromcontractwithcustomerexcludingassessedtax": "revenue",
    "salesrevenue": "revenue",
    "salesrevenuenet": "revenue",
    "profitloss": "net-income",
    "netincomeloss": "net-income",
    "profitlossbeforetax": "pretax-income",
    "incomelossfromcontinuingoperationsbeforeincometaxesextraordinaryitemsnoncontrollinginterest": "pretax-income",
    "operatingprofitloss": "operating-income",
    "operatingincomeloss": "operating-income",
    "assets": "assets",
    "assetscurrent": "current-assets",
    "currentassets": "current-assets",
    "liabilities": "liabilities",
    "liabilitiescurrent": "current-liabilities",
    "currentliabilities": "current-liabilities",
    "equity": "equity",
    "stockholdersequity": "equity",
    "stockholdersequityincludingportionattributabletononcontrollinginterest": "equity",
    "cashandcashequivalents": "cash",
    "cashandcashequivalentsatcarryingvalue": "cash",
    "cashflowsfromusedinoperatingactivities": "operating-cash-flow",
    "netcashprovidedbyusedinoperatingactivities": "operating-cash-flow",
    "basicearningslosspershare": "basic-eps",
    "earningspersharebasic": "basic-eps",
    "dilutedearningslosspershare": "diluted-eps",
    "earningspersharediluted": "diluted-eps",
}


def _first(mapping: Mapping[str, Any], *names: str) -> object | None:
    for name in names:
        value = mapping.get(name)
        if value is not None and value != "":
            return value
    return None


def _local_concept(value: object) -> str:
    raw = str(value or "").strip()
    local = raw.rsplit(":", 1)[-1]
    return "".join(character for character in local.casefold() if character.isalnum())


def _xbrl_entity(
    filing: Mapping[str, Any],
    entities: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    attributes = filing.get("attributes", {})
    relationships = filing.get("relationships", {})
    entity_id = ""
    if isinstance(relationships, Mapping):
        entity_relation = relationships.get("entity", {})
        if isinstance(entity_relation, Mapping):
            entity_data = entity_relation.get("data", {})
            if isinstance(entity_data, Mapping):
                entity_id = str(entity_data.get("id", "")).strip()
    entity_attributes = entities.get(entity_id, {})
    entity_name = str(
        _first(entity_attributes, "name", "legal_name", "entity_name")
        or (
            _first(attributes, "entity_name", "name")
            if isinstance(attributes, Mapping)
            else None
        )
        or entity_id
        or "Unknown reporting entity"
    ).strip()
    lei = str(
        _first(entity_attributes, "lei", "identifier")
        or entity_id
        or ""
    ).strip()
    return entity_name, lei


class FreeDecisionDepthInformationProvider(ImpactfulPublicLiveInformationProvider):
    """Normalize keyless sources that close specific global decision-data gaps."""

    def _collect_source(
        self,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> tuple[tuple[DecisionInformationRecord, ...], str]:
        if source.parser != "xbrl_filings":
            return super()._collect_source(source, retrieved_at)

        # The filing index is intentionally bounded. We then follow only a very small
        # number of the newest xBRL-JSON links so a public-source collection cannot
        # become an unbounded global-filing crawl in the production worker.
        response = self._request(
            source.endpoint,
            parameters=dict(source.parameters),
            headers=dict(source.headers),
        )
        raw_parts = [response.content]
        metadata_records = self._parse_xbrl_filings(response, source, retrieved_at)
        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        included = payload.get("included", []) if isinstance(payload, Mapping) else []
        entities: dict[str, Mapping[str, Any]] = {}
        if isinstance(included, list):
            for item in included:
                if not isinstance(item, Mapping) or item.get("type") != "entity":
                    continue
                identifier = str(item.get("id", "")).strip()
                attributes = item.get("attributes", {})
                if identifier and isinstance(attributes, Mapping):
                    entities[identifier] = attributes

        fact_records: list[DecisionInformationRecord] = []
        if isinstance(rows, list):
            for filing in rows[:_XBRL_FACT_FILING_LIMIT]:
                if not isinstance(filing, Mapping):
                    continue
                attributes = filing.get("attributes", {})
                if not isinstance(attributes, Mapping):
                    continue
                json_url = _first(attributes, "json_url", "xbrl_json_url")
                if not json_url:
                    continue
                endpoint = urljoin(source.endpoint, str(json_url))
                try:
                    fact_response = self._request(
                        endpoint,
                        parameters={},
                        headers={"Accept": "application/json"},
                    )
                    raw_parts.append(fact_response.content)
                    fact_records.extend(
                        self._parse_xbrl_facts(
                            fact_response,
                            source,
                            retrieved_at,
                            filing=filing,
                            entities=entities,
                        )
                    )
                except (PublicLiveInformationError, ValueError):
                    # One malformed/temporarily unavailable filing must not erase the
                    # usable index or other filing facts. Missing fact extraction is
                    # explicit through source limitations and downstream coverage.
                    continue

        records = fact_records + metadata_records[:_XBRL_METADATA_RECORD_LIMIT]
        digest = hashlib.sha256(b"\0".join(raw_parts)).hexdigest()
        return tuple(records[: source.maximum_records]), digest

    def _parse_xbrl_filings(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        """Normalize the filings.xbrl.org JSON:API filing index."""

        payload = response.json()
        if not isinstance(payload, Mapping):
            return []
        rows = payload.get("data", [])
        included = payload.get("included", [])
        if not isinstance(rows, list):
            return []

        entities: dict[str, Mapping[str, Any]] = {}
        if isinstance(included, list):
            for item in included:
                if not isinstance(item, Mapping) or item.get("type") != "entity":
                    continue
                identifier = str(item.get("id", "")).strip()
                attributes = item.get("attributes", {})
                if identifier and isinstance(attributes, Mapping):
                    entities[identifier] = attributes

        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping) or item.get("type") not in {None, "filing"}:
                continue
            filing_id = str(item.get("id", "")).strip()
            attributes = item.get("attributes", {})
            if not filing_id or not isinstance(attributes, Mapping):
                continue

            entity_name, lei = _xbrl_entity(item, entities)
            country = str(_first(attributes, "country", "jurisdiction") or "").strip()
            period_end = _first(
                attributes,
                "period_end",
                "reporting_date",
                "report_date",
                "date",
            )
            publication = _first(
                attributes,
                "publication_date",
                "published",
                "date_added",
                "processed",
                "added",
                "updated",
            ) or retrieved_at
            filing_system = str(
                _first(attributes, "filing_system", "system", "programme") or "XBRL"
            ).strip()
            language = str(_first(attributes, "language", "lang") or "").strip()
            summary_bits = [f"Structured {filing_system} filing for {entity_name}."]
            if country:
                summary_bits.append(f"Jurisdiction {country}.")
            if period_end:
                summary_bits.append(f"Reporting period ended {period_end}.")
            if language:
                summary_bits.append(f"Language {language}.")

            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"Structured company filing: {entity_name}",
                    summary=" ".join(summary_bits),
                    event_at=period_end or publication,
                    published_at=publication,
                    source_identifier=filing_id,
                    entities=tuple(value for value in (entity_name, lei) if value),
                    geographies=((country,) if country else ()),
                    tags=tuple(
                        value
                        for value in (
                            "structured-filing",
                            "xbrl",
                            "global-fundamental-disclosure",
                            filing_system,
                            language,
                            "availability-time-requires-regulator-certification",
                        )
                        if value
                    ),
                )
            )
        return output

    def _parse_xbrl_facts(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
        *,
        filing: Mapping[str, Any],
        entities: Mapping[str, Mapping[str, Any]],
    ) -> list[DecisionInformationRecord]:
        """Extract a bounded set of high-value fundamentals from xBRL-JSON."""

        payload = response.json()
        facts = payload.get("facts", {}) if isinstance(payload, Mapping) else {}
        attributes = filing.get("attributes", {})
        if not isinstance(facts, Mapping) or not isinstance(attributes, Mapping):
            return []
        filing_id = str(filing.get("id", "")).strip()
        entity_name, lei = _xbrl_entity(filing, entities)
        country = str(_first(attributes, "country", "jurisdiction") or "").strip()
        period_end = _first(attributes, "period_end", "reporting_date", "report_date")
        publication = _first(
            attributes,
            "publication_date",
            "published",
            "date_added",
            "processed",
            "added",
            "updated",
        ) or retrieved_at

        output: list[DecisionInformationRecord] = []
        seen_categories: set[tuple[str, str, str]] = set()
        for fact_id, raw_fact in facts.items():
            if not isinstance(raw_fact, Mapping):
                continue
            dimensions = raw_fact.get("dimensions", {})
            if not isinstance(dimensions, Mapping):
                continue
            concept = dimensions.get("concept")
            normalized_concept = _local_concept(concept)
            category = _FUNDAMENTAL_CONCEPTS.get(normalized_concept)
            value = raw_fact.get("value")
            if not category or value is None or value == "":
                continue
            unit = str(dimensions.get("unit", "")).strip()
            period = str(dimensions.get("period", "")).strip()
            fingerprint = (category, period, unit)
            if fingerprint in seen_categories:
                continue
            seen_categories.add(fingerprint)
            decimals = raw_fact.get("decimals")
            fact_payload = {
                "filing_id": filing_id,
                "fact_id": str(fact_id),
                "concept": str(concept),
                "category": category,
                "value": value,
                "unit": unit,
                "period": period,
                "decimals": decimals,
            }
            unit_text = f" {unit}" if unit else ""
            period_text = f" for {period}" if period else ""
            output.append(
                self._record(
                    source,
                    fact_payload,
                    retrieved_at=retrieved_at,
                    topic=f"{entity_name} {category}",
                    summary=(
                        f"{entity_name} reported {category} of {value}{unit_text}{period_text} "
                        f"in structured filing {filing_id}."
                    ),
                    event_at=period_end or publication,
                    published_at=publication,
                    source_identifier=f"{filing_id}:{fact_id}",
                    entities=tuple(value for value in (entity_name, lei) if value),
                    geographies=((country,) if country else ()),
                    tags=tuple(
                        value
                        for value in (
                            "xbrl-fact",
                            "structured-global-fundamentals",
                            category,
                            str(concept),
                            unit,
                            "availability-time-requires-regulator-certification",
                        )
                        if value
                    ),
                )
            )
            if len(output) >= _XBRL_FACTS_PER_FILING_LIMIT:
                break
        return output

    def _parse_treasury_tic_slt(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        """Normalize the latest country rows from Treasury TIC Form SLT table 1."""

        lines = response.text.lstrip("\ufeff").splitlines()
        header_index = next(
            (
                index
                for index, line in enumerate(lines)
                if line.lower().startswith("country\tcountry_code\tdate\t")
            ),
            None,
        )
        if header_index is None:
            raise ValueError("Treasury TIC SLT payload is missing the machine header")
        reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter="\t")
        rows = [
            {str(key or "").strip(): value for key, value in row.items()}
            for row in reader
            if isinstance(row, Mapping)
        ]
        periods = sorted(
            {
                str(row.get("date", "")).strip()
                for row in rows
                if str(row.get("date", "")).strip()
            }
        )
        if not periods:
            return []
        latest_period = periods[-1]
        observation_date = (
            f"{latest_period}-01"
            if len(latest_period) == 7 and latest_period[4] == "-"
            else latest_period
        )

        output: list[DecisionInformationRecord] = []
        for item in rows:
            if str(item.get("date", "")).strip() != latest_period:
                continue
            country = str(item.get("country", "")).strip()
            country_code = str(item.get("country_code", "")).strip()
            if not country or not country_code:
                continue
            total = str(item.get("for_lt_total_pos", "")).strip()
            net = str(item.get("for_lt_total_net", "")).strip()
            treasury = str(item.get("for_lt_treas_pos", "")).strip()
            corporate_bonds = str(item.get("for_lt_corp_pos", "")).strip()
            equities = str(item.get("for_lt_eqty_pos", "")).strip()
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"Treasury TIC cross-border securities: {country}",
                    summary=(
                        f"For {latest_period}, foreign residents associated with {country} "
                        f"reported U.S. long-term securities holdings of {total or 'n.a.'} "
                        f"million dollars and net U.S. sales of {net or 'n.a.'} million; "
                        f"Treasuries {treasury or 'n.a.'}, corporate/other bonds "
                        f"{corporate_bonds or 'n.a.'}, and equities {equities or 'n.a.'} million."
                    ),
                    event_at=observation_date,
                    published_at=retrieved_at,
                    source_identifier=f"tic-slt1:{country_code}:{latest_period}",
                    entities=("U.S. Department of the Treasury",),
                    geographies=(country,),
                    tags=(
                        "cross-border-capital",
                        "portfolio-holdings",
                        "fund-flows-positioning",
                        "foreign-exchange",
                        "rates",
                        "retrieval-time-availability-proxy",
                    ),
                )
            )
        return output

    def _parse_coinmetrics_asset_metrics(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        """Normalize keyless Community API network metrics in shadow mode."""

        payload = response.json()
        rows = payload.get("data", []) if isinstance(payload, Mapping) else []
        if not isinstance(rows, list):
            return []
        output: list[DecisionInformationRecord] = []
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            asset = str(item.get("asset", "")).strip().lower()
            observed = item.get("time")
            if not asset or not observed:
                continue
            metrics = {
                str(key): value
                for key, value in item.items()
                if key not in {"asset", "time"}
                and not str(key).endswith("-status")
                and not str(key).endswith("-status-time")
                and value is not None
            }
            if not metrics:
                continue
            metric_text = ", ".join(
                f"{name}={value}" for name, value in sorted(metrics.items())
            )
            output.append(
                self._record(
                    source,
                    item,
                    retrieved_at=retrieved_at,
                    topic=f"Coin Metrics network activity: {asset.upper()}",
                    summary=f"{asset.upper()} network metrics at {observed}: {metric_text}.",
                    event_at=observed,
                    published_at=retrieved_at,
                    source_identifier=f"coinmetrics:{asset}:{observed}:{_hash_payload(metrics)[:16]}",
                    entities=(asset.upper(),),
                    tags=(
                        "onchain-crypto-network",
                        "network-activity",
                        "shadow-research-only",
                        "non-commercial-community-license",
                        "retrieval-time-availability-proxy",
                    ),
                )
            )
        return output


__all__ = ["FreeDecisionDepthInformationProvider"]
