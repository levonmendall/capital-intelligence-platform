"""Strict bridge from collected public records into supporting CIO evidence.

The public-live collector remains educational and has no investment authority.  This
module only certifies a conservative subset of its already-normalized
``DecisionInformationRecord`` values for use by the existing governed event-forward
pipeline.  Certification cannot create a candidate, rank an opportunity, size a
position, construct a portfolio, execute an order, or authorize real money.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)


_ALLOWED_PRIMARY_TYPES = frozenset(
    {
        InformationSourceType.OFFICIAL,
        InformationSourceType.REGULATORY,
        InformationSourceType.ISSUER,
        InformationSourceType.MARKET,
    }
)
_ALLOWED_QUALITY = frozenset(
    {InformationQualityState.LIVE, InformationQualityState.CORRECTED}
)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return _aware(parsed, field_name=field_name)


def decision_information_record_from_dict(
    payload: Mapping[str, Any],
) -> DecisionInformationRecord:
    """Rebuild the canonical record without weakening any model validation."""

    provenance_payload = payload.get("provenance")
    if not isinstance(provenance_payload, Mapping):
        raise TypeError("decision-information provenance must be an object")
    return DecisionInformationRecord(
        identifier=str(payload["identifier"]),
        topic=str(payload["topic"]),
        summary=str(payload["summary"]),
        event_at=_timestamp(payload["event_at"], field_name="event_at"),
        published_at=_timestamp(payload["published_at"], field_name="published_at"),
        available_at=_timestamp(payload["available_at"], field_name="available_at"),
        knowledge_cutoff=_timestamp(
            payload["knowledge_cutoff"], field_name="knowledge_cutoff"
        ),
        provenance=InformationProvenance(
            provider=str(provenance_payload["provider"]),
            source_identifier=str(provenance_payload["source_identifier"]),
            source_type=InformationSourceType(str(provenance_payload["source_type"])),
            retrieved_at=_timestamp(
                provenance_payload["retrieved_at"], field_name="retrieved_at"
            ),
            license_identifier=str(provenance_payload["license_identifier"]),
            usage_rights_identifier=str(
                provenance_payload["usage_rights_identifier"]
            ),
            raw_content_hash=str(provenance_payload["raw_content_hash"]),
            quality_state=InformationQualityState(
                str(provenance_payload["quality_state"])
            ),
            correction_of_identifier=(
                None
                if provenance_payload.get("correction_of_identifier") is None
                else str(provenance_payload["correction_of_identifier"])
            ),
            limitations=tuple(
                str(item) for item in provenance_payload.get("limitations", ())
            ),
        ),
        canonical_event_identifier=str(payload["canonical_event_identifier"]),
        entities=tuple(str(item) for item in payload.get("entities", ())),
        instruments=tuple(str(item) for item in payload.get("instruments", ())),
        geographies=tuple(str(item) for item in payload.get("geographies", ())),
        sectors=tuple(str(item) for item in payload.get("sectors", ())),
        tags=tuple(str(item) for item in payload.get("tags", ())),
        impact_channels=tuple(
            PortfolioImpactChannel(str(item))
            for item in payload.get("impact_channels", ())
        ),
        reliability=float(payload["reliability"]),
        relevance=float(payload["relevance"]),
        materiality=float(payload["materiality"]),
        independence=float(payload["independence"]),
        corroborating_source_identifiers=tuple(
            str(item)
            for item in payload.get("corroborating_source_identifiers", ())
        ),
        supersedes_identifiers=tuple(
            str(item) for item in payload.get("supersedes_identifiers", ())
        ),
        schema_version=str(
            payload.get("schema_version", "decision-information-record.v1")
        ),
    )


@dataclass(frozen=True, slots=True)
class PublicDecisionInformationPolicy:
    """Conservative admission policy for supporting public decision evidence."""

    minimum_reliability: float = 0.80
    minimum_relevance: float = 0.55
    minimum_materiality: float = 0.40
    minimum_independence_for_secondary: float = 0.75
    minimum_secondary_corroborators: int = 2
    version: str = "public-decision-information-policy.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "minimum_reliability",
            "minimum_relevance",
            "minimum_materiality",
            "minimum_independence_for_secondary",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between zero and one")
        if self.minimum_secondary_corroborators < 1:
            raise ValueError("minimum_secondary_corroborators must be positive")

    def admits(self, record: DecisionInformationRecord) -> bool:
        if record.provenance.quality_state not in _ALLOWED_QUALITY:
            return False
        if record.reliability < self.minimum_reliability:
            return False
        if record.relevance < self.minimum_relevance:
            return False
        if record.materiality < self.minimum_materiality:
            return False
        if not record.provenance.license_identifier.strip():
            return False
        if not record.provenance.usage_rights_identifier.strip():
            return False
        if record.provenance.source_type in _ALLOWED_PRIMARY_TYPES:
            return True
        return (
            record.independence >= self.minimum_independence_for_secondary
            and len(record.corroborating_source_identifiers)
            >= self.minimum_secondary_corroborators
            and record.reliability >= max(0.85, self.minimum_reliability)
        )


@dataclass(frozen=True, slots=True)
class PublicDecisionInformationAudit:
    source_record_count: int
    admitted_record_count: int
    rejected_record_count: int
    policy_version: str
    source_path: str
    candidate_authority: bool = False
    sizing_authority: bool = False
    execution_authority: bool = False
    real_money_authorized: bool = False


class PublicDecisionInformationProvider:
    """Read and certify the rolling public record set at the decision boundary."""

    def __init__(
        self,
        path: str | Path,
        *,
        policy: PublicDecisionInformationPolicy | None = None,
    ) -> None:
        self.path = Path(path)
        self.policy = policy or PublicDecisionInformationPolicy()

    @property
    def name(self) -> str:
        return "certified-public-decision-information"

    def _all_records(self) -> tuple[DecisionInformationRecord, ...]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("records") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            raise ValueError("public decision-information record set is invalid")
        records = tuple(
            decision_information_record_from_dict(item)
            for item in rows
            if isinstance(item, Mapping)
        )
        identifiers = tuple(item.identifier for item in records)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("public decision-information identifiers must be unique")
        return records

    def audit(self) -> PublicDecisionInformationAudit:
        records = self._all_records()
        admitted = sum(1 for item in records if self.policy.admits(item))
        return PublicDecisionInformationAudit(
            source_record_count=len(records),
            admitted_record_count=admitted,
            rejected_record_count=len(records) - admitted,
            policy_version=self.policy.version,
            source_path=str(self.path),
        )

    def records(
        self,
        *,
        start_at: datetime,
        as_of: datetime,
        topics: tuple[str, ...] = (),
        entities: tuple[str, ...] = (),
    ) -> tuple[DecisionInformationRecord, ...]:
        start = _aware(start_at, field_name="start_at")
        cutoff = _aware(as_of, field_name="as_of")
        if start > cutoff:
            raise ValueError("start_at cannot follow as_of")
        requested_topics = {item.strip().casefold() for item in topics if item.strip()}
        requested_entities = {item.strip().casefold() for item in entities if item.strip()}
        selected: list[DecisionInformationRecord] = []
        for record in self._all_records():
            if not self.policy.admits(record):
                continue
            record.require_available_to(cutoff)
            if record.available_at < start:
                continue
            if requested_topics and record.topic.casefold() not in requested_topics:
                continue
            if requested_entities and not requested_entities.intersection(
                item.casefold() for item in record.entities
            ):
                continue
            selected.append(record)
        selected.sort(key=lambda item: (item.available_at, item.identifier))
        return tuple(selected)


def configured_public_record_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    explicit = os.getenv(
        "CAPITAL_INTELLIGENCE_CERTIFIED_PUBLIC_DECISION_INFORMATION_RECORDS",
        "",
    ).strip()
    if explicit:
        return Path(explicit).expanduser()
    explicit = os.getenv("CAPITAL_INTELLIGENCE_PUBLIC_LIVE_RECORDS", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    data_dir = Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()
    return data_dir / "public-live-information-records.json"


def build_public_decision_information_provider(
    path: str | Path | None = None,
) -> PublicDecisionInformationProvider | None:
    resolved = configured_public_record_path(path)
    if not resolved.exists():
        return None
    return PublicDecisionInformationProvider(resolved)


__all__ = [
    "PublicDecisionInformationAudit",
    "PublicDecisionInformationPolicy",
    "PublicDecisionInformationProvider",
    "build_public_decision_information_provider",
    "configured_public_record_path",
    "decision_information_record_from_dict",
]
