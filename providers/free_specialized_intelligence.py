"""Free specialist research sources for government demand and scientific pipelines.

USAspending, ClinicalTrials.gov, and NIH RePORTER are collected as supporting
research evidence only.  Current retrieval time is preserved as availability time;
these methods never pretend that today's API snapshot was historically available.
They do not authorize candidates, rankings, sizing, portfolio changes, or execution.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import requests

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe(value: object, maximum: int = 1000) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum] or "Public research record"


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class FreeSpecializedIntelligenceProvider:
    """Bounded, retrying client for three credential-free public APIs."""

    USA_SPENDING = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    CLINICAL_TRIALS = "https://clinicaltrials.gov/api/v2/studies"
    NIH_REPORTER = "https://api.reporter.nih.gov/v2/projects/search"

    def __init__(
        self,
        *,
        request: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
        timeout: int = 20,
        attempts: int = 3,
    ) -> None:
        self._request = request or requests.request
        self._clock = clock or _utc_now
        self._sleeper = sleeper or time.sleep
        self.timeout = timeout
        self.attempts = attempts

    def _call(self, method: str, url: str, **kwargs: Any) -> Any:
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self._request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as error:
                last = error
                if attempt < self.attempts:
                    self._sleeper(0.25 * (2 ** (attempt - 1)))
        raise RuntimeError(f"specialized public API request failed: {last}")

    @staticmethod
    def _record(
        *,
        retrieved_at: datetime,
        provider: str,
        source_identifier: str,
        topic: str,
        summary: str,
        entities: tuple[str, ...],
        tags: tuple[str, ...],
        channels: tuple[PortfolioImpactChannel, ...],
        reliability: float,
        materiality: float,
        raw: object,
        license_identifier: str,
    ) -> DecisionInformationRecord:
        content_hash = _hash(raw)
        canonical = hashlib.sha256(
            f"{provider}|{source_identifier}".encode("utf-8")
        ).hexdigest()
        return DecisionInformationRecord(
            identifier=f"specialized:{canonical[:28]}",
            topic=_safe(topic, 300),
            summary=_safe(summary),
            event_at=retrieved_at,
            published_at=retrieved_at,
            available_at=retrieved_at,
            knowledge_cutoff=retrieved_at,
            provenance=InformationProvenance(
                provider=provider,
                source_identifier=source_identifier,
                source_type=InformationSourceType.OFFICIAL,
                retrieved_at=retrieved_at,
                license_identifier=license_identifier,
                usage_rights_identifier="official-public-api.internal-research",
                raw_content_hash=content_hash,
                quality_state=InformationQualityState.LIVE,
                limitations=(
                    "Current API snapshot is not automatically certified for historical replay.",
                    "Entity mapping must be independently verified before candidate-specific reliance.",
                ),
            ),
            canonical_event_identifier=f"event:{canonical}",
            entities=tuple(dict.fromkeys(item for item in entities if item)),
            instruments=(),
            geographies=(),
            sectors=(),
            tags=tuple(dict.fromkeys(tags)),
            impact_channels=channels,
            reliability=reliability,
            relevance=0.65,
            materiality=materiality,
            independence=1.0,
        )

    def usaspending_awards(
        self,
        recipient: str,
        *,
        start_date: str,
        end_date: str,
        limit: int = 100,
    ) -> tuple[DecisionInformationRecord, ...]:
        recipient = recipient.strip()
        if not recipient:
            raise ValueError("recipient cannot be empty")
        payload = {
            "filters": {
                "keywords": [recipient],
                "award_type_codes": ["A", "B", "C", "D"],
                "time_period": [{"start_date": start_date, "end_date": end_date}],
            },
            "fields": [
                "Award ID",
                "Recipient Name",
                "Award Amount",
                "Start Date",
                "End Date",
                "Description",
                "Awarding Agency",
            ],
            "page": 1,
            "limit": max(1, min(int(limit), 100)),
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }
        data = self._call("POST", self.USA_SPENDING, json=payload)
        rows = data.get("results", []) if isinstance(data, Mapping) else []
        retrieved_at = self._clock()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            award_id = _safe(row.get("Award ID") or row.get("generated_unique_award_id"), 200)
            name = _safe(row.get("Recipient Name") or recipient, 300)
            amount = row.get("Award Amount")
            description = _safe(row.get("Description"), 500)
            output.append(
                self._record(
                    retrieved_at=retrieved_at,
                    provider="USAspending.gov",
                    source_identifier=award_id,
                    topic=f"Federal award to {name}",
                    summary=f"Reported federal award amount {amount}; {description}",
                    entities=(name, _safe(row.get("Awarding Agency"), 300)),
                    tags=("government-demand", "federal-award"),
                    channels=(PortfolioImpactChannel.DEMAND, PortfolioImpactChannel.EARNINGS),
                    reliability=0.98,
                    materiality=0.60,
                    raw=row,
                    license_identifier="USAspending-public-api",
                )
            )
        return tuple(output)

    def clinical_trials(
        self,
        query: str,
        *,
        limit: int = 100,
    ) -> tuple[DecisionInformationRecord, ...]:
        query = query.strip()
        if not query:
            raise ValueError("query cannot be empty")
        data = self._call(
            "GET",
            self.CLINICAL_TRIALS,
            params={"query.term": query, "pageSize": max(1, min(int(limit), 1000)), "format": "json"},
        )
        rows = data.get("studies", []) if isinstance(data, Mapping) else []
        retrieved_at = self._clock()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            protocol = row.get("protocolSection", {})
            if not isinstance(protocol, Mapping):
                continue
            identification = protocol.get("identificationModule", {})
            status = protocol.get("statusModule", {})
            sponsor = protocol.get("sponsorCollaboratorsModule", {})
            if not isinstance(identification, Mapping):
                continue
            nct = str(identification.get("nctId", "")).strip()
            if not nct:
                continue
            title = _safe(identification.get("briefTitle") or identification.get("officialTitle"), 500)
            lead = ""
            if isinstance(sponsor, Mapping):
                lead_payload = sponsor.get("leadSponsor", {})
                if isinstance(lead_payload, Mapping):
                    lead = _safe(lead_payload.get("name"), 300)
            overall_status = _safe(status.get("overallStatus") if isinstance(status, Mapping) else "", 100)
            output.append(
                self._record(
                    retrieved_at=retrieved_at,
                    provider="ClinicalTrials.gov",
                    source_identifier=nct,
                    topic=f"Clinical trial {nct}: {title}",
                    summary=f"Lead sponsor {lead or 'unknown'}; status {overall_status}.",
                    entities=((lead,) if lead else ()),
                    tags=("clinical-trial", overall_status),
                    channels=(PortfolioImpactChannel.EARNINGS, PortfolioImpactChannel.REGULATION),
                    reliability=0.99,
                    materiality=0.55,
                    raw=row,
                    license_identifier="ClinicalTrials.gov-public-api",
                )
            )
        return tuple(output)

    def nih_reporter_projects(
        self,
        organization: str,
        *,
        limit: int = 100,
    ) -> tuple[DecisionInformationRecord, ...]:
        organization = organization.strip()
        if not organization:
            raise ValueError("organization cannot be empty")
        payload = {
            "criteria": {"org_names": [organization], "use_relevance": True},
            "include_fields": [
                "ApplId",
                "ProjectNum",
                "ProjectTitle",
                "OrgName",
                "AwardAmount",
                "AwardNoticeDate",
                "FiscalYear",
                "AgencyCode",
            ],
            "offset": 0,
            "limit": max(1, min(int(limit), 500)),
            "sort_field": "award_notice_date",
            "sort_order": "desc",
        }
        data = self._call("POST", self.NIH_REPORTER, json=payload)
        rows = data.get("results", []) if isinstance(data, Mapping) else []
        retrieved_at = self._clock()
        output = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            application = _safe(row.get("appl_id") or row.get("ApplId") or row.get("project_num"), 200)
            org = _safe(row.get("organization", {}).get("org_name") if isinstance(row.get("organization"), Mapping) else row.get("OrgName") or organization, 300)
            title = _safe(row.get("project_title") or row.get("ProjectTitle"), 500)
            amount = row.get("award_amount", row.get("AwardAmount"))
            output.append(
                self._record(
                    retrieved_at=retrieved_at,
                    provider="NIH RePORTER",
                    source_identifier=application,
                    topic=f"NIH-funded research: {title}",
                    summary=f"Organization {org}; reported award amount {amount}.",
                    entities=(org,),
                    tags=("scientific-research", "nih-award"),
                    channels=(PortfolioImpactChannel.DEMAND, PortfolioImpactChannel.EARNINGS),
                    reliability=0.99,
                    materiality=0.50,
                    raw=row,
                    license_identifier="NIH-RePORTER-public-api",
                )
            )
        return tuple(output)


__all__ = ["FreeSpecializedIntelligenceProvider"]
