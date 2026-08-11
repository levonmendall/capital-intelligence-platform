"""Keyless decision-depth parsers for globally relevant public information.

These sources fill specific underwriting gaps rather than broadening the provider
count for its own sake.  They remain evidence inputs only: none can authorize a
portfolio action, weaken a readiness gate, or bypass the six-specialist/CIO path.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Mapping

from data.decision_information import DecisionInformationRecord
from providers.public_live_information import PublicLiveSourceDefinition, _hash_payload
from providers.public_live_information_extended import ImpactfulPublicLiveInformationProvider


def _first(mapping: Mapping[str, Any], *names: str) -> object | None:
    for name in names:
        value = mapping.get(name)
        if value not in {None, ""}:
            return value
    return None


class FreeDecisionDepthInformationProvider(ImpactfulPublicLiveInformationProvider):
    """Normalize keyless sources that close specific global decision-data gaps."""

    def _parse_xbrl_filings(
        self,
        response: Any,
        source: PublicLiveSourceDefinition,
        retrieved_at: datetime,
    ) -> list[DecisionInformationRecord]:
        """Normalize the filings.xbrl.org JSON:API filing index.

        XBRL International's index is valuable global fundamental-disclosure
        discovery, but its ``processed`` time is an index-availability proxy rather
        than a universal regulator filing timestamp.  The proxy is therefore made
        explicit in every record and the source remains subject to normal
        point-in-time certification before decision reliance.
        """

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
            relationships = item.get("relationships", {})
            if not filing_id or not isinstance(attributes, Mapping):
                continue

            entity_id = ""
            if isinstance(relationships, Mapping):
                entity_relation = relationships.get("entity", {})
                if isinstance(entity_relation, Mapping):
                    entity_data = entity_relation.get("data", {})
                    if isinstance(entity_data, Mapping):
                        entity_id = str(entity_data.get("id", "")).strip()
            entity_attributes = entities.get(entity_id, {})
            entity_name = str(
                _first(
                    entity_attributes,
                    "name",
                    "legal_name",
                    "entity_name",
                )
                or _first(attributes, "entity_name", "name")
                or entity_id
                or "Unknown reporting entity"
            ).strip()
            lei = str(
                _first(entity_attributes, "lei", "identifier")
                or entity_id
                or ""
            ).strip()
            country = str(_first(attributes, "country", "jurisdiction") or "").strip()
            period_end = _first(
                attributes,
                "period_end",
                "reporting_date",
                "report_date",
                "date",
            )
            processed = _first(
                attributes,
                "processed",
                "date_added",
                "added",
                "updated",
            ) or retrieved_at
            filing_system = str(
                _first(attributes, "filing_system", "system", "programme") or "XBRL"
            ).strip()
            language = str(_first(attributes, "language", "lang") or "").strip()
            summary_bits = [
                f"Structured {filing_system} filing for {entity_name}."
            ]
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
                    event_at=period_end or processed,
                    published_at=processed,
                    source_identifier=filing_id,
                    entities=tuple(value for value in (entity_name, lei) if value),
                    geographies=((country,) if country else ()),
                    tags=tuple(
                        value
                        for value in (
                            "structured-filing",
                            "xbrl",
                            "global-fundamentals",
                            filing_system,
                            language,
                            "processed-time-availability-proxy",
                        )
                        if value
                    ),
                )
            )
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
                    event_at=latest_period,
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
