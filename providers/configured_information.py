"""Canonical decision-information adapter for configured datasets."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from data.decision_information import (
    DecisionInformationError,
    DecisionInformationProvider,
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)
from data.provider_dataset import (
    ProviderDatasetProvider,
    ProviderDatasetQuery,
    ProviderDatasetType,
)
from providers.configured_dataset import ConfiguredDatasetProvider


class ConfiguredDecisionInformationError(DecisionInformationError):
    """Raised when configured information cannot satisfy the canonical contract."""


class ConfiguredDecisionInformationProvider:
    """Adapt canonical decision-information records from a reviewed binding."""

    def __init__(self, provider: ProviderDatasetProvider) -> None:
        if not isinstance(provider, ProviderDatasetProvider):
            raise TypeError("provider must implement ProviderDatasetProvider")
        self.provider = provider

    @property
    def name(self) -> str:
        return f"{self.provider.name}:decision-information"

    def records(
        self,
        *,
        start_at: datetime,
        as_of: datetime,
        topics: tuple[str, ...] = (),
        entities: tuple[str, ...] = (),
    ) -> tuple[DecisionInformationRecord, ...]:
        if start_at.tzinfo is None or start_at.utcoffset() is None:
            raise ValueError("start_at must be timezone-aware")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if start_at > as_of:
            raise ValueError("start_at cannot follow as_of")
        try:
            snapshot = self.provider.fetch_dataset(
                ProviderDatasetQuery(
                    dataset_type=ProviderDatasetType.DECISION_INFORMATION,
                    provider_symbol="ALL",
                    as_of=as_of,
                    start_at=start_at,
                    end_at=as_of,
                    limit=1_000_000,
                )
            )
            if not isinstance(snapshot.payload, list):
                raise ConfiguredDecisionInformationError(
                    "decision-information dataset must contain an array"
                )
            records = tuple(_record(item) for item in snapshot.payload)
            identifiers = tuple(item.identifier for item in records)
            if len(identifiers) != len(set(identifiers)):
                raise ConfiguredDecisionInformationError(
                    "decision-information dataset contains duplicate identifiers"
                )
            requested_topics = {item.strip().casefold() for item in topics if item.strip()}
            requested_entities = {item.strip() for item in entities if item.strip()}
            selected: list[DecisionInformationRecord] = []
            for record in records:
                record.require_available_to(as_of)
                if record.available_at < start_at:
                    continue
                if requested_topics and record.topic.casefold() not in requested_topics:
                    continue
                if requested_entities and not requested_entities.intersection(
                    record.entities
                ):
                    continue
                selected.append(record)
            return tuple(selected)
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            if isinstance(error, ConfiguredDecisionInformationError):
                raise
            raise ConfiguredDecisionInformationError(
                f"configured decision information is invalid: {error}"
            ) from error


def _timestamp(value: object, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result):
        raise ValueError(f"{field_name} cannot contain empty values")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


def _record(payload: object) -> DecisionInformationRecord:
    if not isinstance(payload, Mapping):
        raise TypeError("each decision-information record must be an object")
    if payload.get("schema_version") != "decision-information-record.v1":
        raise ValueError("unsupported decision-information record schema")
    provenance = payload["provenance"]
    if not isinstance(provenance, Mapping):
        raise TypeError("provenance must be an object")
    return DecisionInformationRecord(
        identifier=str(payload["identifier"]),
        topic=str(payload["topic"]),
        summary=str(payload["summary"]),
        event_at=_timestamp(payload["event_at"], field_name="event_at"),
        published_at=_timestamp(
            payload["published_at"], field_name="published_at"
        ),
        available_at=_timestamp(
            payload["available_at"], field_name="available_at"
        ),
        knowledge_cutoff=_timestamp(
            payload["knowledge_cutoff"], field_name="knowledge_cutoff"
        ),
        provenance=InformationProvenance(
            provider=str(provenance["provider"]),
            source_identifier=str(provenance["source_identifier"]),
            source_type=InformationSourceType(str(provenance["source_type"])),
            retrieved_at=_timestamp(
                provenance["retrieved_at"], field_name="retrieved_at"
            ),
            license_identifier=str(provenance["license_identifier"]),
            usage_rights_identifier=str(
                provenance["usage_rights_identifier"]
            ),
            raw_content_hash=str(provenance["raw_content_hash"]),
            quality_state=InformationQualityState(
                str(provenance["quality_state"])
            ),
            correction_of_identifier=(
                None
                if provenance.get("correction_of_identifier") is None
                else str(provenance["correction_of_identifier"])
            ),
            limitations=_texts(
                provenance.get("limitations", []), field_name="limitations"
            ),
        ),
        canonical_event_identifier=str(payload["canonical_event_identifier"]),
        entities=_texts(payload.get("entities", []), field_name="entities"),
        instruments=_texts(
            payload.get("instruments", []), field_name="instruments"
        ),
        geographies=_texts(
            payload.get("geographies", []), field_name="geographies"
        ),
        sectors=_texts(payload.get("sectors", []), field_name="sectors"),
        tags=_texts(payload.get("tags", []), field_name="tags"),
        impact_channels=tuple(
            PortfolioImpactChannel(str(item))
            for item in payload.get("impact_channels", [])
        ),
        reliability=float(payload["reliability"]),
        relevance=float(payload["relevance"]),
        materiality=float(payload["materiality"]),
        independence=float(payload["independence"]),
        corroborating_source_identifiers=_texts(
            payload.get("corroborating_source_identifiers", []),
            field_name="corroborating_source_identifiers",
        ),
        supersedes_identifiers=_texts(
            payload.get("supersedes_identifiers", []),
            field_name="supersedes_identifiers",
        ),
        schema_version=str(payload["schema_version"]),
    )


def build_configured_decision_information_provider(
) -> ConfiguredDecisionInformationProvider:
    path = os.getenv("CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING")
    if not path:
        raise ConfiguredDecisionInformationError(
            "CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING is required"
        )
    return ConfiguredDecisionInformationProvider(
        ConfiguredDatasetProvider.from_path(Path(path).expanduser())
    )


__all__ = [
    "ConfiguredDecisionInformationError",
    "ConfiguredDecisionInformationProvider",
    "build_configured_decision_information_provider",
]
